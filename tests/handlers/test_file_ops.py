"""测试 file ops 消费已物化 URL (内部派生 / 外部) + trailer 落盘."""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from PIL import Image

from amane.config import HotSettings, WatermarkConfig
from amane.db.models import MediaFile, Metadata
from amane.enums import DownloadableResource, SiteName
from amane.handlers.file import _uses_western_image_flow, _write_into_library, execute_file_operations
from amane.media import ResourceStore
from amane.organize import MoveMode, PlaceOutcome, ResolvedPaths
from amane.parsing import ContentType, parse_file_info

if TYPE_CHECKING:
    from amane.net.http import WebClient


class FakeClient:
    """download 写出小图/视频占位."""

    async def download(self, url: str, dest: Path, **kwargs) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".mp4"):
            dest.write_bytes(b"video")
        else:
            Image.new("RGB", (800, 538), "blue").save(dest)
        return True

    async def get_filesize(self, url: str, **kwargs):
        return None

    async def resolve_final_url(self, url: str, **kwargs) -> str:
        return url


def _pixel(path: Path) -> tuple[int, int, int]:
    with Image.open(path) as img:
        return cast("tuple[int, int, int]", img.convert("RGB").getpixel((0, 0)))


def _paths(base: Path) -> ResolvedPaths:
    return ResolvedPaths(
        video=base / "MIDV-123" / "MIDV-123.mp4",
        thumb=base / "MIDV-123" / "thumb.jpg",
        poster=base / "MIDV-123" / "poster.jpg",
        fanart=base / "MIDV-123" / "fanart.jpg",
        extrafanart_dir=base / "MIDV-123" / "extrafanart",
        nfo=base / "MIDV-123" / "MIDV-123.nfo",
        trailer=base / "MIDV-123" / "trailer.mp4",
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (SiteName.PONDO, True),
        (SiteName.TENMUSUME, True),
        (SiteName.CARIBBEANCOM, True),
        (SiteName.TOKYO_HOT, False),
    ],
)
def test_uncensored_streaming_image_flow_by_actual_source(source: SiteName, expected: bool) -> None:
    """无码流媒体按实际图片来源决定是否采用欧美图片流程."""
    url = "https://example.com/cover.jpg"
    metadata = Metadata(
        number="HEYZO-1234",
        content_type=ContentType.UNCENSORED,
        original_cover_urls=[url],
        image_sources={url: str(source)},
    )

    assert _uses_western_image_flow(metadata, HotSettings()) is expected


def test_uncensored_dvd_keeps_original_image_flow() -> None:
    """无码 DVD 不因图片来源而进入欧美图片流程."""
    url = "https://example.com/cover.jpg"
    metadata = Metadata(
        number="RED-163",
        content_type=ContentType.UNCENSORED,
        original_cover_urls=[url],
        image_sources={url: str(SiteName.PONDO)},
    )

    assert _uses_western_image_flow(metadata, HotSettings()) is False


def test_censored_keeps_original_image_flow() -> None:
    """日本有码不受无码流媒体分流规则影响."""
    url = "https://example.com/cover.jpg"
    metadata = Metadata(
        number="MIDV-123",
        content_type=ContentType.CENSORED,
        original_cover_urls=[url],
        image_sources={url: str(SiteName.PONDO)},
    )

    assert _uses_western_image_flow(metadata, HotSettings()) is False


def test_western_always_uses_western_image_flow() -> None:
    """欧美作品始终采用欧美图片流程."""
    metadata = Metadata(
        number="ABC-123",
        content_type=ContentType.WESTERN,
    )

    assert _uses_western_image_flow(metadata, HotSettings()) is True


def test_uncensored_streaming_without_image_source_keeps_original_flow() -> None:
    """缺少真实图片来源记录时，不擅自推断为欧美图片流程."""
    metadata = Metadata(
        number="HEYZO-1234",
        content_type=ContentType.UNCENSORED,
    )

    assert _uses_western_image_flow(metadata, HotSettings()) is False


@pytest.mark.asyncio
async def test_internal_poster_and_trailer(resource_store: ResourceStore, tmp_path: Path):
    """poster = 内部派生 URL → 从 store 取文件; trailer 下载并复制."""
    client = cast("WebClient", FakeClient())

    # 造一个裁剪派生资源, 作为 metadata 的内部 poster URL
    async def producer(dest: Path) -> bool:
        Image.new("RGB", (379, 538), "red").save(dest)
        return True

    crop = await resource_store.acquire_derived("https://s/t.jpg", "crop", "0.7", producer)
    assert crop is not None
    internal_url = f"/api/resources/{ResourceStore.url_hash(crop.url)}"

    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(
        number="MIDV-123",
        cover_urls=["https://s/t.jpg"],
        poster_urls=[internal_url],
        trailer_urls=["https://s/trailer.mp4"],
    )
    out_base = tmp_path / "out"
    paths = _paths(out_base)

    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
    )
    assert result.outcome is PlaceOutcome.PLACED
    assert paths.thumb.exists()  # 外部下载
    assert paths.poster.exists()  # 内部派生解析
    assert paths.trailer.exists()  # trailer 落盘
    assert paths.trailer.read_bytes() == b"video"


