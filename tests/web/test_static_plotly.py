# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``/static``: plotly.js comes from the installed plotly package, cached, never from a CDN."""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.offline
import pytest

from sankey_studio.web.routers import pages
from sankey_studio.web.security import CSP

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.web.conftest import AppFactory, WebApp

PATH = "/static/vendor/plotly.min.js"
NOT_FOUND = {"error": {"code": "not_found", "message": "Not Found", "details": []}}


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """``plotly_js`` is cached per process: every test starts (and leaves) it empty."""
    pages.plotly_js.cache_clear()
    yield
    pages.plotly_js.cache_clear()


class FakePlotly:
    """Stands in for ``plotly.offline.get_plotlyjs``: counts calls, returns non-ASCII text."""

    text = "/* plotly fake */ var label = 'café';"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.text


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakePlotly:
    replacement = FakePlotly()
    monkeypatch.setattr(pages, "get_plotlyjs", replacement)
    return replacement


def test_the_route_serves_the_plotly_package_file(web: WebApp) -> None:
    response = web.client.get(PATH)
    expected = plotly.offline.get_plotlyjs().encode()
    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["content-length"] == str(len(expected))
    assert b"plotly.js v" in response.content[:200]
    assert len(response.content) > 1_000_000


def test_the_answer_is_javascript_never_stored_with_the_page_headers(web: WebApp) -> None:
    headers = web.client.get(PATH).headers
    assert headers["content-type"] == "text/javascript; charset=utf-8"
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["content-security-policy"] == CSP
    assert headers["cross-origin-resource-policy"] == "same-origin"


def test_the_bytes_are_utf_8_and_read_once_per_process(web: WebApp, fake: FakePlotly) -> None:
    first = web.client.get(PATH)
    second = web.client.get(PATH)
    assert first.content == second.content == FakePlotly.text.encode("utf-8")
    assert b"caf\xc3\xa9" in first.content
    assert fake.calls == 1
    assert pages.plotly_js() is pages.plotly_js()


def test_the_accessor_returns_bytes_of_the_package_text(fake: FakePlotly) -> None:
    body = pages.plotly_js()
    assert isinstance(body, bytes)
    assert body.decode() == FakePlotly.text
    assert pages.plotly_js.cache_info().currsize == 1
    assert fake.calls == 1


def test_the_route_is_available_in_remote_read_only_mode(make_app: AppFactory) -> None:
    response = make_app(mode="remote_read_only").client.get(PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


def test_the_route_is_get_only(web: WebApp) -> None:
    response = web.client.post(PATH, json={})
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_other_vendor_and_static_paths_are_404_envelopes(web: WebApp) -> None:
    for path in ("/static/vendor/other.js", "/static/vendor/", "/static/missing.css", "/static"):
        response = web.client.get(path)
        assert (response.status_code, response.json()) == (404, NOT_FOUND), path


def test_static_requests_obey_the_host_check(web: WebApp) -> None:
    response = web.bare.get(PATH, headers={"Host": "evil.example"})
    assert (response.status_code, response.text) == (400, "Invalid host header")
