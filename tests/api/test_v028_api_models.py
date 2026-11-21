import pytest
from pydantic import TypeAdapter, ValidationError

from amane.api.models.actors import ActorUserTagsRequest
from amane.api.models.cleanup import SelectionRequest
from amane.api.models.facets import FacetBatchAction, FacetBatchRequest, FacetMergeRequest
from amane.api.models.feeds import FeedItemBatchAction, FeedItemBatchRequest, FeedUpdateRequest
from amane.api.models.metadata import MetadataBatchIdsRequest, MetadataUserTagsRequest, PartialMetadata
from amane.api.models.tasks import TaskBatchAction, TaskBatchRequest


def test_feed_patch_uses_create_validation_rules():
    assert FeedUpdateRequest.model_validate({"name": "  Feed  "}).name == "Feed"
    assert FeedUpdateRequest.model_validate({"number_pattern": None}).number_pattern is None
    assert FeedUpdateRequest.model_validate({"use_cache": ["trans", "metadata"]}).use_cache == ["metadata", "trans"]
    assert FeedUpdateRequest.model_validate({"ignore_keywords": [" foo ", "", "bar"]}).ignore_keywords == [
        "foo",
        "bar",
    ]

    for payload in (
        {"name": None},
        {"group": None},
        {"interval_seconds": 59},
        {"interval_seconds": 86401},
        {"url": "file:///etc/passwd"},
        {"number_pattern": "["},
        {"use_cache": ["unknown"]},
    ):
        with pytest.raises(ValidationError):
            FeedUpdateRequest.model_validate(payload)


def test_metadata_patch_allows_clearing_nullable_fields_only():
    partial_metadata_adapter = TypeAdapter(PartialMetadata)
    assert partial_metadata_adapter.validate_python({"release": None}).release is None
    assert partial_metadata_adapter.validate_python({"title": None}).title is None
    with pytest.raises(ValidationError):
        partial_metadata_adapter.validate_python({"actors": None})


def test_batch_id_requests_are_bounded():
    ids = list(range(1000))
    MetadataBatchIdsRequest(ids=ids)
    MetadataUserTagsRequest(ids=ids, user_tag_ids=ids, action="attach")
    ActorUserTagsRequest(ids=ids, user_tag_ids=ids, action="attach")
    SelectionRequest(media_file_ids=ids)
    FacetBatchRequest(facet_ids=ids, action=FacetBatchAction.FAVORITE)
    FacetMergeRequest(target_id=1, source_ids=ids)
    FeedItemBatchRequest(action=FeedItemBatchAction.IGNORE, ids=ids)
    TaskBatchRequest(action=TaskBatchAction.CANCEL, task_ids=ids)

    for factory in (
        lambda: MetadataBatchIdsRequest(ids=[*ids, 1000]),
        lambda: MetadataUserTagsRequest(ids=[*ids, 1000], user_tag_ids=[1], action="attach"),
        lambda: ActorUserTagsRequest(ids=[*ids, 1000], user_tag_ids=[1], action="attach"),
        lambda: SelectionRequest(media_file_ids=[*ids, 1000]),
        lambda: FacetBatchRequest(facet_ids=[*ids, 1000], action=FacetBatchAction.FAVORITE),
        lambda: FacetMergeRequest(target_id=1, source_ids=[*ids, 1000]),
        lambda: FeedItemBatchRequest(action=FeedItemBatchAction.IGNORE, ids=[*ids, 1000]),
        lambda: TaskBatchRequest(action=TaskBatchAction.CANCEL, task_ids=[*ids, 1000]),
    ):
        with pytest.raises(ValidationError):
            factory()