@pytest.mark.asyncio
async def test_target_occupied_returns_before_side_effects(resource_store: ResourceStore, tmp_path: Path):
    """目标被占用时立即返回: 不下载图片、不写 NFO、不动磁盘."""
    client = cast("WebClient", FakeClient())

    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    paths = _paths(tmp_path / "out")
    paths.video.parent.mkdir(parents=True)
    paths.video.write_text("existing content")

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(number="MIDV-123", cover_urls=["https://s/t.jpg"])

    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.MOVE,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
    )

    assert result.outcome is PlaceOutcome.CONFLICT
    assert result.conflict_target == paths.video
    assert paths.video.read_text() == "existing content"
    assert src.read_bytes() == b"movie"
    assert not paths.thumb.exists()
    assert not paths.nfo.exists()


@pytest.mark.asyncio
async def test_unknown_target_state_returns_before_side_effects(
    resource_store: ResourceStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """读不出目标状态时立即返回并记为失败: 不下载图片、不写 NFO、不动磁盘."""
    client = cast("WebClient", FakeClient())

    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    paths = _paths(tmp_path / "out")
    paths.video.parent.mkdir(parents=True)
    paths.video.write_text("existing content")

    def denied(self: Path, other: object) -> bool:
        raise PermissionError(13, "Permission denied", str(other))

    monkeypatch.setattr(Path, "samefile", denied)

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(number="MIDV-123", cover_urls=["https://s/t.jpg"])

    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.MOVE,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
    )

    assert result.outcome is PlaceOutcome.FAILED
    assert result.error is not None
    assert "Permission denied" in result.error
    assert result.conflict_target is None
    assert paths.video.read_text() == "existing content"
    assert src.read_bytes() == b"movie"
    assert not paths.thumb.exists()
    assert not paths.nfo.exists()


@pytest.mark.asyncio
async def test_copy_resources_skips_trailer(resource_store: ResourceStore, tmp_path: Path):
    """copy_resources 不含 trailer 时不落盘预告片, 仍复制封面."""
    client = cast("WebClient", FakeClient())
    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(number="MIDV-123", cover_urls=["https://s/t.jpg"], trailer_urls=["https://s/trailer.mp4"])
    paths = _paths(tmp_path / "out")
    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
        copy_resources=[DownloadableResource.thumb, DownloadableResource.poster],
    )
    assert result.outcome is PlaceOutcome.PLACED
    assert paths.thumb.exists()
    assert not paths.trailer.exists()


@pytest.mark.asyncio
async def test_write_nfo_false_skips_nfo(resource_store: ResourceStore, tmp_path: Path):
    client = cast("WebClient", FakeClient())
    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(number="MIDV-123", title="T", cover_urls=["https://s/t.jpg"])
    paths = _paths(tmp_path / "out")
    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
        write_nfo=False,
    )
    assert result.outcome is PlaceOutcome.PLACED
    assert not paths.nfo.exists()


@pytest.mark.asyncio
async def test_missing_internal_resource_falls_back_to_crop(resource_store: ResourceStore, tmp_path: Path):
    """poster 内部 URL 指向不存在资源 → 回退从 thumb 裁剪."""
    client = cast("WebClient", FakeClient())
    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(
        number="MIDV-123",
        content_type=ContentType.CENSORED,
        cover_urls=["https://s/t.jpg"],
        poster_urls=["/api/resources/deadbeefdeadbeef"],  # 不存在
    )
    paths = _paths(tmp_path / "out")
    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
    )
    assert result.outcome is PlaceOutcome.PLACED
    assert paths.poster.exists()  # 裁剪回退


