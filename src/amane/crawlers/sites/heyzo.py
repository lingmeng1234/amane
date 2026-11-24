"""Heyzo official movie-page crawler."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from parsel import Selector

from ...enums import SiteName
from ..base import Crawler, CrawlerProfile
from ..http import RequestError
from ..models import FetchOptions, MediaMetadata, SearchQuery, film_actors
from ...utils.dates import normalize_calendar_date
from ...utils.text import normalize_long_text

_BASE_URL = "https://www.heyzo.com"
_NUMBER_RE = re.compile(r"^HEYZO-(?P<digits>\\d{4})$", re.IGNORECASE)
_DETAIL_RE = re.compile(r"/movie/(?P<movie_id>\\d+)/?(?:[?#].*)?$", re.IGNORECASE)


def _number(value: str) -> str | None:
    match = _NUMBER_RE.fullmatch(value.strip())
    return f"HEYZO-{match.group('digits')}" if match else None


def _field_item(html: Selector, label: str) -> Selector | None:
    """从作品信息列表中按字段标签定位对应项目, 不依赖页面字段顺序."""
    for item in html.css(".Movie_item__5i6St"):
        if item.xpath("normalize-space(./span[1])").get() == label:
            return item
    return None


def _detail(html_text: str, page_url: str) -> tuple[dict[str, object], list[str], str | None]:
    html = Selector(text=html_text)

    title = html.xpath(
        'normalize-space((//*[contains(concat(" ",normalize-space(@class)," ")," Movie_movieInfo__P1QoM ")]//h1)[1])'
    ).get()

    # 简介只读取 Movie_memo 元素本身. 多个简介段落分别归一后仍保留段落间距;
    # 后面的 Movie_disclaimer 是独立元素, 不会被拼入剧情.
    memo_fragments = html.css(".Movie_memo__Oq_R5").getall()
    plot = normalize_long_text("\\n".join(memo_fragments)) if memo_fragments else None

    actor_item = _field_item(html, "出演")
    actors: list[str] = []
    if actor_item is not None:
        for anchor in actor_item.xpath(".//a"):
            raw_name = anchor.xpath("string(.)").get() or ""
            name = re.sub(r"\\s+", " ", raw_name).strip()
            if name:
                actors.append(name)

    tag_item = _field_item(html, "タグ")
    tags: list[str] = []
    if tag_item is not None:
        for anchor in tag_item.css(".Movie_tags__5D_UT a"):
            raw_tag = anchor.xpath("string(.)").get() or ""
            tag = re.sub(r"\\s+", " ", raw_tag).strip()
            if tag:
                tags.append(tag)

    release_item = _field_item(html, "配信日")
    release_text = ""
    if release_item is not None:
        release_text = "".join(
            part.strip()
            for part in release_item.xpath("./text() | ./span[2]//text()").getall()
            if part.strip()
        )
    release = normalize_calendar_date(release_text)

    poster = (
        html.xpath('//meta[@property="og:image"]/@content').get()
        or html.xpath('//meta[@name="twitter:image"]/@content').get()
    )
    poster_url = urljoin(page_url, poster) if poster else None

    # 只以详情页图库中的缩略图条目数决定原图数量; 不读取缩略图 URL,
    # 不探测下一张编号, 也不混入播放器时间轴 capture 图片.
    gallery_count = len(html.css(".Movie_galleryContainer__LIKsj img"))
    movie_id = _DETAIL_RE.search(page_url)
    gallery: list[str] = []
    if movie_id:
        digits = str(int(movie_id.group("movie_id")))
        gallery = [
            urljoin(_BASE_URL, f"/contents/3000/{digits}/gallery/{index:03d}.jpg")
            for index in range(1, gallery_count + 1)
        ]

    metadata: dict[str, object] = {
        "title": title.strip() if title else None,
        "plot": plot,
        "actors": list(dict.fromkeys(actors)),
        "release": release,
        "tags": list(dict.fromkeys(tags)),
    }
    return metadata, gallery, poster_url


class HeyzoCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(name=SiteName.HEYZO, base_url=_BASE_URL)

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        del options
        number = _number(query.number)
        if number is None:
            return None
        movie_id = int(number.removeprefix("HEYZO-"))
        return f"{self.base_url.rstrip('/')}/movie/{movie_id}"

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        del options
        match = _DETAIL_RE.search(url)
        if match is None:
            return None
        movie_id = str(int(match.group("movie_id")))
        number = f"HEYZO-{int(movie_id):04d}"

        try:
            html_text = await self.client.get_html(url)
        except RequestError as exc:
            self.logger.warning("Heyzo 详情页访问失败", number=number, url=url, error=str(exc))
            return None

        data, gallery, poster = _detail(html_text, url)
        title = data.get("title")
        if not isinstance(title, str) or not title:
            self.logger.warning("Heyzo 详情页缺少标题", number=number, url=url)
            return None

        actors = data.get("actors")
        tags = data.get("tags")
        plot = data.get("plot")
        release = data.get("release")
        return MediaMetadata(
            number=number,
            title=title,
            plot=plot if isinstance(plot, str) else None,
            actors=film_actors(actors if isinstance(actors, list) else []),
            release=release if isinstance(release, str) else None,
            studio="HEYZO",
            publisher="HEYZO",
            tags=tags if isinstance(tags, list) else [],
            # 无码流媒体通用图片流程会把 cover_urls 同步为海报及原始海报;
            # Tokyo-Hot 的专属封面模式不在本来源内实现.
            cover_urls=[poster] if poster else [],
            extrafanart=gallery,
            source_url=url,
            external_id=movie_id,
        )
