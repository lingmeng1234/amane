from unittest.mock import AsyncMock

import pytest

from amane.crawlers.http import HttpClient
from amane.crawlers.sites.giga import GigaCrawler


@pytest.mark.asyncio
async def test_scrape_extracts_tags_directors_and_full_plot():
    html = """
    <html><body>
      <div id="works_pic"><h5>GIGA作品</h5><img src="/cover.jpg"></div>
      <div id="works_txt">
        <dl><dt>作品番号</dt><dd>THPA-17</dd></dl>
        <dl><dt>DVDリリース日</dt><dd>2026-01-01</dd></dl>
        <dl><dt>収録時間</dt><dd>120分</dd></dl>
        <dl><dt>監督</dt><dd><a>导演A</a><a>导演B</a></dd></dl>
      </div>
      <div id="tag"><a href="?tag_id=1">类型A</a><a href="?tag_id=2">类型B</a></div>
      <div id="tag"><a href="?tag_id=3">角色标签</a></div>
      <div id="story_list1">截断剧情……</div>
      <div id="story_list2"><li class="story_window">完整剧情第一段<br>完整剧情第二段<a>更多</a></li></div>
      <div class="gasatsu_images_pc"><img src="/sample1.jpg"></div>
    </body></html>
    """
    crawler = GigaCrawler(client=HttpClient(web=AsyncMock()))
    crawler._get_html = AsyncMock(return_value=html)

    result = await crawler._scrape("https://www.giga-web.jp/product/index.php?product_id=1")

    assert result is not None
    assert result.tags == ["类型A", "类型B"]
    assert result.directors == ["导演A", "导演B"]
    assert result.plot == "完整剧情第一段\n完整剧情第二段"
    assert result.cover_urls == ["https://www.giga-web.jp/cover.jpg"]
    assert result.extrafanart == ["https://www.giga-web.jp/sample1.jpg"]
