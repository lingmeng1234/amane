from amane.aggregate.actor import AggregatedActor, merge_actor_metadata
from amane.crawlers.actor.models import ActorMetadata
from amane.db.actor_person import filter_locked_person_data
from amane.enums import ActorField, SiteName


def test_actor_blood_type_aggregates_with_source() -> None:
    result = merge_actor_metadata(
        {SiteName.MINNANO: ActorMetadata(name="Alice", blood_type="A型")},
        profile_sites=[SiteName.MINNANO],
        image_sites=[],
    )

    assert result.blood_type == "A型"
    assert result.field_sources["blood_type"] == SiteName.MINNANO


def test_actor_blood_type_respects_manual_field_lock() -> None:
    fetched = AggregatedActor(blood_type="A型", field_sources={"blood_type": "minnano"})
    current = AggregatedActor(blood_type="B型", field_sources={"blood_type": "manual"})

    result = filter_locked_person_data(
        fetched,
        locked={ActorField.BLOOD_TYPE},
        current=current,
    )

    assert result.blood_type == "B型"
    assert result.field_sources["blood_type"] == "manual"
