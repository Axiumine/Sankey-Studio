# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``BodyRecorder``: keep everything a client received, to prove a secret never shows up in it.

``record(client)`` hooks the client so that the status line, headers and body of every response
are appended to ``Recording.texts``; ``Recording.leaks(secret)`` returns the entries that contain
the secret. Used with ``caplog`` / ``capfd`` for the "the password is nowhere" checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


@dataclass(slots=True)
class Recording:
    """The responses seen so far, as text (``METHOD path status headers body``)."""

    texts: list[str] = field(default_factory=list)

    def leaks(self, secret: str) -> list[str]:
        """The recorded responses that contain ``secret`` (empty = the secret never came back)."""
        return [text for text in self.texts if secret in text]


def record(client: httpx.Client) -> Recording:
    """Start recording every response that ``client`` receives."""
    recording = Recording()

    def on_response(response: httpx.Response) -> None:
        response.read()
        request = response.request
        headers = "\n".join(f"{name}: {value}" for name, value in response.headers.items())
        line = f"{request.method} {request.url.path} {response.status_code}"
        recording.texts.append(f"{line}\n{headers}\n{response.text}")

    client.event_hooks["response"].append(on_response)
    return recording
