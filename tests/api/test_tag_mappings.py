"""标签中文映射全局开关 API 测试。"""

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx2 import AsyncClient

    from amane.db.repository import Repository


class TestTagMappingStateHttp:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_state_defaults_to_enabled_and_can_be_toggled(self, client: AsyncClient):
        initial = await client.get("tag-mappings/state")
        assert initial.status_code == 200
        assert initial.json() == {"enabled": True}

        disabled = await client.put("tag-mappings/state", json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json() == {"enabled": False}

        current = await client.get("tag-mappings/state")
        assert current.status_code == 200
        assert current.json() == {"enabled": False}

        enabled = await client.put("tag-mappings/state", json={"enabled": True})
        assert enabled.status_code == 200
        assert enabled.json() == {"enabled": True}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_state_update_is_persisted(self, client: AsyncClient, app: FastAPI):
        response = await client.put("tag-mappings/state", json={"enabled": False})
        assert response.status_code == 200

        mapping_path = app.state.runtime.tag_mappings.path
        saved = json.loads(mapping_path.read_text(encoding="utf-8"))
        assert saved["enabled"] is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_state_rejects_non_boolean_value(self, client: AsyncClient):
        response = await client.put("tag-mappings/state", json={"enabled": "off"})
        assert response.status_code == 422


class TestMappedTagFacetSearch:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_search_group_count_and_filter_use_all_original_tags(
        self, client: AsyncClient, app: FastAPI, repo: Repository
    ) -> None:
        both = await repo.upsert_metadata(number="MAP-001", tags=["AAA", "BBB"])
        await repo.upsert_metadata(number="MAP-002", tags=["AAA"])
        await repo.upsert_metadata(number="MAP-003", tags=["BBB"])
        assert both.id is not None

        mappings = app.state.runtime.tag_mappings
        mappings.upsert("AAA", "CCC")
        mappings.upsert("BBB", "CCC")

        facets = await client.get("facets/tag?search=CCC")
        assert facets.status_code == 200
        body = facets.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "CCC"
        assert body["items"][0]["count"] == 3

        representative_id = body["items"][0]["id"]
        filtered = await client.get(f"metadata?tag_id={representative_id}")
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 3
        assert {item["number"] for item in filtered.json()["items"]} == {"MAP-001", "MAP-002", "MAP-003"}


@pytest.mark.asyncio(loop_scope="function")
async def test_typed_mapping_api_uses_one_export_with_distinct_ownership(
    client: AsyncClient, app: FastAPI, repo: Repository
) -> None:
    await repo.upsert_metadata(
        number="MAP-TYPE-001",
        tags=["Same"],
        studio="Same",
        publisher="Same",
        series_names=["Same"],
    )
    store = app.state.runtime.tag_mappings
    store.upsert("Same", "中文标签", "tag")
    store.upsert("Same", "中文制作商", "maker")
    store.upsert("Same", "中文发行商", "publisher")
    store.upsert("Same", "中文系列", "series")

    for kind, translation in (
        ("tag", "中文标签"),
        ("maker", "中文制作商"),
        ("publisher", "中文发行商"),
        ("series", "中文系列"),
    ):
        response = await client.get(f"tag-mappings?type={kind}&status=mapped")
        assert response.status_code == 200
        item = next(item for item in response.json()["items"] if item["original"] == "Same")
        assert item["type"] == kind
        assert item["translation"] == translation

    exported = await client.get("tag-mappings/export")
    assert exported.status_code == 200
    entries = exported.json()["entries"]
    assert {
        (item["original"], item["type"], item["translation"])
        for item in entries
    } == {
        ("Same", "tag", "中文标签"),
        ("Same", "maker", "中文制作商"),
        ("Same", "publisher", "中文发行商"),
        ("Same", "series", "中文系列"),
    }

    imported = await client.post(
        "tag-mappings/import",
        json={
            "version": 2,
            "entries": [
                {"original": "Other", "translation": "其他制作商", "type": "maker"},
                {"original": "Other", "translation": "其他系列", "type": "series"},
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json() == {"imported": 2}

    invalid = await client.post(
        "tag-mappings/import",
        json={"version": 2, "entries": [{"original": "Bad", "translation": "错误", "type": "unknown"}]},
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio(loop_scope="function")
async def test_merchant_mappings_apply_to_facet_display_metadata_and_filters(
    client: AsyncClient, app: FastAPI, repo: Repository
) -> None:
    first = await repo.upsert_metadata(
        number="MERCHANT-MAP-001",
        studio="Studio A",
        publisher="Publisher A",
        series_names=["Series A"],
    )
    second = await repo.upsert_metadata(
        number="MERCHANT-MAP-002",
        studio="Studio B",
        publisher="Publisher B",
        series_names=["Series B"],
    )
    assert first.id is not None and second.id is not None

    store = app.state.runtime.tag_mappings
    store.upsert("Studio A", "中文制作商", "maker")
    store.upsert("Studio B", "中文制作商", "maker")
    store.upsert("Publisher A", "中文发行商", "publisher")
    store.upsert("Publisher B", "中文发行商", "publisher")
    store.upsert("Series A", "中文系列", "series")
    store.upsert("Series B", "中文系列", "series")

    for kind, display in (
        ("studio", "中文制作商"),
        ("publisher", "中文发行商"),
        ("series", "中文系列"),
    ):
        facets = await client.get(f"facets/{kind}?search={display}")
        assert facets.status_code == 200
        assert facets.json()["total"] == 1
        assert facets.json()["items"][0]["name"] == display
        assert facets.json()["items"][0]["count"] == 2
        representative_id = facets.json()["items"][0]["id"]
        filtered = await client.get(f"metadata?{kind}_id={representative_id}")
        assert filtered.status_code == 200
        assert {item["number"] for item in filtered.json()["items"]} == {
            "MERCHANT-MAP-001",
            "MERCHANT-MAP-002",
        }

    detail = await client.get(f"metadata/{first.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["metadata"]["studio"] == "中文制作商"
    assert body["metadata"]["publisher"] == "中文发行商"
    assert body["metadata"]["series"] == "中文系列"
    assert body["metadata"]["series_names"] == ["中文系列"]
    assert body["studio_id"] is not None
    assert body["publisher_id"] is not None
    assert body["series_id"] is not None
    assert body["series_ids"] == {"中文系列": body["series_id"]}
