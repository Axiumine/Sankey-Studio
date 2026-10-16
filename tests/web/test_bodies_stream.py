# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The body cap is cumulative: many messages that are each small still add up to a 413."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.web.middleware import BodySizeLimit
from sankey_studio.web.security import BodyLimits

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.types import Message, Receive, Scope, Send

PATH = "/api/v1/probe"
LIMIT = 10


class Outcome(NamedTuple):
    status: int
    seen: list[int]
    ended: str


class Reader:
    """A raw ASGI app that reads the whole body and answers 200 with what it saw."""

    def __init__(self) -> None:
        self.seen: list[int] = []
        self.ended = ""

    async def __call__(self, _scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] != "http.request":
                self.ended = message["type"]
                break
            self.seen.append(len(message["body"]))
            if not message["more_body"]:
                self.ended = "complete"
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _messages(sizes: list[int]) -> Iterator[Message]:
    for index, size in enumerate(sizes):
        last = index == len(sizes) - 1
        yield {"type": "http.request", "body": b"a" * size, "more_body": not last}


def _drive(sizes: list[int], method: str = "POST") -> Outcome:
    inner = Reader()
    messages = _messages(sizes)
    sent: list[Message] = []

    async def receive() -> Message:
        return next(messages, {"type": "http.disconnect"})

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "method": method, "path": PATH, "headers": []}
    asyncio.run(BodySizeLimit(inner, BodyLimits(json_bytes=LIMIT))(scope, receive, send))
    (start,) = (m["status"] for m in sent if m["type"] == "http.response.start")
    return Outcome(start, inner.seen, inner.ended)


class Split(NamedTuple):
    sizes: list[int]
    status: int


SPLITS = [
    Split([10], 200),
    Split([11], 413),
    Split([5, 5], 200),
    Split([6, 5], 413),
    Split([6, 6], 413),
    Split([4, 3, 3], 200),
    Split([4, 3, 4], 413),
    Split([1] * 10, 200),
    Split([1] * 11, 413),
    Split([0, 0, 10, 0], 200),
    Split([0, 5, 0, 6], 413),
]


@pytest.mark.parametrize("split", SPLITS, ids=lambda s: "+".join(map(str, s.sizes)))
def test_the_cap_counts_the_sum_of_all_messages(split: Split) -> None:
    assert _drive(split.sizes).status == split.status


def test_every_message_up_to_the_cap_reaches_the_app() -> None:
    outcome = _drive([4, 3, 3])
    assert outcome == Outcome(200, [4, 3, 3], "complete")


def test_the_app_is_told_to_stop_at_the_message_that_crosses_the_cap() -> None:
    outcome = _drive([6, 5, 4])
    assert outcome.status == 413
    assert outcome.seen == [6]
    assert outcome.ended == "http.disconnect"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "GET"])
def test_the_cumulative_count_does_not_depend_on_the_method(method: str) -> None:
    assert _drive([6, 6], method).status == 413
    assert _drive([5, 5], method).status == 200
