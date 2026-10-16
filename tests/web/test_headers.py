# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Security headers, Host checking, no CORS and non-HTTP scopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi import APIRouter
from starlette.responses import PlainTextResponse
from starlette.websockets import WebSocketDisconnect

from sankey_studio.web.security import API_PREFIX, CSP, DEFAULT_POLICY, HeaderPolicy

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

EXPECTED_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)
PAGE_HEADERS = {
    "content-security-policy": EXPECTED_CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}

router = APIRouter()


@router.get("/api/v1/probe")
def _api() -> dict[str, bool]:
    return {"ok": True}


@router.get("/page")
def _page() -> PlainTextResponse:
    return PlainTextResponse("hello")


@router.get("/api/v1/probe/own")
def _own() -> PlainTextResponse:
    return PlainTextResponse(
        "own", headers={"content-security-policy": "sandbox", "Cache-Control": "max-age=60"}
    )


@pytest.fixture
def probe(make_app: AppFactory) -> WebApp:
    return make_app([router])


def test_the_csp_is_exactly_the_spec_policy() -> None:
    assert CSP == EXPECTED_CSP


def test_the_default_policy_headers() -> None:
    assert dict(DEFAULT_POLICY.everywhere) == {
        "Content-Security-Policy": EXPECTED_CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    assert DEFAULT_POLICY.api_only == (("Cache-Control", "no-store"),)
    assert DEFAULT_POLICY.api_prefix == API_PREFIX == "/api/"


class Where(NamedTuple):
    path: str
    api: bool


@pytest.mark.parametrize(
    "where",
    [
        Where("/api/v1/health", api=True),
        Where("/api/", api=True),
        Where("/api", api=False),
        Where("/apix/v1", api=False),
        Where("/", api=False),
        Where("/static/api/x.js", api=False),
    ],
)
def test_no_store_is_for_api_paths_only(where: Where) -> None:
    names = [name for name, _ in DEFAULT_POLICY.for_path(where.path)]
    assert ("Cache-Control" in names) is where.api
    assert names[:4] == [name for name, _ in DEFAULT_POLICY.everywhere]


def test_a_policy_is_data() -> None:
    policy = HeaderPolicy(everywhere=(("X-A", "1"),), api_only=(("X-B", "2"),), api_prefix="/v/")
    assert policy.for_path("/v/x") == [("X-A", "1"), ("X-B", "2")]
    assert policy.for_path("/api/x") == [("X-A", "1")]


def test_api_responses_carry_every_header_and_no_store(probe: WebApp) -> None:
    response = probe.client.get("/api/v1/probe")
    assert response.status_code == 200
    for name, value in PAGE_HEADERS.items():
        assert response.headers[name] == value
    assert response.headers["cache-control"] == "no-store"


def test_page_responses_carry_the_headers_without_no_store(probe: WebApp) -> None:
    response = probe.client.get("/page")
    for name, value in PAGE_HEADERS.items():
        assert response.headers[name] == value
    assert "cache-control" not in response.headers


def test_a_header_the_route_sets_is_kept_not_duplicated(probe: WebApp) -> None:
    response = probe.client.get("/api/v1/probe/own")
    assert response.headers.get_list("content-security-policy") == ["sandbox"]
    assert response.headers.get_list("cache-control") == ["max-age=60"]
    assert response.headers["x-content-type-options"] == "nosniff"


class HostCase(NamedTuple):
    host: str
    status: int


@pytest.mark.parametrize(
    "case",
    [
        HostCase("testserver", 200),
        HostCase("localhost:8765", 200),
        HostCase("127.0.0.1", 200),
        HostCase("[::1]:8765", 200),
        HostCase("evil.example", 400),
        HostCase("testserver.evil.example", 400),
        HostCase("evil.example:80", 400),
        HostCase("127.0.0.2", 400),
    ],
)
def test_only_allowed_hosts_are_served(probe: WebApp, case: HostCase) -> None:
    response = probe.bare.get("/page", headers={"Host": case.host})
    assert response.status_code == case.status
    assert response.text == ("hello" if case.status == 200 else "Invalid host header")


def test_no_cors_headers_are_ever_sent(probe: WebApp) -> None:
    same = probe.client.get("/api/v1/probe", headers={"Origin": "http://testserver"})
    foreign = probe.bare.get("/api/v1/probe", headers={"Origin": "http://evil.example"})
    preflight = probe.bare.options(
        "/api/v1/probe",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    for response in (same, foreign, preflight):
        assert not [h for h in response.headers if h.startswith("access-control-")]
    assert preflight.status_code == 405


def test_a_websocket_scope_passes_through_every_middleware(probe: WebApp) -> None:
    with pytest.raises(WebSocketDisconnect), probe.client.websocket_connect("/ws"):
        pass  # there is no websocket route: the app closes it, the middleware stay out of it
