from collections.abc import Callable
from typing import cast

import pytest
from starlette.datastructures import Headers

from amane.api.middleware import browser_source_allowed
from amane.config.manager import ColdSettings


@pytest.mark.parametrize(
    ("fetch_site", "expected"),
    [("same-origin", True), ("none", True), ("cross-site", False), ("SAME-ORIGIN", True)],
)
def test_fetch_metadata_is_authoritative(fetch_site: str, expected: bool):
    headers = Headers({"sec-fetch-site": fetch_site, "origin": "https://trusted.example"})
    assert browser_source_allowed(headers, ["https://trusted.example"]) is expected


def test_origin_fallback_checks_host_and_configured_origins():
    assert browser_source_allowed(Headers({"origin": "http://amane.local:8000", "host": "amane.local:8000"}), [])
    assert browser_source_allowed(
        Headers({"origin": "https://frontend.example", "host": "amane.local:8000"}),
        ["https://frontend.example"],
    )
    assert not browser_source_allowed(
        Headers({"origin": "https://attacker.example", "host": "amane.local:8000"}),
        ["https://frontend.example"],
    )


def test_non_browser_client_without_origin_is_allowed():
    assert browser_source_allowed(Headers({"host": "amane.local:8000"}), [])


def test_origin_settings_parse_comma_separated_and_reject_paths():
    # pydantic-settings 支持 _env_file 运行时参数, 但其静态构造签名未声明该参数.
    settings_factory = cast(Callable[..., ColdSettings], ColdSettings)
    settings = settings_factory(_env_file=None, trusted_origins="https://a.example, http://b.example:5173")
    assert settings.trusted_origins == ["https://a.example", "http://b.example:5173"]
    with pytest.raises(ValueError):
        settings_factory(_env_file=None, cors_origins="https://a.example/path")


def test_same_site_cross_origin_requires_explicit_trust():
    headers = Headers({"sec-fetch-site": "same-site", "origin": "http://frontend.local:5173", "host": "localhost:8000"})
    assert browser_source_allowed(headers, ["http://frontend.local:5173"])
    assert not browser_source_allowed(headers, ["http://other.local:5173"])
    assert not browser_source_allowed(headers, [])
