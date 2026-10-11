"""Boundaries of the web core that an independent mutation pass found unpinned."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi import APIRouter
from starlette.applications import Starlette

from sankey_studio.web import routers as router_registry
from sankey_studio.web.errors import ErrorBody, error_response
from sankey_studio.web.middleware import CsrfGuard, host_allowed
from sankey_studio.web.security import MIB, BodyLimits

if TYPE_CHECKING:
    from starlette.types import Scope

    from tests.web.conftest import AppFactory

router = APIRouter()


@router.get("/api/v1/probe")
def _probe() -> dict[str, bool]:
    return {"ok": True}


def test_an_explicit_empty_router_list_does_not_fall_back_to_the_registry(
    make_app: AppFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router_registry, "ALL_ROUTERS", (router,))
    assert make_app().client.get("/api/v1/probe").json() == {"ok": True}
    assert make_app([]).client.get("/api/v1/probe").status_code == 404


class HostCase(NamedTuple):
    host: str
    allowed: list[str]
    expected: bool


EXACT = [
    HostCase("localhost", ["localhost"], True),
    HostCase("xocalhost", ["localhost"], False),
    HostCase("evil.example.com", ["example.com"], False),
    HostCase("example.com", ["example.com"], True),
    HostCase("a.example.com", ["*.example.com"], True),
    HostCase("example.com", ["*.example.com"], False),
]


@pytest.mark.parametrize("case", EXACT, ids=lambda c: f"{c.host}-{c.allowed}")
def test_a_pattern_without_a_star_matches_only_itself(case: HostCase) -> None:
    assert host_allowed(case.host, case.allowed) is case.expected


def _json_scope(content_type: bytes) -> Scope:
    headers = [(b"host", b"testserver"), (b"content-type", content_type)]
    return {"type": "http", "method": "POST", "path": "/", "headers": headers}


@pytest.mark.parametrize(
    "content_type",
    [
        b"application/json",
        b"Application/JSON",
        b"application/json; charset=utf-8",
        b"application/json ; charset=utf-8",
        b" application/json ",
    ],
)
def test_json_is_recognised_whatever_the_spacing_and_case(content_type: bytes) -> None:
    guard = CsrfGuard(Starlette(), ["testserver"])
    assert guard.verdict(_json_scope(content_type)) is None


def test_headers_given_to_an_error_response_win_over_the_policy_defaults() -> None:
    body = ErrorBody("http_error", "Method Not Allowed")
    response = error_response(405, body, "/api/v1/x", {"Cache-Control": "private", "Allow": "GET"})
    assert response.headers["cache-control"] == "private"
    assert response.headers["allow"] == "GET"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.status_code == 405


class Route(NamedTuple):
    path: str
    cap: int


ROUTES = [
    Route("/api/v1/sources/files", 101 * MIB),
    Route("/api/v1/graphs/import", 16 * MIB),
    Route("/api/v1/graphs", 8 * MIB),
    Route("/api/v1/sources/files/", 8 * MIB),
    Route("/api/v1/graphs/import/", 8 * MIB),
    Route("/api/v1/sources/files/x", 8 * MIB),
]


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.path)
def test_the_special_body_caps_are_bound_to_the_spec_route_table(route: Route) -> None:
    assert BodyLimits().limit_for(route.path) == route.cap


def test_multipart_is_accepted_on_the_spec_upload_path_only() -> None:
    guard = CsrfGuard(Starlette(), ["testserver"])
    multipart = b"multipart/form-data; boundary=x"

    def verdict(path: str) -> object:
        scope = _json_scope(multipart)
        scope["path"] = path
        scope["headers"] = [*scope["headers"], (b"sec-fetch-site", b"same-origin")]
        return guard.verdict(scope)

    assert verdict("/api/v1/sources/files") is None
    assert verdict("/api/v1/graphs/import") is not None
    assert verdict("/api/v1/sources/files/") is not None
