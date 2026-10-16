# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Host check, no docs UI, no CORS and the security headers, on every route of the FULL app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from sankey_studio.web.security import CSP
from tests.web.test_matrix_support import ENDPOINTS, Endpoint, ids

if TYPE_CHECKING:
    from tests.web.conftest import WebApp

NOT_FOUND = {"error": {"code": "not_found", "message": "Not Found", "details": []}}
PLOTLY: Final = "/static/vendor/plotly.min.js"
PREVIEW: Final = Endpoint("POST", "/api/v1/preview", "/api/v1/preview")
BAD_HOSTS: Final = ["evil.example", "testserver.evil.example", "evil.example:80", "127.0.0.2"]
GOOD_HOSTS: Final = ["testserver", "localhost:8765", "127.0.0.1", "[::1]:8765"]
POLICY: Final = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}
DOC_PATHS: Final = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
    "/api/docs",
    "/api/openapi.json",
    "/api/v1/docs",
    "/api/v1/openapi.json",
    "/api/v1/redoc",
]


def call(web: WebApp, endpoint: Endpoint, headers: dict[str, str]) -> tuple[int, str]:
    """Send ``endpoint`` with a JSON body and the CSRF proof, plus ``headers`` on top."""
    sent = {"Origin": "http://testserver", "Content-Type": "application/json", **headers}
    response = web.bare.request(endpoint.method, endpoint.path, headers=sent, content=b"{}")
    return response.status_code, response.text


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ids(ENDPOINTS))
@pytest.mark.parametrize("host", BAD_HOSTS)
def test_a_foreign_host_header_is_refused_on_every_route(
    web: WebApp, endpoint: Endpoint, host: str
) -> None:
    response = web.bare.request(endpoint.method, endpoint.path, headers={"Host": host})
    assert (response.status_code, response.text) == (400, "Invalid host header")
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize("host", GOOD_HOSTS)
def test_the_allowed_hosts_reach_the_routes(web: WebApp, host: str) -> None:
    for path in ("/api/v1/health", "/graphs/new", PLOTLY):
        assert web.bare.get(path, headers={"Host": host}).status_code == 200


def test_a_matching_origin_on_a_foreign_host_is_still_refused(web: WebApp) -> None:
    headers = {"Host": "evil.example", "Origin": "http://evil.example"}
    status, body = call(web, PREVIEW, headers)
    assert (status, body) == (400, "Invalid host header")


@pytest.mark.parametrize("path", DOC_PATHS)
def test_there_is_no_docs_ui_or_schema(web: WebApp, path: str) -> None:
    for client in (web.client, web.bare):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == NOT_FOUND


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ids(ENDPOINTS))
def test_no_route_sends_cors_headers_and_a_preflight_is_not_answered(
    web: WebApp, endpoint: Endpoint
) -> None:
    foreign = {"Origin": "http://evil.example", "Access-Control-Request-Method": endpoint.method}
    simple = web.bare.request(
        endpoint.method, endpoint.path, headers={"Origin": "http://evil.example"}
    )
    preflight = web.bare.options(endpoint.path, headers=foreign)
    for response in (simple, preflight):
        assert not [n for n in response.headers if n.startswith("access-control-")]
    assert preflight.status_code == 405
    assert preflight.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ids(ENDPOINTS))
def test_every_response_carries_the_security_headers(web: WebApp, endpoint: Endpoint) -> None:
    response = web.client.request(endpoint.method, endpoint.path, content=b"{}")
    for name, value in POLICY.items():
        assert response.headers[name] == value, name


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=ids(ENDPOINTS))
def test_api_answers_are_no_store_and_pages_are_not(web: WebApp, endpoint: Endpoint) -> None:
    response = web.client.request(endpoint.method, endpoint.path, content=b"{}")
    never_stored = endpoint.template.startswith("/api/") or endpoint.template == PLOTLY
    if never_stored or response.headers["content-type"].startswith("text/html"):
        assert response.headers["cache-control"] == "no-store"
    else:
        assert "cache-control" not in response.headers


def test_the_refusals_of_the_middleware_carry_the_headers_too(web: WebApp) -> None:
    refused = [
        web.bare.get("/api/v1/health", headers={"Sec-Fetch-Site": "cross-site"}),
        web.bare.post("/api/v1/preview", content=b"{}", headers={"Content-Type": "text/plain"}),
        web.client.post("/api/v1/preview", content=b"a" * (8 * 2**20 + 1)),
        web.client.post("/api/v1/preview", content=b"{}", headers={"Content-Type": "text/plain"}),
    ]
    assert [r.status_code for r in refused] == [403, 403, 413, 415]
    for response in refused:
        assert response.headers["cache-control"] == "no-store"
        for name, value in POLICY.items():
            assert response.headers[name] == value, name


def test_an_unknown_route_is_a_404_envelope_with_the_headers(web: WebApp) -> None:
    for path in ("/nope", "/api/v1/nope", "/api/v1", "/api/v1/graphs/x/y/z"):
        response = web.client.get(path)
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        assert response.headers["content-security-policy"] == CSP
