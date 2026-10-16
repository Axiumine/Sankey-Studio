# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The pure pieces of the CSRF guard: origin parsing, host matching, the allowed-host list."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from sankey_studio.errors import ForbiddenError
from sankey_studio.web.middleware import CsrfGuard, host_allowed, origin_of

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.types import Scope

JSON = {"Content-Type": "application/json"}


class OriginCase(NamedTuple):
    value: str
    parsed: tuple[str, str, int] | None


ORIGINS = [
    OriginCase("http://localhost:8765", ("http", "localhost", 8765)),
    OriginCase("http://localhost", ("http", "localhost", 80)),
    OriginCase("https://Example.COM", ("https", "example.com", 443)),
    OriginCase("https://example.com:8443", ("https", "example.com", 8443)),
    OriginCase("http://[::1]:8765", ("http", "::1", 8765)),
    OriginCase("http://127.0.0.1:1", ("http", "127.0.0.1", 1)),
    OriginCase("null", None),
    OriginCase("", None),
    OriginCase("http://", None),
    OriginCase("http:///x", None),
    OriginCase("localhost:8765", None),
    OriginCase("ftp://localhost", None),
    OriginCase("//localhost", None),
    OriginCase("http://localhost/", None),
    OriginCase("http://localhost/path", None),
    OriginCase("http://localhost?q", None),
    OriginCase("http://localhost#f", None),
    OriginCase("http://user@localhost", None),
    OriginCase("http://:pw@localhost", None),
    OriginCase("http://@localhost", None),
    OriginCase("http://localhost:abc", None),
    OriginCase("http://localhost:65536", None),
    OriginCase("http://[::1", None),
]


@pytest.mark.parametrize("case", ORIGINS, ids=lambda c: c.value or "empty")
def test_origin_of(case: OriginCase) -> None:
    assert origin_of(case.value) == case.parsed


class HostCase(NamedTuple):
    host: str
    allowed: list[str]
    expected: bool


HOSTS = [
    HostCase("localhost", ["localhost"], True),
    HostCase("localhost", ["127.0.0.1", "localhost"], True),
    HostCase("localhost", ["127.0.0.1"], False),
    HostCase("localhost", [], False),
    HostCase("::1", ["::1"], True),
    HostCase("a.example.com", ["*.example.com"], True),
    HostCase("example.com", ["*.example.com"], False),
    HostCase("badexample.com", ["*.example.com"], False),
    HostCase("anything.test", ["*"], True),
    HostCase("", ["*"], True),
]


@pytest.mark.parametrize("case", HOSTS, ids=lambda c: f"{c.host}-{c.allowed}")
def test_host_allowed(case: HostCase) -> None:
    assert host_allowed(case.host, case.allowed) is case.expected


async def _ok(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _guarded(allowed: list[str], base_url: str) -> TestClient:
    inner = Starlette(routes=[Route("/", _ok, methods=["POST"])])
    return TestClient(CsrfGuard(inner, allowed), base_url=base_url)


class ListCase(NamedTuple):
    allowed: list[str]
    base_url: str
    status: int


LISTS = [
    ListCase(["testserver"], "http://testserver", 200),
    ListCase(["TestServer"], "http://testserver", 200),
    ListCase(["only.example"], "http://testserver", 403),
    ListCase([], "http://testserver", 403),
    ListCase(["*"], "http://anything.test", 200),
    ListCase(["*.example"], "http://api.example", 200),
    ListCase(["*.example"], "http://example", 403),
    ListCase(["[::1]"], "http://[::1]:8765", 200),
    ListCase(["::1"], "http://[::1]:8765", 200),
    ListCase(["127.0.0.1"], "http://[::1]:8765", 403),
]


@pytest.mark.parametrize("case", LISTS, ids=lambda c: f"{c.allowed}-{c.base_url}")
def test_the_origin_host_must_be_in_the_allowed_list(case: ListCase) -> None:
    client = _guarded(case.allowed, case.base_url)
    response = client.post("/", headers={"Origin": case.base_url, **JSON}, content=b"{}")
    assert response.status_code == case.status


def test_the_scheme_comes_from_the_connection() -> None:
    client = _guarded(["testserver"], "https://testserver")
    same = client.post("/", headers={"Origin": "https://testserver", **JSON}, content=b"{}")
    plain = client.post("/", headers={"Origin": "http://testserver", **JSON}, content=b"{}")
    assert same.status_code == 200
    assert plain.status_code == 403


def _scope(*pairs: tuple[bytes, bytes]) -> Scope:
    base = [(b"origin", b"http://testserver"), (b"content-type", b"application/json")]
    return {"type": "http", "method": "POST", "path": "/", "headers": [*base, *pairs]}


def test_a_request_without_a_host_header_cannot_match_an_origin() -> None:
    guard = CsrfGuard(Starlette(), ["*"])
    assert guard.verdict(_scope((b"host", b"testserver"))) is None
    refusal = guard.verdict(_scope())
    assert isinstance(refusal, ForbiddenError)
    assert refusal.message == "Cross-origin request refused"


def test_a_scope_without_a_scheme_is_plain_http() -> None:
    guard = CsrfGuard(Starlette(), ["testserver"])
    assert guard.verdict(_scope((b"host", b"testserver"))) is None
    secure = _scope((b"host", b"testserver"))
    secure["scheme"] = "https"
    assert isinstance(guard.verdict(secure), ForbiddenError)
