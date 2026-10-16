# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Smoke tests of the e2e harness itself: one HTTP and one browser pass per fixture family.

If these fail, the problem is the harness (or the app does not start), not a suite built on it.
Deeper self-tests of the builders, the watcher and the artefacts are in
``test_harness_support``, ``test_harness_artifacts`` and ``test_harness_shared``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import fetch_json, json_of, make_client, seed_graph
from tests.e2e.support.pages import AppPage
from tests.e2e.support.server import port_is_closed

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.session import PageOpener
    from tests.e2e.support.watch import WatchedPage


class LibraryPage(AppPage):
    path = "/"
    name = "library"


# ------------------------------------------------------------------------------ HTTP smoke


def test_http_smoke_health_and_a_same_origin_write(
    live_server: LiveServer, api: httpx.Client
) -> None:
    assert json_of(api.get("/api/v1/health")) == {"status": "ok"}
    assert live_server.url.startswith("http://127.0.0.1:")
    assert live_server.port > 0
    name = unique_name("smoke")
    created = seed_graph(api, name)
    assert created["name"] == name
    assert created["revision"] == 1
    listing = json_of(api.get("/api/v1/graphs"))
    assert [item["id"] for item in listing["items"]] == [created["id"]]
    assert [p.stem for p in live_server.graphs_dir.glob("*.json")] == [created["id"]]


def test_the_clients_differ_only_by_their_origin(
    api: httpx.Client, foreign: httpx.Client, bare: httpx.Client
) -> None:
    body = {"sample": "a,b,1"}
    assert api.post("/api/v1/sources/detect", json=body).status_code == 200
    refused = foreign.post("/api/v1/sources/detect", json=body)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden"
    # curl-style: no Origin at all is fine for a JSON body ...
    assert bare.post("/api/v1/sources/detect", json=body).status_code == 200
    # ... but not for a multipart upload.
    upload = bare.post("/api/v1/sources/files", files={"file": ("a.csv", b"a,b,1", "text/csv")})
    assert upload.status_code == 403


def test_the_server_stops_cleanly_and_its_port_is_closed(make_server: ServerFactory) -> None:
    server = make_server()
    assert not port_is_closed(server.host, server.port)
    server.stop()
    assert port_is_closed(server.host, server.port)
    server.stop()  # idempotent
    assert not server.thread.is_alive()


def test_every_server_gets_its_own_port_and_directories(make_server: ServerFactory) -> None:
    first, second = make_server(), make_server()
    assert first.port != second.port
    assert first.data_dir != second.data_dir
    assert first.sources_dir != second.sources_dir
    first.stop()
    assert port_is_closed(first.host, first.port)
    assert not port_is_closed(second.host, second.port)


def test_the_read_only_remote_variant_refuses_writes_over_http(make_server: ServerFactory) -> None:
    server = make_server(remote_mode=True)
    assert server.read_only
    with make_client(server) as client:
        refused = client.put("/api/v1/settings", json={})
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "read_only_mode"
        assert client.get("/api/v1/graphs").status_code == 200


def test_export_unavailable_answers_501_for_images_only(make_server: ServerFactory) -> None:
    server = make_server(export_unavailable=True)
    with make_client(server) as api:
        graph = seed_graph(api, unique_name("export"))
        route = f"/api/v1/graphs/{graph['id']}/export"
        for fmt in ("svg", "png"):
            response = api.get(route, params={"format": fmt})
            assert response.status_code == 501
            error = response.json()["error"]
            assert error["code"] == "export_unavailable"
            assert "Chrome" in error["message"]
        assert api.get(route, params={"format": "csv"}).status_code == 200
        assert api.get(route, params={"format": "json"}).status_code == 200


# ------------------------------------------------------------------------------ browser smoke


def test_browser_smoke_the_library_loads_without_a_single_complaint(
    page: WatchedPage, live_server: LiveServer
) -> None:
    library = LibraryPage(page, live_server)
    response = library.goto()
    assert response is not None
    assert response.status == 200
    expect(library.heading).to_have_text("Graphs")
    expect(library.tid("library-empty")).to_be_visible()
    expect(library.nav("new")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-theme", "system")
    # the page fixture asserts at teardown: no console error/warning, page error, CSP violation,
    # failed request or 4xx/5xx response.


def test_browser_smoke_the_read_only_variant_shows_its_banners(
    make_server: ServerFactory, open_page: PageOpener
) -> None:
    server = make_server(remote_mode=True)
    page = open_page(server, color_scheme="light", viewport={"width": 1280, "height": 900})
    library = LibraryPage(page, server)
    library.goto()
    expect(library.remote_banner).to_be_visible()
    expect(library.read_only_banner).to_be_visible()


def test_browser_smoke_a_local_server_shows_no_banner(
    page: WatchedPage, live_server: LiveServer
) -> None:
    library = LibraryPage(page, live_server)
    library.goto()
    expect(library.remote_banner).to_have_count(0)
    expect(library.read_only_banner).to_have_count(0)


def test_browser_smoke_export_unavailable_reaches_the_page_as_a_501(
    make_server: ServerFactory, open_page: PageOpener
) -> None:
    server = make_server(export_unavailable=True)
    page = open_page(server, color_scheme="light", viewport={"width": 1280, "height": 900})
    LibraryPage(page, server).goto()
    # a 501 is an expected 4xx/5xx for this test only (Chrome logs it as well)
    page.allow_http(501, "/api/v1/export")
    result = fetch_json(page, "POST", "/api/v1/export", {"source": {"type": "manual", "links": []}})
    assert result.status == 501
    assert result.json["error"]["code"] == "export_unavailable"
    assert page.watch.matching(r"^http 501: POST .*/api/v1/export")


@pytest.mark.parametrize("color_scheme", ["dark"])
def test_browser_smoke_color_scheme_is_a_parametrizable_fixture(
    page: WatchedPage, live_server: LiveServer
) -> None:
    LibraryPage(page, live_server).goto()
    assert page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") is True
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is True
