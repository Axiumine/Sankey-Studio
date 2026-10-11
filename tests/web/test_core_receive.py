"""Each early refusal of the middleware answers with the very ``receive`` and ``send`` it got."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NamedTuple

import pytest
from starlette.applications import Starlette

from sankey_studio.web import middleware
from sankey_studio.web.middleware import BodySizeLimit, CsrfGuard, refuse_too_large
from sankey_studio.web.security import UPLOAD_PATH, BodyLimits

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.types import Message, Receive, Scope, Send

    from sankey_studio.errors import SankeyError

PATH = "/api/v1/probe"


class Reply(NamedTuple):
    error: SankeyError
    path: str
    scope: Scope
    receive: Receive
    send: Send


class Spy:
    """Stands in for ``sankey_response``: records what the response would be called with."""

    def __init__(self) -> None:
        self.replies: list[Reply] = []

    def __call__(
        self, error: SankeyError, path: str
    ) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
        async def respond(scope: Scope, receive: Receive, send: Send) -> None:
            self.replies.append(Reply(error, path, scope, receive, send))

        return respond


class Channel(NamedTuple):
    """The two ASGI callables a test hands in, to be recognised by identity afterwards."""

    receive: Receive
    send: Send


def _channel(body: bytes = b"") -> Channel:
    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(_message: Message) -> None:
        return None

    return Channel(receive, send)


async def _read_once(_scope: Scope, receive: Receive, _send: Send) -> None:
    await receive()


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    recorder = Spy()
    monkeypatch.setattr(middleware, "sankey_response", recorder)
    return recorder


def _one(spy: Spy, channel: Channel, scope: Scope) -> Reply:
    (reply,) = spy.replies
    assert reply.scope is scope
    assert reply.receive is channel.receive
    assert reply.send is channel.send
    assert reply.path == scope["path"]
    return reply


def test_refuse_too_large_answers_413_with_the_limit(spy: Spy) -> None:
    channel, scope = _channel(), {"type": "http", "path": PATH}
    asyncio.run(refuse_too_large(scope, channel.receive, channel.send, 7))
    reply = _one(spy, channel, scope)
    assert (reply.error.code, reply.error.status_code) == ("payload_too_large", 413)
    assert reply.error.details == ["limit_bytes=7"]


def test_a_declared_length_over_the_cap_is_refused_before_the_app_runs(spy: Spy) -> None:
    channel = _channel()
    headers = [(b"content-length", b"11")]
    scope: Scope = {"type": "http", "method": "POST", "path": PATH, "headers": headers}
    limits = BodyLimits(json_bytes=10)
    asyncio.run(BodySizeLimit(_read_once, limits)(scope, channel.receive, channel.send))
    reply = _one(spy, channel, scope)
    assert reply.error.code == "payload_too_large"
    assert reply.error.details == ["limit_bytes=10"]


def test_a_closed_upload_route_answers_read_only_without_reading(spy: Spy) -> None:
    channel = _channel()
    scope: Scope = {"type": "http", "method": "POST", "path": UPLOAD_PATH, "headers": []}
    limits = BodyLimits(writes_allowed=False)
    asyncio.run(BodySizeLimit(_read_once, limits)(scope, channel.receive, channel.send))
    reply = _one(spy, channel, scope)
    assert (reply.error.code, reply.error.status_code) == ("read_only_mode", 403)


def test_a_streamed_body_over_the_cap_is_refused_with_the_original_receive(spy: Spy) -> None:
    channel = _channel(b"x" * 11)
    scope: Scope = {"type": "http", "method": "POST", "path": PATH, "headers": []}
    limits = BodyLimits(json_bytes=10)
    asyncio.run(BodySizeLimit(_read_once, limits)(scope, channel.receive, channel.send))
    reply = _one(spy, channel, scope)
    assert reply.error.code == "payload_too_large"


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ([(b"origin", b"http://evil.example"), (b"host", b"testserver")], "forbidden"),
        (
            [(b"sec-fetch-site", b"same-origin"), (b"content-type", b"text/plain")],
            "unsupported_media_type",
        ),
    ],
    ids=["cross-origin", "text-plain"],
)
def test_the_csrf_guard_refuses_with_the_original_receive(
    spy: Spy, headers: list[tuple[bytes, bytes]], code: str
) -> None:
    channel = _channel()
    scope: Scope = {"type": "http", "method": "POST", "path": PATH, "headers": headers}
    asyncio.run(CsrfGuard(Starlette(), ["testserver"])(scope, channel.receive, channel.send))
    assert _one(spy, channel, scope).error.code == code
