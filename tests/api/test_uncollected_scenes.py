from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from amane.api.routes.theporndb_scenes import _official_gender, _performer_entries, _tag_names
from amane.api.routes.uncollected_scenes import _scene_response
from amane.enums import ActorGender


def test_theporndb_official_gender_is_normalized() -> None:
    assert _official_gender({"extras": {"gender": "Female"}}) is ActorGender.FEMALE
    assert _official_gender({"extras": {"gender": "TRANSGENDER_FEMALE"}}) is ActorGender.TRANSGENDER_FEMALE
    assert _official_gender({"extras": {"gender": "Male"}}) is ActorGender.MALE
    assert _official_gender({"extras": {"gender": "Unknown"}}) is ActorGender.UNKNOWN


def test_missing_official_gender_is_distinct_from_explicit_unknown() -> None:
    assert _official_gender({"extras": {}}) is None
    assert _official_gender({"extras": {"gender": ""}}) is None
    assert _official_gender({"extras": {"gender": "Non_Binary"}}) is ActorGender.UNKNOWN


def test_scene_performers_accept_rest_and_graphql_shapes() -> None:
    scene = {
        "performers": [
            {"name": "Official Name", "extras": {"gender": "Female"}},
            {"as": "Alias Name", "performer": {"name": "Canonical Name", "extras": {}}},
        ]
    }
    assert _performer_entries(scene) == [
        {"name": "Official Name", "official_gender": ActorGender.FEMALE},
        {"name": "Canonical Name", "official_gender": None},
    ]


def test_scene_tags_are_names_only() -> None:
    assert _tag_names({"tags": [{"name": "Anal"}, {"name": "Creampie"}, "Amateur"]}) == [
        "Anal",
        "Creampie",
        "Amateur",
    ]


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
        ActorGender.FEMALE,
        ActorGender.MALE,
        ActorGender.UNKNOWN,
        ActorGender.UNKNOWN,
    ]
