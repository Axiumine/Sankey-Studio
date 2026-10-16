# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``raw_request``: one HTTP request with an exact request target, for URLs a client would tidy.

``httpx`` (like a browser) removes ``..`` segments from the URL before it sends it, so it can
never deliver ``/api/v1/sources/files/../x.csv``. The traversal tests need that exact line to reach
the server, so they use ``http.client``, which sends the target as given. The request carries the
server's own ``Origin`` (the CSRF guard lets a bodiless DELETE through only with it).
"""

from __future__ import annotations

import http.client
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from tests.e2e.support.server import LiveServer

RAW_TIMEOUT_S: Final = 20.0


@dataclass(frozen=True, slots=True)
class RawResponse:
    """The status line, headers (lower-case names) and decoded body of a raw request."""

    status: int
    headers: Mapping[str, str]
    text: str

    def json(self) -> Any:
        return json.loads(self.text)

    @property
    def error_code(self) -> str:
        """``error.code`` of the JSON envelope (an assertion error when the body is no envelope)."""
        envelope = self.json()
        assert isinstance(envelope, dict), self.text
        return str(envelope["error"]["code"])


def raw_request(
    server: LiveServer,
    method: str,
    target: str,
    headers: Mapping[str, str] | None = None,
) -> RawResponse:
    """Send ``method target`` to ``server`` exactly as written (no URL normalisation)."""
    connection = http.client.HTTPConnection(server.host, server.port, timeout=RAW_TIMEOUT_S)
    try:
        connection.request(method, target, headers={"Origin": server.url, **(headers or {})})
        response = connection.getresponse()
        text = response.read().decode("utf-8", errors="replace")
        return RawResponse(response.status, {k.lower(): v for k, v in response.getheaders()}, text)
    finally:
        connection.close()


BOUNDARY: Final = "e2eBoundary7f3a"
MULTIPART_TYPE: Final = f"multipart/form-data; boundary={BOUNDARY}"


def multipart_file(filename: bytes, content: bytes = b"a,b,1\n") -> bytes:
    """A multipart body with one ``file`` part whose ``filename`` is EXACTLY these bytes.

    ``httpx`` (like a browser) percent-encodes control characters in a file name, so a NUL or a
    newline can only reach the server through a hand-written body. Send it with
    ``content=multipart_file(...)`` and ``headers={"Content-Type": MULTIPART_TYPE}``.
    """
    head = f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="'.encode()
    part = b'"\r\nContent-Type: text/csv\r\n\r\n'
    return head + filename + part + content + f"\r\n--{BOUNDARY}--\r\n".encode()
