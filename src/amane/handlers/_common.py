from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from ..db import Library
from ..db.models import MediaIdentityType
from ..library import LibraryHit, LibraryScan
from ..organize import discover_subtitles
from ..parsing import ContentType, file_phase_from_path, parse_file_info
from ..utils.litepan_strm import read_litepan_115_file_id
from ..utils.oshash import compute_oshash
from ..utils.threads import existing_disk_path, in_thread

logger = structlog.get_logger(__name__)


if TYPE_CHECKING:
    from ..db.models import MediaFile
    from ..db.repository import Repository


class LibraryTaskLocks:
    """同库 REFRESH、ORGANIZE 与 DELETE 共用, 执行期串行."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def get(self, library_id: int) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(library_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[library_id] = lock
            return lock


def _maybe_file(f: Path) -> bool:
    """常规文件或符号链接 (含断链) 视为文件入口; 目录不产出."""
    return f.is_file() or f.is_symlink()


@in_thread
def scan_library(scan_dir: Path, *, recursive: bool, scan: LibraryScan) -> list[LibraryHit]:
    """目录本身与回收目录不产出."""
    glob_pattern = "**/*" if recursive else "*"
    hits: list[LibraryHit] = []
    # 跳过目录与回收目录; 其余按规则分类.
    for file_path in scan_dir.glob(glob_pattern):
        if not _maybe_file(file_path):
            continue
        kind = scan.classify(file_path)
        if kind is None:
            continue
        hits.append(LibraryHit(file_path, kind))
    return hits


async def register_media_file(
    repo: Repository,
    library_id: int,
    path: Path,
    *,
    library: Library | None = None,
    mosaic_rules: Mapping[str, str] | None = None,
) -> MediaFile | None:
    """按全局路径唯一性登记; 已被其它媒体库登记时不重复插入、不自动转移."""
    media, created = await repo.create_media_file_if_absent(library_id=library_id, path=str(path))
    if media.library_id != library_id:
        logger.debug(
            "file path already indexed in another library",
            path=str(path),
            existing_library_id=media.library_id,
            requested_library_id=library_id,
        )
        return None
    if created:
        await refresh_file_phase(repo, media, mosaic_rules)
        if library is not None:
            await refresh_external_subtitle(repo, media, library)
    return media


async def refresh_file_phase(
    repo: Repository,
    media: MediaFile,
    mosaic_rules: Mapping[str, str] | None = None,
) -> None:
    """按当前无码识别规则重新计算并持久化 path 派生属性."""
    if media.id is None:
        return
    phase = file_phase_from_path(media.path, mosaic_rules=mosaic_rules)
    updated = await repo.update_media_file(
        media.id,
        mosaic=phase["mosaic"],
        number_content_type=phase.get("number_content_type"),
        hentai=phase.get("hentai", False),
        has_subtitle_in_name=phase["has_subtitle"],
        definition=phase["definition"],
    )
    if updated is not None:
        media.mosaic = updated.mosaic
        media.number_content_type = updated.number_content_type
        media.hentai = updated.hentai
        media.has_subtitle_in_name = updated.has_subtitle_in_name
        media.definition = updated.definition


async def refresh_external_subtitle(repo: Repository, media: MediaFile, library: Library) -> None:
    """按主番号与现有 Metadata 精确匹配同目录外挂字幕, 写回文件级标记.

    不使用目录级存在性判断: 无法解析番号、没有对应 Metadata 或属于其它作品的字幕均不命中.
    """
    extensions = library.subtitle_extensions or []
    parsed = parse_file_info(media.path)
    number_content_type = getattr(parsed, "number_content_type", None) or parsed.content_type
    found = False
    if extensions and parsed.number:
        if number_content_type is ContentType.WESTERN:
            metadata_exists = bool(await repo.list_western_metadata_by_number(parsed.number))
        else:
            metadata_exists = (
                await repo.get_metadata_by_number(parsed.number, content_type=number_content_type)
            ) is not None
        if metadata_exists:
            found = bool(
                await discover_subtitles(
                    Path(media.path),
                    extensions,
                    parsed,
                    metadata_number=parsed.number,
                )
            )
    if media.id is None:
        media.has_external_subtitle = found
        return
    media.has_external_subtitle = found
    await repo.update_media_file(media.id, has_external_subtitle=found)


async def refresh_media_association(repo: Repository, media: MediaFile) -> bool:
    """通过番号限定 WESTERN 候选，再只读核对当前文件身份；命中后恢复关联。"""
    if media.id is None or media.metadata_id is not None:
        return False

    parsed = parse_file_info(media.path)
    number_content_type = getattr(parsed, "number_content_type", None) or parsed.content_type
    metadata = None

    if parsed.number and number_content_type != ContentType.WESTERN:
        metadata = await repo.get_metadata_by_number(parsed.number, content_type=number_content_type)

    elif parsed.number and number_content_type == ContentType.WESTERN:
        candidates = await repo.list_western_metadata_by_number(parsed.number)
        candidate_ids = [item.id for item in candidates if item.id is not None]
        if not candidate_ids:
            return False

        path = Path(media.path)
        if path.suffix.casefold() == ".strm":
            file_115_id = await read_litepan_115_file_id(path)
            if file_115_id:
                metadata = await repo.get_metadata_by_identity_in_candidates(
                    candidate_ids,
                    MediaIdentityType.FILE_115_ID,
                    file_115_id,
                )
        else:
            disk = await existing_disk_path(path)
            if disk is not None:
                current_oshash = await compute_oshash(disk)
                if current_oshash:
                    metadata = await repo.get_metadata_by_identity_in_candidates(
                        candidate_ids,
                        MediaIdentityType.LOCAL_OSHASH,
                        current_oshash,
                    )

    if metadata is None or metadata.id is None:
        return False

    # 恢复关联后立即按 Metadata 重新计算外挂字幕, 避免扫描时因尚无档案而留下假值.
    await repo.finalize_media_file(media.id, metadata.id)
    updated = await repo.get_media_file(media.id)
    if updated is not None:
        library = await repo.get_library(updated.library_id)
        if library is not None:
            await refresh_external_subtitle(repo, updated, library)
    return True


async def ensure_oshash(repo: Repository, media: MediaFile) -> str | None:
    """已有指纹直接返回; STRM 是播放指针, 不计算 OSHASH."""
    if Path(media.path).suffix.casefold() == ".strm":
        return None
    if media.oshash is not None:
        return media.oshash
    disk = await existing_disk_path(Path(media.path))
    if disk is None:
        return None
    media_hash = await compute_oshash(disk)
    if media_hash is None or media.id is None:
        return None
    updated = await repo.update_media_file(media.id, oshash=media_hash)
    return updated.oshash if updated is not None else media_hash


async def finalize_media_file(repo: Repository, media_file_id: int | None, metadata_id: int | None) -> None:
    """media_file_id 为 None 时静默跳过."""
    if media_file_id is None:
        return
    await repo.finalize_media_file(media_file_id, metadata_id)
    media = await repo.get_media_file(media_file_id)
    if media is not None:
        library = await repo.get_library(media.library_id)
        if library is not None:
            await refresh_external_subtitle(repo, media, library)
