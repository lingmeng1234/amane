from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from httpx2 import AsyncClient

from amane.api.routes.theporndb_scenes import (
    _fetch_scene_pages,
    _official_gender,
    _performer_entries,
    _tag_names,
)
from amane.api.routes.uncollected_scenes import _scene_response
from amane.enums import ActorGender


def test_theporndb_official_gender_is_normalized() -> None:
    assert _official_gender({"extras": {"gender": "Female"}}) == "female"
    assert _official_gender({"extras": {"gender": "TRANSGENDER_FEMALE"}}) == "transgender_female"
    assert _official_gender({"extras": {"gender": "Male"}}) == "male"
    assert _official_gender({"extras": {"gender": "Unknown"}}) == "unknown"
    assert _official_gender({"extras": {"gender": "INTERSEX"}}) == "intersex"
    assert _official_gender({"extras": {"gender": "NON_BINARY"}}) == "non_binary"
    assert _official_gender({"extras": {"gender": "TRANSGENDER_MALE"}}) == "transgender_male"


def test_missing_official_gender_is_distinct_from_explicit_unknown() -> None:
    assert _official_gender({"extras": {}}) is None
    assert _official_gender({"extras": {"gender": ""}}) is None
    assert _official_gender({"extras": {"gender": "Non_Binary"}}) == "non_binary"


def test_scene_performers_accept_rest_and_graphql_shapes() -> None:
    scene = {
        "performers": [
            {"name": "Official Name", "extras": {"gender": "Female"}},
            {"as": "Alias Name", "performer": {"name": "Canonical Name", "extras": {}}},
        ]
    }
    assert _performer_entries(scene) == [
        {"name": "Official Name", "official_gender": "female"},
        {"name": "Canonical Name", "official_gender": None},
    ]


def test_scene_tags_are_names_only() -> None:
    assert _tag_names({"tags": [{"name": "Anal"}, {"name": "Creampie"}, "Amateur"]}) == [
        "Anal",
        "Creampie",
        "Amateur",
    ]


def test_scene_performer_gender_falls_back_to_outer_relationship() -> None:
    scene = {
        "performers": [
            {
                "as": "Display Alias",
                "gender": "Female",
                "performer": {"name": "Canonical Name", "extras": {}},
            },
            {
                "as": "Another Alias",
                "extras": {"gender": "Male"},
                "performer": {"name": "Another Name", "extras": {}},
            },
        ]
    }
    assert _performer_entries(scene) == [
        {"name": "Canonical Name", "official_gender": "female"},
        {"name": "Another Name", "official_gender": "male"},
    ]


@pytest.mark.asyncio
async def test_scene_search_fetches_all_pages() -> None:
    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.payload

    class FakeClient:
        def __init__(self) -> None:
            self.pages: list[int] = []

        async def get(self, _url: str, *, params: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
            page = int(params["page"])
            self.pages.append(page)
            batch = (
                [{"id": f"scene-{index}"} for index in range(50)]
                if page == 1
                else [{"id": "scene-50"}, {"id": "scene-51"}]
            )
            return FakeResponse({"data": batch})

    client = FakeClient()
    scenes = await _fetch_scene_pages(cast(AsyncClient, client), {"orderBy": "recently_released"}, {})
    assert client.pages == [1, 2]
    assert len(scenes) == 52
    assert scenes[-1]["id"] == "scene-51"


@pytest.mark.asyncio
async def test_saved_scene_gender_uses_official_then_local_then_unknown() -> None:
    item = SimpleNamespace(
        id=1,
        theporndb_uuid="scene-uuid",
        title="Scene",
        date="2026-01-01",
        studio="Studio",
        performers=[
            {"name": "Official Female", "official_gender": "female"},
            {"name": "Local Male", "official_gender": None},
            {"name": "No Profile", "official_gender": None},
            {"name": "Official Unknown", "official_gender": "unknown"},
        ],
        image_url=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    response = await _scene_response(
        item,
        {
            "Official Female": ActorGender.MALE,
            "Local Male": ActorGender.MALE,
            "Official Unknown": ActorGender.FEMALE,
        },
    )
    assert [performer.gender for performer in response.performers] == [
        "female",
        "male",
        "unknown",
        "unknown",
    ]
