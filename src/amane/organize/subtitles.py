from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from ..enums import ActorGender, MoveMode
from ..parsing import FileInfo, parse_file_info
from ..utils.threads import in_thread
from .file import PlaceOutcome, execute_organize
from .path_templates import resolve_subtitle_path

if TYPE_CHECKING:
    from ..db.models import Library, Metadata

logger = structlog.get_logger()


@in_thread
def discover_subtitles(
    video_path: Path,
    extensions: Sequence[str],
    video: FileInfo,
    *,
    metadata_number: str | None = None,
) -> list[Path]:
    """只发现能精确归属当前已入库作品的外挂字幕.

    字幕必须解析出主番号, 与视频主番号及现有 Metadata 番号一致; 不比较 CD 分集.
    无番号、无对应 Metadata 或扩展名未启用的字幕一律不参与匹配.
    """
    if not metadata_number or not video.number or metadata_number.casefold() != video.number.casefold():
        return []
    exts = {e.lower() for e in extensions}
    if not exts:
        return []
    parent = video_path.parent
    if not parent.is_dir():
        return []

    found: list[Path] = []
    for child in parent.iterdir():
        if not child.is_file() or child == video_path:
            continue
        if child.suffix.lower() not in exts:
            continue
        if _belongs(video, parse_file_info(text=child.name)):
            found.append(child)
    found.sort(key=lambda p: p.name.casefold())
    return found


@dataclass(frozen=True, slots=True)
class SubtitleConflict:
    """一条未落盘的字幕: 源路径 + 被占用的目标路径."""

    source: Path
    target: Path


@in_thread
def place_subtitles(
    sources: Sequence[Path],
    video_source: Path,
    video_dest: Path,
    library: Library,
    metadata: Metadata,
    file_info: FileInfo,
    mode: MoveMode,
    safe_dirs: Sequence[Path] | None = (),
    link_dir: Path | None = None,
    link_name: str | None = None,
    actor_genders: Mapping[str, ActorGender] | None = None,
) -> list[SubtitleConflict]:
    """失败与冲突只记日志, 不抛异常; 返回被占用而跳过的字幕源与其目标."""
    conflicted: list[SubtitleConflict] = []
    # 字幕绝不能脱离实际落盘的视频单独移动.
    if not video_dest.is_file() or not metadata.number or not file_info.number:
        return conflicted
    if metadata.number.casefold() != file_info.number.casefold():
        return conflicted
    for sub in sources:
        if not _belongs(file_info, parse_file_info(text=sub.name), metadata.number):
            continue
        dest = resolve_subtitle_path(
            library,
            metadata,
            sub,
            video_dir=video_dest.parent,
            link_dir=link_dir,
            video_name=video_dest.stem,
            video_dest=video_dest,
            link_name=link_name,
            source_path=video_source,
            file_info=file_info,
            safe_dirs=safe_dirs,
            actor_genders=actor_genders,
        )
        result = execute_organize.sync(
            source=sub,
            target_dir=dest.parent,
            target_stem=dest.stem,
            mode=mode,
            suffix=dest.suffix,
        )
        match result.outcome:
            case PlaceOutcome.PLACED:
                pass
            case PlaceOutcome.CONFLICT:
                logger.warning("subtitle target occupied", source=str(sub), dest=str(dest))
                conflicted.append(SubtitleConflict(source=sub, target=dest))
            case PlaceOutcome.FAILED:
                logger.warning("subtitle organize failed", source=str(sub), dest=str(dest), error=result.error)
    return conflicted


def _belongs(video: FileInfo, sub: FileInfo, metadata_number: str | None = None) -> bool:
    """只按主番号精确归属; 不允许无番号回退, CD 分集不参与字幕归属."""
    if not metadata_number or not video.number or not sub.number:
        return False
    expected = video.number.casefold()
    return metadata_number.casefold() == expected and sub.number.casefold() == expected
