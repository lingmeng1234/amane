from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from amane.api.spa import _is_safe_dist_path, mount_spa

_INDEX_HTML = "<!doctype html><div id=root></div>"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", True),
        ("/index.html", True),
        ("/assets/app-abc123.js", True),
        ("/meta/42", True),
        ("/条目/详情", True),
        ("/a//b", True),
        ("", False),
        ("index.html", False),
        ("/../secret", False),
        ("/meta/../secret", False),
        ("/foo..bar", False),
        ("/C:/Windows/win.ini", False),
        ("/c:Windows/win.ini", False),
        (r"\\attacker\share\x", False),
        (r"/\\attacker\share\x", False),
        ("/index\x00.html", False),
    ],
)
def test_is_safe_dist_path(path: str, expected: bool):
    assert _is_safe_dist_path(path) is expected


@pytest.mark.asyncio(loop_scope="function")
async def test_spa_fallback_rejects_unsafe_paths_before_disk_access(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")

    app = FastAPI()
    mount_spa(app, dist)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for raw_path in (
            "/%2e%2e/secret",
            "/C:/Windows/win.ini",
            "/%5C%5Cattacker%5Cshare%5Cx",
            "/index%00.html",
        ):
            response = await client.get(raw_path)
            assert response.status_code == 400, raw_path

        fallback = await client.get("/meta/42")
        assert fallback.status_code == 200
        assert fallback.text == _INDEX_HTML
        head = await client.head("/meta/42")
        assert head.status_code == 200
        assert head.content == b""
        asset = await client.get("/assets/app-abc123.js")
        assert asset.status_code == 200
        assert asset.text == "console.log(1)"