@pytest.mark.asyncio
async def test_western_missing_internal_poster_does_not_fall_back_to_crop(
    resource_store: ResourceStore, tmp_path: Path
):
    """WESTERN 的内部海报 URL 不存在时, 不回退从封面裁剪."""
    client = cast("WebClient", FakeClient())
    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(
        number="MIDV-123",
        content_type=ContentType.WESTERN,
        cover_urls=["https://s/t.jpg"],
        poster_urls=["/api/resources/deadbeefdeadbeef"],  # 不存在
    )
    paths = _paths(tmp_path / "out")

    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
    )

    assert result.outcome is PlaceOutcome.PLACED
    assert paths.thumb.exists()
    assert not paths.poster.exists()  # 欧美不允许回退裁剪


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_watermark_respects_enabled(resource_store: ResourceStore, tmp_path: Path, enabled: bool):
    client = cast("WebClient", FakeClient())
    src = tmp_path / "src" / "MIDV-123-C.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    user_dir = tmp_path / "watermarks"
    user_dir.mkdir()
    Image.new("RGBA", (40, 20), (255, 0, 0, 255)).save(user_dir / "subtitle.png")

    mf = MediaFile(path=str(src), library_id=1)
    meta = Metadata(number="MIDV-123", cover_urls=["https://s/t.jpg"])
    paths = _paths(tmp_path / "out")
    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src, has_external_subtitle=mf.has_external_subtitle),
        web_client=client,
        config=HotSettings(watermark=WatermarkConfig(enabled=enabled, scale=0.2)),
        watermark_dir=user_dir,
    )
    assert result.outcome is PlaceOutcome.PLACED
    with Image.open(paths.thumb) as img:
        pixel = img.convert("RGB").getpixel((20, 20))
    assert isinstance(pixel, tuple)
    if enabled:
        assert pixel[0] > 180 and pixel[2] < 80
    else:
        assert pixel[2] > 180 and pixel[0] < 80


@pytest.mark.asyncio
async def test_watermark_from_external_subtitle(resource_store: ResourceStore, tmp_path: Path):
    """文件名没有 -C 时, 库里的同目录字幕命中同样打出封面中字角标."""
    client = cast("WebClient", FakeClient())
    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")

    user_dir = tmp_path / "watermarks"
    user_dir.mkdir()
    Image.new("RGBA", (40, 20), (255, 0, 0, 255)).save(user_dir / "subtitle.png")

    mf = MediaFile(path=str(src), library_id=1, has_external_subtitle=True)
    meta = Metadata(number="MIDV-123", cover_urls=["https://s/t.jpg"])
    paths = _paths(tmp_path / "out")
    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src, has_external_subtitle=mf.has_external_subtitle),
        web_client=client,
        config=HotSettings(watermark=WatermarkConfig(enabled=True, scale=0.2)),
        watermark_dir=user_dir,
    )
    assert result.outcome is PlaceOutcome.PLACED
    with Image.open(paths.thumb) as img:
        pixel = img.convert("RGB").getpixel((20, 20))
    assert isinstance(pixel, tuple)
    assert pixel[0] > 180 and pixel[2] < 80


@pytest.mark.asyncio
async def test_in_place_rewrites_existing_artifacts(resource_store: ResourceStore, tmp_path: Path) -> None:
    """源已在目标路径上时仍重写库路径上的旧产物: NFO 按本次元数据, 图片与预告片按本次资源.

    fanart 与 thumb 同源, 因此与 thumb 一同重写.
    """
    client = cast("WebClient", FakeClient())

    paths = _paths(tmp_path / "out")
    paths.video.parent.mkdir(parents=True)
    paths.video.write_bytes(b"movie")
    paths.nfo.write_text("旧 NFO", encoding="utf-8")
    stale = (paths.thumb, paths.poster, paths.fanart)
    before = {}
    for image in stale:
        Image.new("RGB", (800, 538), "red").save(image)
        before[image] = _pixel(image)
    paths.trailer.write_bytes(b"old trailer")

    mf = MediaFile(path=str(paths.video), library_id=1)
    meta = Metadata(
        number="MIDV-123",
        title="新标题",
        cover_urls=["https://s/t.jpg"],
        poster_urls=["https://s/p.jpg"],
        trailer_urls=["https://s/trailer.mp4"],
    )

    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.MOVE,
        resource_store=resource_store,
        file_info=parse_file_info(paths.video),
        web_client=client,
        config=HotSettings(),
    )

    assert result.outcome is PlaceOutcome.PLACED
    assert result.dest == paths.video
    assert "新标题" in paths.nfo.read_text(encoding="utf-8")
    for image in stale:
        assert _pixel(image) != before[image]
    assert paths.trailer.read_bytes() == b"video"


