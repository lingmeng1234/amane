"""Jav321 字段提取边界."""

import pytest
from parsel import Selector

from amane.crawlers.sites.jav321 import Jav321Crawler, _clean_url, _field_links, _field_text


def test_clean_url_collapses_duplicate_path_slashes_only() -> None:
    assert _clean_url("https://pics.dmm.co.jp//digital/video/a.jpg") == "https://pics.dmm.co.jp/digital/video/a.jpg"


def test_field_text_and_links_stop_at_next_label() -> None:
    html = Selector(
        text="""<div><b>品番</b>: ABC-123<br><b>メーカー</b><a>Studio A</a><br>
        <b>ジャンル</b><a>Drama</a><a>Romance</a><br><b>シリーズ</b><a>Series X</a></div>"""
    )
    assert _field_text(html, "品番") == "ABC-123"
    assert _field_links(html, "ジャンル") == ["Drama", "Romance"]


class _FakeClient:
    async def get_html(self, url: str) -> str:
        return """
        <div class="panel-heading"><h3>Test title</h3></div>
        <div class="panel-body">
          <div><b>品番</b>: ABC-123</div>
          <div class="row">
            <div class="col-md-12"><p>First line<br>Second line</p><p>Second paragraph</p></div>
          </div>
        </div>
        """


@pytest.mark.asyncio
async def test_scrape_preserves_plot_line_breaks_and_paragraphs() -> None:
    crawler = Jav321Crawler(_FakeClient())  # type: ignore[arg-type]

    result = await crawler._scrape("https://www.jav321.com/video/123")

    assert result is not None
    assert result.plot == ("First line\nSecond line\n\nSecond paragraph")
