import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from amane.crawlers.actor.sites.gfriends import GFriendsActorCrawler, GFriendsImage
from amane.net.errors import FailureReason, SourceError


def _tree(filename: str = "Alice.jpg") -> dict:
    return {"Content": {"A": {filename: filename}}}


def _crawler(
    data_dir: Path, *, etag: str | None, tree: dict | None = None
) -> tuple[GFriendsActorCrawler, AsyncMock, AsyncMock]:
    response = SimpleNamespace(headers={"etag": etag} if etag is not None else {})
    request = AsyncMock(return_value=response)
    get_json = AsyncMock(return_value=_tree() if tree is None else tree)
    client = SimpleNamespace(web_client=SimpleNamespace(request=request), get_json=get_json)
    return GFriendsActorCrawler(client, data_dir=data_dir), request, get_json


@pytest.mark.asyncio
async def test_gfriends_downloads_and_writes_index_and_etag_atomically(tmp_path: Path):
    crawler, request, get_json = _crawler(tmp_path, etag='"v2"')

    index = await crawler._ensure_index()

    assert "Alice.jpg" in index
    assert get_json.await_count == 1
    assert request.await_count == 1
    assert (tmp_path / "gfriends.json").exists()
    assert json.loads((tmp_path / "gfriends.etag").read_text(encoding="utf-8")) == {
        "url": crawler._tree_url(),
        "etag": '"v2"',
    }
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_fresh_cache_does_not_make_network_requests(tmp_path: Path):
    crawler, request, get_json = _crawler(tmp_path, etag='"v1"')
    cache = tmp_path / "gfriends.json"
    cache.write_text(json.dumps({"Alice.jpg": {"url": "https://img.example/a.jpg", "path": "Content/A/Alice.jpg"}}))

    index = await crawler._ensure_index()

    assert index["Alice.jpg"].url == "https://img.example/a.jpg"
    assert request.await_count == 0
    assert get_json.await_count == 0


@pytest.mark.asyncio
async def test_stale_cache_with_same_etag_only_touches_cache(tmp_path: Path):
    crawler, request, get_json = _crawler(tmp_path, etag='"v1"')
    cache = tmp_path / "gfriends.json"
    cache.write_text(json.dumps({"Alice.jpg": {"url": "https://img.example/a.jpg", "path": "Content/A/Alice.jpg"}}))
    old = time.time() - 2 * 24 * 3600
    os.utime(cache, (old, old))
    (tmp_path / "gfriends.etag").write_text(json.dumps({"url": crawler._tree_url(), "etag": '"v1"'}))

    index = await crawler._ensure_index()

    assert "Alice.jpg" in index
    assert request.await_count == 1
    assert get_json.await_count == 0
    assert cache.stat().st_mtime > old


@pytest.mark.asyncio
async def test_stale_index_survives_refresh_failure_with_backoff(tmp_path: Path):
    crawler, _request, get_json = _crawler(tmp_path, etag=None)
    crawler._index = {"Alice.jpg": GFriendsImage(url="https://img.example/a.jpg", path="Content/A/Alice.jpg")}
    crawler._index_at = 0
    get_json.side_effect = SourceError(FailureReason.NETWORK, detail="offline")

    first = await crawler._ensure_index()
    second = await crawler._ensure_index()

    assert first == second
    assert "Alice.jpg" in first
    assert get_json.await_count == 1
    assert crawler._retry_at > time.time()


@pytest.mark.asyncio
async def test_empty_refresh_keeps_stale_index(tmp_path: Path):
    crawler, _request, _get_json = _crawler(tmp_path, etag='"v2"', tree={"Content": {}})
    crawler._index = {"Alice.jpg": GFriendsImage(url="https://img.example/a.jpg", path="Content/A/Alice.jpg")}
    crawler._index_at = 0

    index = await crawler._ensure_index()

    assert "Alice.jpg" in index
    assert crawler._retry_at > time.time()
