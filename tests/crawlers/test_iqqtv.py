from parsel import Selector

from amane.crawlers.sites.iqqtv import IqqtvCrawler


def test_extract_plot_preserves_line_breaks_and_paragraphs() -> None:
    html = Selector(text=("<p>简介：第一段第一行<br>第一段第二行<br><br>第二段内容</p>"))

    assert IqqtvCrawler._extract_plot(html) == ("第一段第一行\n第一段第二行\n\n第二段内容")


def test_extract_plot_excludes_invalid_content() -> None:
    invalid_html = Selector(text="<p>简介：克破相关内容</p>")
    assert IqqtvCrawler._extract_plot(invalid_html) == ""

    suffix_html = Selector(text="<p>简介：正文内容*根据分发后续内容</p>")
    assert IqqtvCrawler._extract_plot(suffix_html) == "正文内容"
