"""同目录字幕发现: 必须精确匹配 Metadata 主番号, 不按 CD 或无番号回退."""

from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest

from amane.organize import MoveMode
from amane.db.models import Metadata
from amane.library import DEFAULT_SUBTITLE_EXTENSIONS
from amane.organize import discover_subtitles, place_subtitles
from amane.parsing import parse_file_info


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


class _Case(NamedTuple):
    id: str
    files: tuple[str, ...]
    video: str
    extensions: tuple[str, ...]
    expected: tuple[str, ...]


_NUMBER_CD_FILES = (
    "ABC-123-CD1.mp4",
    "ABC-123-CD2.mp4",
    "DEF-456-CD1.mp4",
    "DEF-456-CD2.mp4",
    "ABC-123-CD1.chs.srt",
    "ABC-123-CD1.en.srt",
    "ABC-123-CD2.chs.srt",
    "ABC-123-CD2.en.srt",
    "DEF-456-CD1.srt",
    "DEF-456-CD2.ass",
)

CASES = (
    _Case(
        "numbered-subtitle-only",
        ("MIDV-123.mp4", "MIDV-123.zh.ass", "chs.srt"),
        "MIDV-123.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        ("MIDV-123.zh.ass",),
    ),
    _Case("empty-extensions", ("MIDV-123.mp4", "MIDV-123.srt"), "MIDV-123.mp4", (), ()),
    _Case("extension-filter", ("MIDV-123.mp4", "MIDV-123.srt", "MIDV-123.ass"), "MIDV-123.mp4", (".srt",), ("MIDV-123.srt",)),
    _Case("extension-case-insensitive", ("MIDV-123.mp4", "MIDV-123.SRT"), "MIDV-123.mp4", (".srt",), ("MIDV-123.SRT",)),
    _Case("does-not-recurse", ("MIDV-123.mp4", "subs/MIDV-123.srt"), "MIDV-123.mp4", DEFAULT_SUBTITLE_EXTENSIONS, ()),
    _Case(
        "unparsed-subtitles-never-fallback",
        ("MIDV-123-CD1.mp4", "MIDV-123-CD2.mp4", "a-CD1.srt", "b-CD2.ass", "chs.srt"),
        "MIDV-123-CD1.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        (),
    ),
    _Case(
        "different-cd-same-number-is-allowed",
        ("MIDV-123-CD1.mp4", "MIDV-123-CD2.srt"),
        "MIDV-123-CD1.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        ("MIDV-123-CD2.srt",),
    ),
    _Case(
        "same-number-different-cd-all-match",
        _NUMBER_CD_FILES,
        "ABC-123-CD1.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        ("ABC-123-CD1.chs.srt", "ABC-123-CD1.en.srt", "ABC-123-CD2.chs.srt", "ABC-123-CD2.en.srt"),
    ),
    _Case(
        "same-number-cd2-all-match",
        _NUMBER_CD_FILES,
        "ABC-123-CD2.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        ("ABC-123-CD1.chs.srt", "ABC-123-CD1.en.srt", "ABC-123-CD2.chs.srt", "ABC-123-CD2.en.srt"),
    ),
    _Case(
        "other-number-rejected",
        ("MIDV-123.mp4", "SSIS-001.srt", "MIDV-123.srt"),
        "MIDV-123.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        ("MIDV-123.srt",),
    ),
    _Case(
        "shorter-number-rejected",
        ("MIDV-123.mp4", "MIDV-12.ass"),
        "MIDV-123.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        (),
    ),
    _Case(
        "number-match-is-case-insensitive",
        ("MIDV-123.mp4", "midv-123.srt"),
        "MIDV-123.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        ("midv-123.srt",),
    ),
    _Case(
        "space-normalized-number-matches",
        ("MIDV-123.mp4", "MIDV 123.ass"),
        "MIDV-123.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        ("MIDV 123.ass",),
    ),
    _Case(
        "digits-only-name-is-unparsed",
        ("MIDV-123.mp4", "012.ass"),
        "MIDV-123.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        (),
    ),
    _Case(
        "same-number-unmarked-subtitle-is-valid-for-main-number",
        (*_NUMBER_CD_FILES, "ABC-123.srt"),
        "ABC-123-CD1.mp4",
        DEFAULT_SUBTITLE_EXTENSIONS,
        (
            "ABC-123-CD1.chs.srt",
            "ABC-123-CD1.en.srt",
            "ABC-123-CD2.chs.srt",
            "ABC-123-CD2.en.srt",
            "ABC-123.srt",
        ),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_discover_subtitles(case: _Case, tmp_path: Path) -> None:
    folder = tmp_path / "inbox"
    for rel in case.files:
        _touch(folder / rel)
    video = folder / case.video
    info = parse_file_info(video)
    found = discover_subtitles.sync(
        video,
        case.extensions,
        info,
        metadata_number=info.number,
    )
    assert [p.name for p in found] == list(case.expected)


def test_discover_subtitles_requires_matching_metadata(tmp_path: Path) -> None:
    video = _touch(tmp_path / "MIDV-123.mp4")
    _touch(tmp_path / "MIDV-123.srt")
    info = parse_file_info(video)

    assert discover_subtitles.sync(video, DEFAULT_SUBTITLE_EXTENSIONS, info) == []
    assert discover_subtitles.sync(
        video, DEFAULT_SUBTITLE_EXTENSIONS, info, metadata_number="SSIS-456"
    ) == []


def test_unmatched_subtitle_stays_in_place_when_video_was_not_placed(tmp_path: Path) -> None:
    video_source = _touch(tmp_path / "source" / "MIDV-123.mp4")
    subtitle = _touch(tmp_path / "source" / "MIDV-123.srt")
    video_dest = tmp_path / "organized" / "MIDV-123.mp4"

    moved = place_subtitles.sync(
        [subtitle],
        video_source=video_source,
        video_dest=video_dest,
        library=MagicMock(),
        metadata=Metadata(number="MIDV-123"),
        file_info=parse_file_info(video_source),
        mode=MoveMode.MOVE,
    )

    assert moved == []
    assert subtitle.exists()
    assert not video_dest.exists()


def test_subtitle_stays_in_place_when_metadata_number_does_not_match(tmp_path: Path) -> None:
    video_source = _touch(tmp_path / "source" / "MIDV-123.mp4")
    subtitle = _touch(tmp_path / "source" / "MIDV-123.srt")
    video_dest = _touch(tmp_path / "organized" / "MIDV-123.mp4")

    moved = place_subtitles.sync(
        [subtitle],
        video_source=video_source,
        video_dest=video_dest,
        library=MagicMock(),
        metadata=Metadata(number="SSIS-456"),
        file_info=parse_file_info(video_source),
        mode=MoveMode.MOVE,
    )

    assert moved == []
    assert subtitle.exists()

