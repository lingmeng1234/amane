from __future__ import annotations

import pytest

from amane.crawlers import registry
from amane.crawlers.models import SearchQuery
from amane.crawlers.sites.heyzo import HeyzoCrawler, _detail, _number
from amane.enums import SiteName

_HTML = """
<html>
<head>
  <meta property="og:image" content="https://www.heyzo.com/contents/3000/1206/images/player_thumbnail.jpg">
</head>
<body>
  <div class="Movie_movieInfo__P1QoM">
    <h1>作品标题</h1>
    <p class="Movie_memo__Oq_R5">第一段说明<br>第二行</p>
    <p class="Movie_memo__Oq_R5">第二段说明</p>
    <div class="Movie_disclaimer__H6muq">这段网站说明不属于简介</div>
    <div class="Movie_item__5i6St">
      <span>出演</span>
      <span><a href="/actor/1">演员甲</a><a href="/actor/2">演员乙</a></span>
    </div>
    <div class="Movie_item__5i6St"><span>配信日</span>2016年7月6日</div>
    <div class="Movie_item__5i6St">
      <span>タグ</span>
      <div class="Movie_tags__5D_UT"><a>标签甲</a><a>标签乙</a></div>
    </div>
  </div>
  <div class="Movie_galleryContainer__LIKsj">
    <div><button><img src="/thumbnail_001.jpg"></button></div>
    <div><button><img src="/thumbnail_002.jpg"></button></div>
    <div class="Movie_guestBlurredThumbnail__qQHB4">
      <button class="Movie_guestLockedThumbnail__9cpd9"><img src="/thumbnail_003.jpg"></button>
    </div>
  </div>
</body>
</html>
"""


def test_heyzo_registered_and_number_is_strict() -> None:
    assert registry.get(SiteName.HEYZO) is HeyzoCrawler
    assert _number("HEYZO-1206") == "HEYZO-1206"
    assert _number("heyzo-0119") == "HEYZO-0119"
    assert _number("HEYZO-119") is None
    assert _number("HEYZO-12060") is None
    assert _number("1206") is None


@pytest.mark.asyncio(loop_scope="function")
async def test_search_builds_direct_movie_url_and_normalizes_leading_zeroes() -> None:
    crawler = HeyzoCrawler(object())  # type: ignore[arg-type]
    assert await crawler._search(SearchQuery("HEYZO-1206")) == "https://www.heyzo.com/movie/1206"
    assert await crawler._search(SearchQuery("HEYZO-0119")) == "https://www.heyzo.com/movie/119"
    assert await crawler._search(SearchQuery("HEYZO-12060")) is None


def test_detail_keeps_plot_layout_and_separates_each_actor_and_tag() -> None:
    data, gallery, poster = _detail(_HTML, "https://www.heyzo.com/movie/1206")

    assert data["title"] == "作品标题"
    assert data["plot"] == "第一段说明\n第二行\n\n第二段说明"
    assert "这段网站说明不属于简介" not in str(data["plot"])
    assert data["actors"] == ["演员甲", "演员乙"]
    assert data["tags"] == ["标签甲", "标签乙"]
    assert data["release"] == "2016-07-06"
    assert poster == "https://www.heyzo.com/contents/3000/1206/images/player_thumbnail.jpg"
    assert gallery == [
        "https://www.heyzo.com/contents/3000/1206/gallery/001.jpg",
        "https://www.heyzo.com/contents/3000/1206/gallery/002.jpg",
        "https://www.heyzo.com/contents/3000/1206/gallery/003.jpg",
    ]


class _FakeClient:
    async def get_html(self, url: str, **kwargs: object) -> str:
        assert url == "https://www.heyzo.com/movie/1206"
        return _HTML


@pytest.mark.asyncio(loop_scope="function")
async def test_scrape_returns_single_cover_and_heyzo_company_fields() -> None:
    crawler = HeyzoCrawler(_FakeClient())  # type: ignore[arg-type]
    result = await crawler._scrape("https://www.heyzo.com/movie/1206")

    assert result is not None
    assert result.number == "HEYZO-1206"
    assert result.title == "作品标题"
    assert result.studio == "HEYZO"
    assert result.publisher == "HEYZO"
    assert result.cover_urls == ["https://www.heyzo.com/contents/3000/1206/images/player_thumbnail.jpg"]
    assert result.poster_urls == []
    assert result.original_poster_urls is None
    assert len(result.extrafanart) == 3
