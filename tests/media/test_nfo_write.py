"""测试 NFO 附属文件生成"""

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest

from amane.config.manager import NfoOutputConfig
from amane.db.models import Metadata
from amane.media import write_nfo
from amane.parsing import ContentType, FilePhase, Mosaic, parse_file_info, summarize_file_phases

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def metadata() -> Metadata:
    return Metadata(
        number="MIDV-123",
        title="Test Title",
        original_title="Original Test Title",
        original_plot="Original plot",
        actors=["Actor A", "Actor B"],
        studio="Studio X",
        release="2026-01-15",
        runtime=120,
        tags=["Drama", "Romance"],
        series="Series Y",
        scores={"javdb": 85.0},
        directors=["Director Z"],
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_has_required_fields(tmp_path: Path, metadata: Metadata):
    nfo_path = tmp_path / "MIDV-123.nfo"
    ok = await write_nfo(metadata, nfo_path)
    assert ok is True
    assert nfo_path.exists()
    content = nfo_path.read_text(encoding="utf-8")
    assert "<title>Test Title</title>" in content
    assert "<originaltitle>MIDV-123 Original Test Title</originaltitle>" in content
    assert "<sorttitle>MIDV-123 Original Test Title</sorttitle>" in content
    assert "<originalplot>Original plot</originalplot>" in content
    assert "<tagline>发行日期 2026-01-15</tagline>" in content
    assert "<premiered>2026-01-15</premiered>" in content
    assert "<releasedate>2026-01-15</releasedate>" in content
    assert "<release>2026-01-15</release>" in content
    assert "<num>MIDV-123</num>" in content
    assert "<actor>" in content
    assert "<name>Actor A</name>" in content
    assert "<studio>Studio X</studio>" in content
    assert "<genre>Drama</genre>" in content
    assert "<director>Director Z</director>" in content
    assert "<outline>" not in content
    assert "<javbusid>" not in content
    assert "<dmmid>" not in content
    assert content.index("<genre>Drama</genre>") < content.index("<tag>Drama</tag>")
    assert content.index("<genre>Romance</genre>") < content.index("<tag>Drama</tag>")
    assert "<rating>85.0</rating>" in content
    # 系列使用规范嵌套: <set><name>…</name></set>
    assert "<series>Series Y</series>" in content
    assert "<set>" in content
    assert "<name>Series Y</name>" in content


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_plot_is_plain_text(tmp_path: Path):
    """长文本按纯文本写出: 无 CDATA, HTML 转义, 非法字符剥离, 换行原样保留."""
    plot = "结尾 ]]> 之后 & <标签>\n\n第二段\x0b"
    nfo_path = tmp_path / "PLOT-1.nfo"

    assert await write_nfo(Metadata(number="PLOT-1", title="T", plot=plot), nfo_path) is True

    content = nfo_path.read_text(encoding="utf-8")
    assert "<![CDATA[" not in content
    assert "]]>" not in content
    assert "\x0b" not in content

    root = ET.fromstring(content)
    assert root.findtext("plot") == "结尾 ]]> 之后 & <标签>\n\n第二段"
    assert root.find("outline") is None


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_uses_original_poster_and_keeps_cover(tmp_path: Path):
    """NFO poster 使用刮削原始地址; cover 继续使用封面地址, 不输出内部裁剪海报 URL."""
    metadata = Metadata(
        number="POSTER-1",
        original_poster_urls=[
            "https://source.example/original-poster.jpg",
            "https://backup.example/original-poster.jpg",
        ],
        poster_urls=["/api/resources/internal-cropped-poster"],
        cover_urls=["/api/resources/manual-cover"],
        original_cover_urls=["https://source.example/cover.jpg"],
    )
    nfo_path = tmp_path / "POSTER-1.nfo"

    assert await write_nfo(metadata, nfo_path) is True

    root = ET.parse(nfo_path).getroot()
    assert root.findtext("poster") == "https://source.example/original-poster.jpg"
    assert root.findtext("cover") == "https://source.example/cover.jpg"
    assert "/api/resources/internal-cropped-poster" not in nfo_path.read_text(encoding="utf-8")
    assert "/api/resources/manual-cover" not in nfo_path.read_text(encoding="utf-8")


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_exports_western_theporndb_source_url_at_the_end(tmp_path: Path):
    metadata = Metadata(
        number="WESTERN-001",
        content_type=ContentType.WESTERN,
        theporndb_uuid="96842b9f-0405-481b-a44a-1c7fb5b0370c",
        original_poster_urls=["https://source.example/poster.jpg"],
        cover_urls=["https://source.example/cover.jpg"],
        original_cover_urls=["https://source.example/cover.jpg"],
        trailer_urls=["https://source.example/trailer.mp4"],
        external_ids={"other_source": "external-123", "theporndb": "duplicate-uuid"},
        source_urls={
            "other_source": "https://other.example/video/123",
            "theporndb": "https://theporndb.net/scenes/96842b9f-0405-481b-a44a-1c7fb5b0370c",
        },
    )
    nfo_path = tmp_path / "WESTERN-001.nfo"

    assert await write_nfo(metadata, nfo_path) is True

    content = nfo_path.read_text(encoding="utf-8")
    root = ET.fromstring(content)
    assert root.find("uniqueid") is None
    assert root.findtext("theporndbid") == metadata.source_urls["theporndb"]
    assert root.findtext("theporndbid") != metadata.theporndb_uuid
    assert root.findtext("other_sourceid") == metadata.source_urls["other_source"]
    assert "external-123" not in content
    assert "duplicate-uuid" not in content
    assert content.index("<poster>") < content.index("<cover>")
    assert content.index("<cover>") < content.index("<trailer>")
    assert content.index("<trailer>") < content.index("<other_sourceid>")
    assert content.index("<other_sourceid>") < content.index("<theporndbid>")
    assert content.rstrip().endswith("</movie>")
    assert content.rfind("<theporndbid>") < content.rfind("</movie>")


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_does_not_export_western_uuid_for_non_western(tmp_path: Path):
    metadata = Metadata(
        number="JAV-001",
        content_type=ContentType.CENSORED,
        theporndb_uuid="must-not-export",
    )
    nfo_path = tmp_path / "JAV-001.nfo"

    assert await write_nfo(metadata, nfo_path) is True

    root = ET.parse(nfo_path).getroot()
    assert root.find("uniqueid") is None


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_preserves_multiple_series(tmp_path: Path):
    metadata = Metadata(number="SERIES-2", series="Series A", series_names=["Series A", "Series B"])
    nfo_path = tmp_path / "SERIES-2.nfo"

    assert await write_nfo(metadata, nfo_path) is True
    root = ET.parse(nfo_path).getroot()
    assert root.findtext("series") == "Series A"
    # Kodi Movie NFO 的 set 仅支持一个; 导出首项, Amane 数据库保留完整列表.
    assert [node.findtext("name") for node in root.findall("set")] == ["Series A"]


def test_title_with_number_deduplicates_only_at_token_boundary() -> None:
    from amane.media.nfo import _title_with_number

    assert _title_with_number("ABC-123", "ABC-123 作品标题") == "ABC-123 作品标题"
    assert _title_with_number("ABC-123", "ABC-123-作品标题") == "ABC-123 作品标题"
    assert _title_with_number("ABF-06", "ABF-062作品标题") == "ABF-06 ABF-062作品标题"


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_omits_cover_when_original_url_missing(tmp_path: Path):
    metadata = Metadata(
        number="POSTER-2",
        cover_urls=["/api/resources/manual-cover"],
        original_cover_urls=[],
    )
    nfo_path = tmp_path / "POSTER-2.nfo"
    assert await write_nfo(metadata, nfo_path) is True
    root = ET.parse(nfo_path).getroot()
    assert root.find("cover") is None


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_respects_global_tag_mapping_switch(tmp_path: Path):
    """NFO 按写入时的全局开关决定使用映射标签还是原文。"""
    mapping_path = tmp_path / "tag_mappings.json"
    mapping_path.write_text(
        '{"version":1,"enabled":true,"entries":{"中出し":{"translation":"内射"}}}',
        encoding="utf-8",
    )
    metadata = Metadata(number="TAG-SWITCH", tags=["中出し", "制服"])
    nfo_path = tmp_path / "TAG-SWITCH.nfo"

    assert await write_nfo(metadata, nfo_path, tag_mapping_path=mapping_path) is True
    root = ET.parse(nfo_path).getroot()
    assert [node.text for node in root.findall("genre")] == ["内射", "制服"]
    assert [node.text for node in root.findall("tag")] == ["内射", "制服"]

    mapping_path.write_text(
        '{"version":1,"enabled":false,"entries":{"中出し":{"translation":"内射"}}}',
        encoding="utf-8",
    )
    assert await write_nfo(metadata, nfo_path, tag_mapping_path=mapping_path) is True
    root = ET.parse(nfo_path).getroot()
    assert [node.text for node in root.findall("genre")] == ["中出し", "制服"]
    assert [node.text for node in root.findall("tag")] == ["中出し", "制服"]


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_uses_original_tags_when_global_mapping_is_disabled(tmp_path: Path):
    """关闭全局映射后，NFO 的 genre/tag 必须全部保留原文。"""
    mapping_path = tmp_path / "tag_mappings.json"
    mapping_path.write_text(
        '{"version":1,"enabled":false,"entries":{"中出し":{"translation":"内射"}}}',
        encoding="utf-8",
    )
    metadata = Metadata(number="TAG-SWITCH-OFF", tags=["中出し", "制服"])
    nfo_path = tmp_path / "TAG-SWITCH-OFF.nfo"

    assert await write_nfo(metadata, nfo_path, tag_mapping_path=mapping_path) is True
    root = ET.parse(nfo_path).getroot()
    assert [node.text for node in root.findall("genre")] == ["中出し", "制服"]
    assert [node.text for node in root.findall("tag")] == ["中出し", "制服"]


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_category_sources_are_independent_and_ordered(tmp_path: Path):
    metadata = Metadata(
        number="MIDV-123",
        title="Title",
        tags=["Drama", "Drama", "Romance"],
        studio="Studio X",
        publisher="Publisher Y",
    )
    config = NfoOutputConfig.model_validate(
        {
            "categories": {
                "genre": {
                    "cover_attributes": True,
                    "tags": True,
                    "studio": True,
                    "publisher": True,
                },
                "tag": {
                    "cover_attributes": False,
                    "tags": True,
                    "studio": False,
                    "publisher": True,
                },
            }
        }
    )
    info = parse_file_info("/media/里番/MIDV-123-U-4K-C.mp4")
    nfo_path = tmp_path / "MIDV-123.nfo"

    assert await write_nfo(metadata, nfo_path, nfo_output=config, file_info=info) is True

    root = ET.parse(nfo_path).getroot()
    assert [item.text for item in root.findall("genre")] == [
        "无码",
        "破解",
        "里番",
        "4K",
        "中文字幕",
        "Drama",
        "Romance",
        "制作商:Studio X",
        "发行商:Publisher Y",
    ]
    assert [item.text for item in root.findall("tag")] == [
        "Drama",
        "Romance",
        "发行商:Publisher Y",
    ]


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_cover_attributes_without_existing_tags(tmp_path: Path):
    metadata = Metadata(number="MIDV-123", title="Title", tags=[])
    config = NfoOutputConfig.model_validate(
        {"categories": {"genre": {"cover_attributes": True, "tags": False}, "tag": {"tags": False}}}
    )
    info = parse_file_info("/media/动漫/MIDV-123.mp4")
    nfo_path = tmp_path / "MIDV-123.nfo"

    assert await write_nfo(metadata, nfo_path, nfo_output=config, file_info=info) is True
    root = ET.parse(nfo_path).getroot()
    assert [item.text for item in root.findall("genre")] == ["有码", "里番"]
    assert root.findall("tag") == []


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_uses_independent_genre_and_tag_sources(tmp_path: Path, metadata: Metadata):
    metadata.publisher = "Publisher Y"
    metadata.tags = ["Drama", "LTX", "Drama"]
    file_info = parse_file_info(
        "/media/动漫/MIDV-123-LTX-4K-C.mp4",
        has_external_subtitle=True,
    )
    output = NfoOutputConfig.model_validate(
        {
            "categories": {
                "genre": {
                    "cover_attributes": True,
                    "tags": True,
                    "studio": True,
                    "publisher": False,
                },
                "tag": {
                    "cover_attributes": False,
                    "tags": False,
                    "studio": False,
                    "publisher": True,
                },
            }
        }
    )
    nfo_path = tmp_path / "MIDV-123.nfo"

    assert await write_nfo(metadata, nfo_path, nfo_output=output, file_info=file_info)

    root = ET.parse(nfo_path).getroot()
    assert [node.text for node in root.findall("genre")] == [
        "无码",
        "LTX",
        "里番",
        "4K",
        "中文字幕",
        "Drama",
        "制作商:Studio X",
    ]
    assert [node.text for node in root.findall("tag")] == ["发行商:Publisher Y"]


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_cover_attributes_do_not_require_existing_tags(tmp_path: Path):
    metadata = Metadata(number="MIDV-123", tags=[])
    file_info = parse_file_info("/media/MIDV-123.mp4")
    output = NfoOutputConfig.model_validate(
        {"categories": {"genre": {"cover_attributes": True, "tags": False}, "tag": {"tags": False}}}
    )
    nfo_path = tmp_path / "MIDV-123.nfo"

    assert await write_nfo(metadata, nfo_path, nfo_output=output, file_info=file_info)

    root = ET.parse(nfo_path).getroot()
    assert [node.text for node in root.findall("genre")] == ["有码"]
    assert root.findall("tag") == []


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_uses_typed_chinese_mappings_for_tags_and_merchants(tmp_path: Path):
    """同一原文在四种归属中可独立映射; Genre/Tag/Series 写入中文值, 独立 studio 字段保留原文."""
    mapping_path = tmp_path / "tag_mappings.json"
    mapping_path.write_text(
        (
            '{"version":2,"enabled":true,"entries":['
            '{"original":"Same","translation":"中文标签","type":"tag"},'
            '{"original":"Same","translation":"中文制作商","type":"maker"},'
            '{"original":"Same","translation":"中文发行商","type":"publisher"},'
            '{"original":"Same","translation":"中文系列","type":"series"}'
            "]}"
        ),
        encoding="utf-8",
    )
    metadata = Metadata(
        number="MAP-NFO-1",
        tags=["Same", "Other"],
        studio="Same",
        publisher="Same",
        series="Same",
        series_names=["Same"],
    )
    output = NfoOutputConfig.model_validate(
        {
            "categories": {
                "genre": {
                    "cover_attributes": False,
                    "tags": True,
                    "studio": True,
                    "publisher": True,
                },
                "tag": {
                    "cover_attributes": False,
                    "tags": True,
                    "studio": True,
                    "publisher": True,
                },
                "series": True,
            }
        }
    )
    nfo_path = tmp_path / "MAP-NFO-1.nfo"

    assert await write_nfo(metadata, nfo_path, tag_mapping_path=mapping_path, nfo_output=output) is True

    root = ET.parse(nfo_path).getroot()
    expected = ["中文标签", "Other", "制作商:中文制作商", "发行商:中文发行商"]
    assert [node.text for node in root.findall("genre")] == expected
    assert [node.text for node in root.findall("tag")] == expected
    assert root.findtext("series") == "中文系列"
    assert [node.findtext("name") for node in root.findall("set")] == ["中文系列"]
    # 独立 NFO 字段沿用原有行为, 不受 Genre/Tag 中文映射开关影响.
    assert root.findtext("studio") == "中文制作商"
    assert root.findtext("maker") == "中文制作商"
    assert root.findtext("publisher") == "中文发行商"
    assert root.findtext("label") == "中文发行商"


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_uses_aggregated_resource_phases(tmp_path: Path):
    metadata = Metadata(number="MIXED-PHASES", title="Mixed resources")
    phases: tuple[FilePhase, ...] = (
        {
            "mosaic": None,
            "has_subtitle": False,
            "definition": "1080p",
            "number_content_type": ContentType.CENSORED,
        },
        {
            "mosaic": Mosaic.CRACKED,
            "has_subtitle": False,
            "definition": "4K",
            "number_content_type": ContentType.CENSORED,
        },
        {
            "mosaic": Mosaic.LEAKED,
            "has_subtitle": True,
            "definition": "720p",
            "number_content_type": ContentType.CENSORED,
        },
    )
    summary = summarize_file_phases(phases, ContentType.CENSORED)
    output = NfoOutputConfig.model_validate(
        {
            "categories": {
                "genre": {"cover_attributes": True, "tags": False},
                "tag": {"cover_attributes": False, "tags": False},
            }
        }
    )
    nfo_path = tmp_path / "MIXED-PHASES.nfo"

    assert (
        await write_nfo(
            metadata,
            nfo_path,
            nfo_output=output,
            file_info=parse_file_info("/media/MIXED-PHASES.mp4"),
            file_phase=summary,
        )
        is True
    )

    root = ET.parse(nfo_path).getroot()
    assert [node.text for node in root.findall("genre")] == ["无码", "破解", "流出", "4K", "中文字幕"]
    assert "有码" not in [node.text for node in root.findall("genre")]


@pytest.mark.asyncio(loop_scope="function")
async def test_write_nfo_global_switch_disables_all_mapping_categories(tmp_path: Path):
    mapping_path = tmp_path / "tag_mappings.json"
    mapping_path.write_text(
        (
            '{"version":2,"enabled":false,"entries":['
            '{"original":"Same","translation":"中文标签","type":"tag"},'
            '{"original":"Same","translation":"中文制作商","type":"maker"},'
            '{"original":"Same","translation":"中文发行商","type":"publisher"},'
            '{"original":"Same","translation":"中文系列","type":"series"}'
            "]}"
        ),
        encoding="utf-8",
    )
    metadata = Metadata(
        number="MAP-OFF-1",
        tags=["Same"],
        studio="Same",
        publisher="Same",
        series="Same",
        series_names=["Same"],
    )
    output = NfoOutputConfig.model_validate(
        {
            "categories": {
                "genre": {"tags": True, "studio": True, "publisher": True},
                "tag": {"tags": True, "studio": True, "publisher": True},
                "series": True,
            }
        }
    )
    nfo_path = tmp_path / "MAP-OFF-1.nfo"

    assert await write_nfo(metadata, nfo_path, tag_mapping_path=mapping_path, nfo_output=output) is True

    root = ET.parse(nfo_path).getroot()
    expected = ["Same", "制作商:Same", "发行商:Same"]
    assert [node.text for node in root.findall("genre")] == expected
    assert [node.text for node in root.findall("tag")] == expected
    assert root.findtext("series") == "Same"
