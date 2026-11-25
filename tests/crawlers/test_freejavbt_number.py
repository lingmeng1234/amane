from typing import TYPE_CHECKING, cast

import pytest

from amane.crawlers.http import HttpClient
from amane.crawlers.sites.freejavbt import FreejavbtCrawler

if TYPE_CHECKING:
    from amane.net.http import WebClient


class _Web:
    async def get_text(self, url: str, **kwargs: object) -> str:
        return (
            '<div class="category-page video-list-item">'
            '<a href="/0712250-01">near match</a>'
            "</div>"
        )


@pytest.mark.asyncio
async def test_search_number_rejects_near_number_with_different_dash_layout() -> None:
    client = HttpClient(web=cast("WebClient", _Web()))
    crawler = FreejavbtCrawler(client=client)

    assert await crawler._search_number("071225-001", "071225-001") is None
