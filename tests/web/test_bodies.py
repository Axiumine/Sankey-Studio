"""Request-body caps: per route, counted while streaming, answered 413 in the envelope."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from starlette.routing import Route

from sankey_studio.models import AppSettings
from sankey_studio.web.middleware import BodySizeLimit, _declared_length
from sankey_studio.web.security import (
    IMPORT_PATH,
    MIB,
    UPLOAD_PATH,
    BodyLimits,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.types import Message, Receive, Scope, Send

    from tests.web.conftest import AppFactory

JSON_PATH = "/api/v1/probe"
LIMITS = BodyLimits(json_bytes=10, import_bytes=20, upload_bytes=30)
ENVELOPE = {
    "error": {
        "code": "payload_too_large",
        "message": "The request body is too large",
        "details": ["limit_bytes=10"],
    }
}


class Target(NamedTuple):
    path: str
    cap: int


ROUTES = [
    Target(JSON_PATH, 10),
    Target(IMPORT_PATH, 20),
    Target(UPLOAD_PATH, 30),
    Target(IMPORT_PATH + "/", 10),
    Target(UPLOAD_PATH + "/x", 10),
    Target("/", 10),
]


async def _size(request: Request) -> JSONResponse:
    return JSONResponse({"size": len(await request.body())})


async def _disconnects(_request: Request) -> JSONResponse:
    raise ClientDisconnect


def _inner() -> Starlette:
    routes = [
        Route("/disconnect", _disconnects, methods=["POST"]),
        Route("/{path:path}", _size, methods=["GET", "POST", "PUT"]),
    ]
    return Starlette(routes=routes)


@pytest.fixture
def limited() -> Iterator[TestClient]:
    with TestClient(BodySizeLimit(_inner(), LIMITS)) as client:
        yield client


def _chunks(count: int) -> Iterator[bytes]:
    for _ in range(count):
        yield b"a"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(b"10", 10), (b"0", 0), (b"", None), (b"-1", None), (b"1.5", None), (b"\xb2", None)],
)
def test_declared_length_reads_plain_ascii_digits_only(raw: bytes, expected: int | None) -> None:
    # b"\xb2" is the superscript two: str.isdigit() is True for it but int() refuses it
    headers = Headers(raw=[(b"content-length", raw)])
    assert _declared_length(headers) == expected


def test_default_limits_are_exact() -> None:
    limits = BodyLimits()
    assert limits.json_bytes == 8 * 1024 * 1024
    assert limits.import_bytes == 16 * 1024 * 1024
    assert limits.upload_bytes == 101 * 1024 * 1024


def test_upload_cap_is_the_setting_ceiling_plus_one_mib() -> None:
    bounds = AppSettings.model_fields["max_upload_mb"].metadata
    ceiling = next(m.le for m in bounds if hasattr(m, "le"))
    assert BodyLimits().upload_bytes == (ceiling + 1) * MIB


@pytest.mark.parametrize("route", ROUTES)
def test_limit_for_picks_the_route_cap(route: Target) -> None:
    assert LIMITS.limit_for(route.path) == route.cap


@pytest.mark.parametrize("route", ROUTES)
def test_declared_length_at_the_cap_passes_and_one_over_is_refused(
    limited: TestClient, route: Target
) -> None:
    at_cap = limited.post(route.path, content=b"a" * route.cap)
    over = limited.post(route.path, content=b"a" * (route.cap + 1))
    assert (at_cap.status_code, at_cap.json()) == (200, {"size": route.cap})
    assert over.status_code == 413
    assert over.json()["error"]["details"] == [f"limit_bytes={route.cap}"]


@pytest.mark.parametrize("route", ROUTES)
def test_chunked_body_without_content_length_is_counted(limited: TestClient, route: Target) -> None:
    at_cap = limited.post(route.path, content=_chunks(route.cap))
    over = limited.post(route.path, content=_chunks(route.cap + 1))
    assert "content-length" not in at_cap.request.headers
    assert (at_cap.status_code, at_cap.json()) == (200, {"size": route.cap})
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "payload_too_large"


def test_a_lying_content_length_does_not_help(limited: TestClient) -> None:
    response = limited.post(JSON_PATH, content=b"a" * 50, headers={"Content-Length": "1"})
    assert response.status_code == 413
    assert response.json() == ENVELOPE


@pytest.mark.parametrize("declared", ["abc", "-5", "1e3", ""])
def test_a_malformed_content_length_falls_back_to_counting(
    limited: TestClient, declared: str
) -> None:
    fits = limited.post(JSON_PATH, content=b"a" * 10, headers={"Content-Length": declared})
    over = limited.post(JSON_PATH, content=b"a" * 11, headers={"Content-Length": declared})
    assert fits.status_code == 200
    assert over.status_code == 413


def test_the_refusal_is_the_standard_envelope_with_security_headers(
    limited: TestClient,
) -> None:
    response = limited.post(JSON_PATH, content=b"a" * 11)
    assert response.status_code == 413
    assert response.json() == ENVELOPE
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_a_page_refusal_has_no_cache_control(limited: TestClient) -> None:
    response = limited.post("/page", content=b"a" * 11)
    assert response.status_code == 413
    assert "cache-control" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_request_without_a_body_is_not_limited(limited: TestClient) -> None:
    response = limited.get(JSON_PATH)
    assert (response.status_code, response.json()) == (200, {"size": 0})


def test_a_route_that_reads_the_body_itself_gets_the_413_not_an_error(
    limited: TestClient,
) -> None:
    response = limited.post(JSON_PATH, content=_chunks(11))
    assert response.status_code == 413


def test_a_real_client_disconnect_still_reaches_the_server(limited: TestClient) -> None:
    with pytest.raises(ClientDisconnect):
        limited.post("/disconnect", content=b"a")


class Raw:
    """A raw ASGI app that records the messages it reads; ``early`` starts the response first."""

    def __init__(self, *, early: bool) -> None:
        self.early = early
        self.seen: list[str] = []

    async def __call__(self, _scope: Scope, receive: Receive, send: Send) -> None:
        if self.early:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        message = await receive()
        while message["type"] == "http.request" and message.get("more_body"):
            message = await receive()
        self.seen.append(message["type"])
        if not self.early:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"done"})
        self.seen.append((await receive())["type"])


def test_a_message_without_a_body_key_counts_zero_bytes() -> None:
    inner = Raw(early=False)
    messages: Iterator[Message] = iter(
        [{"type": "http.request", "more_body": False}, {"type": "http.disconnect"}]
    )
    sent: list[str] = []

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        sent.append(message["type"])

    scope: Scope = {"type": "http", "path": JSON_PATH, "headers": []}
    asyncio.run(BodySizeLimit(inner, BodyLimits(json_bytes=3))(scope, receive, send))
    assert inner.seen == ["http.request", "http.disconnect"]
    assert sent == ["http.response.start", "http.response.body"]


def test_nothing_is_read_from_the_client_once_the_cap_is_passed() -> None:
    inner = Raw(early=False)
    messages: Iterator[Message] = iter(
        [
            {"type": "http.request", "body": b"abcd", "more_body": True},
            {"type": "http.request", "body": b"more", "more_body": False},
        ]
    )
    sent: list[Message] = []

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "path": JSON_PATH, "headers": []}
    asyncio.run(BodySizeLimit(inner, BodyLimits(json_bytes=3))(scope, receive, send))
    # the app is told "disconnect" twice; its own 200 is dropped, the client got one 413
    assert inner.seen == ["http.disconnect", "http.disconnect"]
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [413]


def test_a_response_already_started_is_not_replaced() -> None:
    inner = Raw(early=True)
    response = TestClient(BodySizeLimit(inner, LIMITS)).post(JSON_PATH, content=_chunks(11))
    assert response.status_code == 200
    assert response.text == "done"
    # the app is told once, and asking again does not touch the real receive channel
    assert inner.seen == ["http.disconnect", "http.disconnect"]


def test_a_client_disconnect_passes_through_untouched() -> None:
    inner = Raw(early=False)
    response = TestClient(BodySizeLimit(inner, LIMITS)).post(JSON_PATH, content=b"a" * 10)
    assert (response.status_code, response.text) == (200, "done")
    assert inner.seen == ["http.request", "http.disconnect"]


# --------------------------------------------------------------------------- the whole app

probe = APIRouter()


class _Size(BaseModel):
    size: int


@probe.post(JSON_PATH)
async def _echo(request: Request) -> _Size:
    return _Size(size=len(await request.body()))


def test_the_app_caps_json_bodies_at_8_mib(make_app: AppFactory) -> None:
    web = make_app([probe])
    headers = {"Content-Type": "application/json"}
    fits = web.client.post(JSON_PATH, content=b"a" * (8 * MIB), headers=headers)
    over = web.client.post(JSON_PATH, content=b"a" * (8 * MIB + 1), headers=headers)
    chunked = web.client.post(JSON_PATH, content=iter([b"a" * (8 * MIB), b"a"]), headers=headers)
    assert (fits.status_code, fits.json()) == (200, {"size": 8 * MIB})
    assert over.status_code == 413
    assert chunked.status_code == 413
    assert chunked.json()["error"]["details"] == [f"limit_bytes={8 * MIB}"]


def test_the_app_uses_the_default_caps_and_a_live_upload_setting(make_app: AppFactory) -> None:
    app: Any = make_app([probe]).app
    wrappers = {m.cls.__name__: m for m in app.user_middleware}
    (limits,) = wrappers["BodySizeLimit"].args
    assert limits.upload_mb is not None
    assert replace(limits, upload_mb=None) == BodyLimits()
