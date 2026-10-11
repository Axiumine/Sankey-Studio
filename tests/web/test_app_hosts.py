"""Host names are case-insensitive: ``allowed_hosts`` and the ``Host`` header, in both guards."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from sankey_studio.config import BootstrapConfig
from sankey_studio.web.app import create_app
from sankey_studio.web.middleware import CaseInsensitiveTrustedHost
from tests.web.ids import stable_id

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from starlette.types import Message, Receive, Scope, Send

JSON = {"Content-Type": "application/json"}
REFUSED = "Invalid host header"

router = APIRouter()


@router.get("/api/v1/echo")
def _echo(request: Request) -> dict[str, str]:
    """What the app below the host check sees."""
    return {"host": request.headers["host"], "x-case": request.headers.get("x-case", "")}


@router.post("/api/v1/echo")
def _post(payload: dict[str, Any]) -> dict[str, int]:
    return {"keys": len(payload)}


class Case(NamedTuple):
    allowed: list[str]
    host: str
    status: int


CASES = [
    Case(["MyServer.Local"], "myserver.local", 200),
    Case(["MyServer.Local"], "MYSERVER.LOCAL", 200),
    Case(["MyServer.Local"], "MyServer.Local", 200),
    Case(["MyServer.Local"], "myserver.local:8765", 200),
    Case(["MyServer.Local"], "MYSERVER.LOCAL:8765", 200),
    Case(["MyServer.Local"], "myserver.locale", 400),
    Case(["MyServer.Local"], "xmyserver.local", 400),
    Case(["MyServer.Local"], "other.local", 400),
    Case(["myserver.local"], "MyServer.Local", 200),
    Case(["*.Example.COM"], "a.example.com", 200),
    Case(["*.Example.COM"], "A.EXAMPLE.COM:80", 200),
    Case(["*.Example.COM"], "example.com", 400),
    Case(["*.Example.COM"], "evilexample.com", 400),
    Case(["[FE80::1]"], "[fe80::1]:8765", 200),
    Case(["[fe80::1]"], "[FE80::1]", 200),
    Case(["[FE80::1]"], "[fe80::2]", 400),
    Case(["localhost", "*"], "ANY.thing", 200),
]


def served(tmp_path: Path, allowed: Sequence[str], *, remote: bool = False) -> TestClient:
    config = BootstrapConfig(
        data_dir=tmp_path / "data", allowed_hosts=list(allowed), remote_mode=remote
    )
    return TestClient(create_app(config, routers=[router]))


@pytest.mark.parametrize("case", CASES, ids=lambda c: stable_id(f"{c.allowed[0]} {c.host}"))
def test_the_host_check_ignores_letter_case(tmp_path: Path, case: Case) -> None:
    with served(tmp_path, case.allowed, remote="*" in case.allowed) as client:
        response = client.get("/api/v1/echo", headers={"Host": case.host})
    assert response.status_code == case.status
    if case.status == 400:
        assert response.text == REFUSED
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
    else:
        assert response.json()["host"] == case.host.lower()


def test_only_the_host_header_is_lower_cased(tmp_path: Path) -> None:
    with served(tmp_path, ["MyServer.Local"]) as client:
        response = client.get("/api/v1/echo", headers={"Host": "MYSERVER.LOCAL", "X-Case": "AbC"})
    assert response.json() == {"host": "myserver.local", "x-case": "AbC"}


def test_a_www_name_is_refused_not_redirected(tmp_path: Path) -> None:
    with served(tmp_path, ["www.myserver.local"]) as client:
        response = client.get(
            "/api/v1/echo", headers={"Host": "myserver.local"}, follow_redirects=False
        )
    assert (response.status_code, response.text) == (400, REFUSED)


def test_the_error_pages_and_the_static_files_answer_the_host_check_too(tmp_path: Path) -> None:
    with served(tmp_path, ["MyServer.Local"]) as client:
        missing = client.get("/nope", headers={"Host": "MYSERVER.LOCAL"})
        refused = client.get("/nope", headers={"Host": "evil.example"})
    assert missing.status_code == 404
    assert (refused.status_code, refused.text) == (400, REFUSED)


# --------------------------------------------------------------------------- the CSRF guard


class Origin(NamedTuple):
    origin: str
    host: str
    status: int


ORIGINS = [
    Origin("http://myserver.local", "MYSERVER.LOCAL", 200),
    Origin("http://MYSERVER.LOCAL", "myserver.local", 200),
    Origin("http://MyServer.Local:8765", "myserver.local:8765", 200),
    Origin("http://myserver.local", "myserver.local:8765", 403),
    Origin("http://other.local", "myserver.local", 403),
    Origin("http://myserver.local", "other.local", 400),
]


@pytest.mark.parametrize("case", ORIGINS, ids=lambda c: stable_id(f"{c.origin} {c.host}"))
def test_the_csrf_guard_agrees_with_the_host_check_on_letter_case(
    tmp_path: Path, case: Origin
) -> None:
    with served(tmp_path, ["MyServer.Local"]) as client:
        response = client.post(
            "/api/v1/echo", json={}, headers={**JSON, "Origin": case.origin, "Host": case.host}
        )
    assert response.status_code == case.status
    if case.status == 403:
        assert response.json()["error"]["code"] == "forbidden"


# --------------------------------------------------------------------------- the class itself


async def _inner(scope: Scope, receive: Receive, send: Send) -> None:
    del scope, receive, send


def test_the_patterns_are_lower_cased_for_starlette() -> None:
    guard = CaseInsensitiveTrustedHost(_inner, ["MyServer.Local", "*.EXAMPLE.com", "[FE80::1]"])
    assert guard.allowed_hosts == ["myserver.local", "*.example.com", "[fe80::1]"]
    assert guard.allow_any is False
    assert CaseInsensitiveTrustedHost(_inner, ["*"]).allow_any is True


def test_the_www_redirect_is_off_unless_asked_for() -> None:
    assert CaseInsensitiveTrustedHost(_inner, ["a"]).www_redirect is False
    assert CaseInsensitiveTrustedHost(_inner, ["a"], www_redirect=True).www_redirect is True


def test_a_lifespan_scope_passes_through_untouched() -> None:
    seen: list[Scope] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        del receive, send
        seen.append(scope)

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_message: Message) -> None:
        return None

    scope: Scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
    asyncio.run(CaseInsensitiveTrustedHost(inner, ["only.example"])(scope, receive, send))
    assert len(seen) == 1
    assert seen[0] is scope