@pytest.mark.parametrize("pre_existing", [True, False])
@pytest.mark.asyncio
async def test_fanart_follows_thumb_selection(
    resource_store: ResourceStore, tmp_path: Path, pre_existing: bool
) -> None:
    """thumb 不在 copy_resources 时 fanart 既不重写也不补建."""
    client = cast("WebClient", FakeClient())

    paths = _paths(tmp_path / "out")
    paths.video.parent.mkdir(parents=True)
    paths.video.write_bytes(b"movie")
    if pre_existing:
        Image.new("RGB", (800, 538), "red").save(paths.fanart)
    before = _pixel(paths.fanart) if pre_existing else None

    mf = MediaFile(path=str(paths.video), library_id=1)
    meta = Metadata(number="MIDV-123", cover_urls=["https://s/t.jpg"], poster_urls=["https://s/p.jpg"])

    result = await execute_file_operations(
        media_file=mf,
        metadata=meta,
        paths=paths,
        move_mode=MoveMode.MOVE,
        resource_store=resource_store,
        file_info=parse_file_info(paths.video),
        web_client=client,
        config=HotSettings(),
        copy_resources=[DownloadableResource.poster],
    )

    assert result.outcome is PlaceOutcome.PLACED
    assert not paths.thumb.exists()
    assert paths.poster.exists()
    assert paths.fanart.exists() is pre_existing
    if before is not None:
        assert _pixel(paths.fanart) == before


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 无 POSIX 权限位")
def test_write_into_library_takes_permissions_from_target(tmp_path: Path) -> None:
    source = tmp_path / "src.jpg"
    source.write_bytes(b"image")
    source.chmod(0o600)
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    target = tmp_path / "dst.jpg"

    _write_into_library(source, target)

    assert target.read_bytes() == b"image"
    assert target.stat().st_mode & 0o777 == probe.stat().st_mode & 0o777


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 无 POSIX 权限位")
def test_write_into_library_rewrites_existing_artifact(tmp_path: Path) -> None:
    source = tmp_path / "src.jpg"
    source.write_bytes(b"new")
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    target = tmp_path / "dst.jpg"
    target.write_bytes(b"old")
    target.chmod(0o600)

    _write_into_library(source, target)

    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & 0o777 == probe.stat().st_mode & 0o777


def test_write_into_library_preserves_source_mtime_without_source_permissions(tmp_path: Path) -> None:
    source = tmp_path / "src.jpg"
    source.write_bytes(b"image")
    source_mtime_ns = 1_600_000_000_000_000_000
    os.utime(source, ns=(source_mtime_ns, source_mtime_ns))
    source.chmod(0o600)
    probe = tmp_path / "probe"
    probe.write_bytes(b"")
    target = tmp_path / "dst.jpg"

    _write_into_library(source, target)

    assert target.stat().st_mtime_ns == source_mtime_ns
    assert target.stat().st_mode & 0o777 == probe.stat().st_mode & 0o777


def test_write_into_library_uses_copyfile_not_copy2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "src.jpg"
    source.write_bytes(b"image")
    target = tmp_path / "dst.jpg"

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("copy2 must not transfer source permissions or ACL")

    monkeypatch.setattr("amane.handlers.file.shutil.copy2", forbidden)
    _write_into_library(source, target)

    assert target.read_bytes() == b"image"


@pytest.mark.asyncio
async def test_images_are_placed_through_new_file_write(resource_store: ResourceStore, tmp_path: Path) -> None:
    """图片按新文件写入库路径, 不依赖来源元数据复制."""
    client = cast("WebClient", FakeClient())

    src = tmp_path / "src" / "MIDV-123.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"movie")
    paths = _paths(tmp_path / "out")

    result = await execute_file_operations(
        media_file=MediaFile(path=str(src), library_id=1),
        metadata=Metadata(number="MIDV-123", cover_urls=["https://s/t.jpg"], poster_urls=["https://s/p.jpg"]),
        paths=paths,
        move_mode=MoveMode.COPY,
        resource_store=resource_store,
        file_info=parse_file_info(src),
        web_client=client,
        config=HotSettings(),
    )

    assert result.outcome is PlaceOutcome.PLACED
    assert paths.thumb.exists()
    assert paths.poster.exists()
    assert paths.fanart.read_bytes() == paths.thumb.read_bytes()


def test_write_into_library_failure_keeps_existing_target_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "src.mp4"
    target = tmp_path / "dst.mp4"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    recorded: list[tuple[str, dict[str, object]]] = []

    def reject(*args: object, **kwargs: object) -> None:
        raise OSError(22, "Invalid argument")

    def record(event: str, **fields: object) -> None:
        recorded.append((event, fields))

    monkeypatch.setattr("amane.handlers.file.shutil.copyfile", reject)
    monkeypatch.setattr("amane.handlers.file.logger.error", record)

    with pytest.raises(OSError, match="Invalid argument"):
        _write_into_library(source, target)

    assert target.read_bytes() == b"old"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["dst.mp4", "src.mp4"]
    assert recorded == [
        (
            "library write failed",
            {"source": str(source), "target": str(target), "error": "[Errno 22] Invalid argument"},
        )
    ]
