"""ThePornDB Scene → Movie → series projection tests."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from amane.config import SiteConfig
from amane.crawlers.http import HttpClient
from amane.crawlers.models import SearchQuery
from amane.crawlers.sites.theporndb import ThePornDBCrawler, _extract_movie_title
from amane.net.errors import RequestError


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        ({"movies": [{"title": "Anal Young'uns #04"}]}, "Anal Young'uns #04"),
        ({"movies": []}, None),
        ({"movies": [{"title": "  "}]}, None),
        ({"movies": [{"title": "Movie A"}, {"title": "Movie B"}]}, None),
        ({"movies": [None]}, None),
        ({"movies": "not-a-list"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_extract_movie_title(details: object, expected: str | None) -> None:
    assert _extract_movie_title(details) == expected


def _scene() -> dict[str, Any]:
    return {
        "id": "scene-series-test",
        "code": "SSIS-497",
        "title": "Scene title",
        "date": "2024-01-01",
        "studio": {"name": "S1"},
    }


def _crawler(web: AsyncMock) -> ThePornDBCrawler:
    return ThePornDBCrawler(client=HttpClient(web=web), config=SiteConfig(api_token="test-token"))


@pytest.mark.asyncio
async def test_fetch_uses_only_the_single_related_movie_title_for_series() -> None:
    web = AsyncMock()
    web.post_json.return_value = {"data": {"searchScene": [_scene()]}}
    web.get_json.return_value = {
        "data": {
            "movies": [
                {
                    "title": "Anal Young'uns #04",
                    "actors": [{"name": "must not be imported"}],
                    "details": "must not be imported",
                    "images": [{"url": "https://example.invalid/movie-cover.jpg"}],
                }
            ]
        }
    }

    metadata = await _crawler(web).fetch(SearchQuery(number="SSIS-497"))

    assert metadata is not None
    assert metadata.series == "Anal Young'uns #04"
    assert metadata.title == "Scene title"
    assert metadata.actors == []
    assert metadata.tags == []
    assert metadata.plot is None
    assert metadata.cover_urls == []
    assert web.get_json.await_count == 1
    assert web.get_json.await_args.args[0] == "https://api.theporndb.net/scenes/scene-series-test"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "movies",
    [
        [],
        [{"title": "Movie A"}, {"title": "Movie B"}],
        [{"title": ""}],
    ],
)
async def test_fetch_leaves_series_empty_without_exactly_one_valid_movie(movies: list[dict[str, Any]]) -> None:
    web = AsyncMock()
    web.post_json.return_value = {"data": {"searchScene": [_scene()]}}
    web.get_json.return_value = {"data": {"movies": movies}}

    metadata = await _crawler(web).fetch(SearchQuery(number="SSIS-497"))

    assert metadata is not None
    assert metadata.series is None


@pytest.mark.asyncio
async def test_fetch_keeps_scene_metadata_when_rest_details_request_fails() -> None:
    web = AsyncMock()
    web.post_json.return_value = {"data": {"searchScene": [_scene()]}}
    web.get_json.side_effect = RequestError("https://api.theporndb.net/scenes/scene-series-test")

    metadata = await _crawler(web).fetch(SearchQuery(number="SSIS-497"))

    assert metadata is not None
    assert metadata.title == "Scene title"
    assert metadata.series is None
