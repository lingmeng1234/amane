import pytest
from fastapi import HTTPException

from amane.api.support.metadata_filters import parse_metadata_filters


@pytest.mark.asyncio
async def test_metadata_filter_total_id_limit_is_200():
    filters = await parse_metadata_filters(actor_id=list(range(100)), tag_id=list(range(100)))
    assert len(filters.actor_id or []) == 100
    assert len(filters.tag_id or []) == 100
    with pytest.raises(HTTPException) as exc:
        await parse_metadata_filters(actor_id=list(range(100)), tag_id=list(range(100)), library_id=[1])
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_metadata_filter_single_dimension_limit_is_100(client):
    response = await client.get("metadata", params=[("actor_id", str(value)) for value in range(101)])
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_metadata_filter_total_limit_is_200_at_api(client):
    params = [("actor_id", str(value)) for value in range(100)]
    params += [("director_id", str(value)) for value in range(100)]
    params.append(("tag_id", "1"))
    response = await client.get("metadata", params=params)
    assert response.status_code == 422
