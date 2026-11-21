from unittest.mock import AsyncMock

import pytest

from amane.crawlers.http import HttpClient
from amane.crawlers.sites.official import OfficialCrawler, _poster_urls, _values_without_placeholder


@pytest.mark.parametrize(
    ("cover", "expected"),
    [
        ("https://cdn.example/ABP-001-pl.jpg", ["https://cdn.example/ABP-001-ps.jpg"]),
        ("https://cdn.example/hash123.jpg", []),
        (None, []),
    ],
)
def test_poster_url_is_derived_only_for_known_cover_suffixes(cover, expected):
    assert _poster_urls(cover) == expected


def test_director_placeholder_is_removed():
    assert _values_without_placeholder(["監督A", "---", "監督B"]) == ["監督A", "監督B"]


@pytest.mark.asyncio
async def test_scrape_extracts_plot_director_cover_and_extrafanart():
    html = """
    <html><head><title>作品标题 | 【S1 NO.1 STYLE】公式サイト</title></head><body>
      <div class="th">品番</div><div class="td"><p><span>DVD</span> SSIS960</p></div>
      <div class="th">発売日</div><div class="td"><a>2026-01-01</a></div>
      <div class="th">収録時間</div><div class="td"><p>120分</p></div>
      <div class="th">ジャンル</div><div class="td"><a href="/works/list/genre/1">ジャンルA</a></div>
      <div class="th">監督</div><div class="td"><p>監督A</p><p>---</p></div>
      <div class="p-slider">
        <img class="swiper-lazy" data-src="https://cdn.example/SSIS960-pl.jpg">
        <img class="swiper-lazy" data-src="https://cdn.example/SSIS960-01.jpg">
      </div>
      <p class="p-workPage__text">剧情第一段<br>剧情第二段</p>
    </body></html>
    """
    crawler = OfficialCrawler(client=HttpClient(web=AsyncMock()))
    crawler.client.get_html = AsyncMock(return_value=html)

    result = await crawler._scrape("https://s1s1s1.com/works/detail/ssis960")

    assert result is not None
    assert result.plot == "剧情第一段\n剧情第二段"
    assert result.directors == ["監督A"]
    assert result.cover_urls == ["https://cdn.example/SSIS960-pl.jpg"]
    assert result.poster_urls == ["https://cdn.example/SSIS960-ps.jpg"]
    assert result.extrafanart == ["https://cdn.example/SSIS960-01.jpg"]


@pytest.mark.asyncio
async def test_scrape_uses_src_for_single_image_slider():
    html = """
    <html><head><title>作品标题 | 【BeFree】公式サイト</title></head><body>
      <div class="th">品番</div><div class="td"><p>ABP001</p></div>
      <div class="p-slider"><img src="https://cdn.example/ABP001-pl.jpg"></div>
    </body></html>
    """
    crawler = OfficialCrawler(client=HttpClient(web=AsyncMock()))
    crawler.client.get_html = AsyncMock(return_value=html)

    result = await crawler._scrape("https://befreebe.com/works/detail/abp001")

    assert result is not None
    assert result.cover_urls == ["https://cdn.example/ABP001-pl.jpg"]
    assert result.poster_urls == ["https://cdn.example/ABP001-ps.jpg"]
    assert result.extrafanart == []
