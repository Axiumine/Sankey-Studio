# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md A.8, part 2: the response headers of the live server, on pages AND on the API.

Every answer carries the CSP, ``nosniff``, ``Referrer-Policy`` and ``Cross-Origin-Resource-Policy``;
the API and the HTML pages are ``no-store``; downloads are attachments under ``CSP: sandbox``;
errors (403, 404, 405, 413, 415, 422) carry the same headers as successes; there is no CORS and
no docs UI. The HTML pages contain no inline script or event handler (the CSP would block them).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_create, graph_draft, unique_name
from tests.e2e.support.clients import make_client, seed_graph
from tests.e2e.support.http_b_security import (
    assert_security_headers,
    boot_data,
    inline_code,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import httpx

    from tests.e2e.support.server import LiveServer

HTML = {"Accept": "text/html"}
SCRIPT_SRC = re.compile(r"<script\b[^>]*\bsrc=\"([^\"]+)\"")
MISSING = "0" * 32
PAGES = (
    pytest.param("/", 200, id="library"),
    pytest.param("/graphs/new", 200, id="editor"),
    pytest.param("/settings", 200, id="settings"),
    pytest.param("/compare", 200, id="compare-empty"),
    pytest.param("/compare?ids={gid}", 200, id="compare"),
    pytest.param("/graphs/{gid}", 200, id="viewer"),
    pytest.param("/graphs/{gid}/edit", 200, id="edit"),
    pytest.param("/no/such/page", 404, id="not-found"),
    pytest.param(f"/graphs/{MISSING}", 404, id="graph-not-found"),
)
DOWNLOADS = (
    pytest.param("/api/v1/graphs/{gid}/export?format=csv", id="csv"),
    pytest.param("/api/v1/graphs/{gid}/export?format=json", id="json"),
    pytest.param("/api/v1/graphs/{gid}/export?format=html", id="html"),
    pytest.param("/api/v1/graphs/{gid}/export?format=csv&chart=donut", id="donut-csv"),
    pytest.param("/api/v1/graphs/export?ids={gid}", id="bundle"),
)
JSON_ROUTES = (
    "/api/v1/health",
    "/api/v1/graphs",
    "/api/v1/tags",
    "/api/v1/settings",
    "/api/v1/graphs/{gid}",
    "/api/v1/graphs/{gid}/render",
    "/api/v1/compare/render?ids={gid}",
)


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def gid(module_server: LiveServer) -> Iterator[str]:
    with make_client(module_server) as client:
        yield str(
            seed_graph(client, unique_name("headers"), graph_draft(BUDGET_CATEGORISED.csv))["id"]
        )


# ------------------------------------------------------------------------------ pages


@pytest.mark.parametrize(("path", "status"), PAGES)
def test_every_html_page_has_the_security_headers_and_no_inline_code(
    api: httpx.Client, gid: str, path: str, status: int
) -> None:
    response = api.get(path.format(gid=gid), headers=HTML)
    assert response.status_code == status
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert_security_headers(response, no_store=True)
    assert inline_code(response.text) == []
    sources = SCRIPT_SRC.findall(response.text)
    assert sources
    assert all(src.startswith("/static/") for src in sources)
    data = boot_data(response.text)
    assert (data["remote_mode"], data["writes_allowed"]) == (False, True)


def test_the_not_found_page_does_not_echo_the_address(api: httpx.Client) -> None:
    response = api.get("/zz-marker-9f2c/zz-other", headers=HTML)
    assert response.status_code == 404
    assert "zz-marker" not in response.text
    assert "zz-other" not in response.text


# ------------------------------------------------------------------------------ API


@pytest.mark.parametrize("path", JSON_ROUTES)
def test_every_json_route_is_no_store_with_the_security_headers(
    api: httpx.Client, gid: str, path: str
) -> None:
    response = api.get(path.format(gid=gid))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert_security_headers(response, no_store=True)


@pytest.mark.parametrize("path", DOWNLOADS)
def test_every_download_is_an_attachment_in_a_csp_sandbox(
    api: httpx.Client, gid: str, path: str
) -> None:
    response = api.get(path.format(gid=gid))
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment; filename=")
    assert_security_headers(response, no_store=True, download=True)


def error_cases(client: httpx.Client, foreign: httpx.Client) -> list[Callable[[], httpx.Response]]:
    """Requests that fail in each way the API can refuse a request."""
    return [
        lambda: client.get("/api/v1/nope"),  # 404 unknown route
        lambda: client.get(f"/api/v1/graphs/{MISSING}"),  # 404 unknown graph
        lambda: client.get("/api/v1/graphs", params={"limit": "x"}),  # 422
        lambda: client.put("/api/v1/health", json={}),  # 405
        lambda: foreign.post("/api/v1/graphs", json=graph_create("x")),  # 403
        lambda: client.post("/api/v1/graphs", content="{}", headers={"Content-Type": "text/plain"}),
        lambda: client.post(
            "/api/v1/preview",
            content=b" " * (8 * 2**20 + 1),
            headers={"Content-Type": "application/json"},
        ),  # 413
    ]


def test_errors_carry_the_same_headers_as_successes(
    api: httpx.Client, foreign: httpx.Client
) -> None:
    statuses = []
    for call in error_cases(api, foreign):
        response = call()
        statuses.append(response.status_code)
        assert_security_headers(response, no_store=True)
        assert response.headers["content-type"] == "application/json"
        assert set(response.json()["error"]) == {"code", "message", "details"}
    assert statuses == [404, 404, 422, 405, 403, 415, 413]


# ------------------------------------------------------------------------------ static, CORS, docs


@pytest.mark.parametrize(
    ("path", "media"),
    [
        ("/static/vendor/plotly.min.js", "text/javascript"),
        ("/static/css/tokens.css", "text/css"),
        ("/static/js/core/shell.js", "text/javascript"),
        ("/static/v-0123456789ab/js/core/shell.js", "text/javascript"),
    ],
)
def test_static_files_are_served_locally_with_the_security_headers(
    api: httpx.Client, path: str, media: str
) -> None:
    response = api.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media)
    assert_security_headers(response, no_store=True)


def test_a_missing_or_escaping_static_path_is_a_json_404_with_no_file_content(
    api: httpx.Client,
) -> None:
    for path in (
        "/static/nope.js",
        "/static/%2e%2e/%2e%2e/etc/passwd",
        "/static/..%2f..%2fetc/passwd",
    ):
        response = api.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert "root:" not in response.text
        assert_security_headers(response, no_store=False)


def test_there_is_no_cors_no_preflight_and_no_docs_ui(api: httpx.Client) -> None:
    preflight = api.request(
        "OPTIONS",
        "/api/v1/graphs",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 405
    assert not [h for h in preflight.headers if h.lower().startswith("access-control-")]
    read = api.get("/api/v1/graphs", headers={"Origin": "http://evil.example"})
    assert read.status_code == 200
    assert "access-control-allow-origin" not in read.headers
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert api.get(path).status_code == 404
