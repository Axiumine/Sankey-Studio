# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""HTTP clients for the live server, plus multipart and "fetch from the page" helpers.

Three ``httpx.Client`` flavours (the ``api`` / ``foreign`` / ``bare`` fixtures), all bound to one
``LiveServer`` with ``base_url=server.url``, no redirects followed, no proxy from the environment:

* ``make_client(server)``                      - sends ``Origin: <server.url>``, what a browser
  sends from one of the app's own pages, so state-changing calls pass the CSRF guard.
* ``make_client(server, origin="http://evil.example")`` - a hostile origin (must get 403 on writes).
* ``make_client(server, origin=None)``         - no ``Origin`` / ``Sec-Fetch-Site`` at all: curl.
  Only ``application/json`` bodies pass the guard then; multipart and bodiless DELETE are 403.

``seed_graph(client, name, draft=None, *, tags=())`` creates a saved graph (``POST /graphs``, 201)
and returns its ``GraphDefinition`` (``["id"]``, ``["revision"]``, ...); the draft defaults to the
budget sample. ``upload_source`` posts a file to ``POST /api/v1/sources/files`` as multipart
(field ``file``, optional ``overwrite``), ``post_multipart`` is the raw form for odd names/fields.
``json_of(response, status)`` asserts the status (the body is part of the failure message) and
returns the parsed JSON. ``fetch_json(page, method, path, body)`` does the same from inside the
browser, so the request carries the browser's own same-origin headers (docs/api.md, section 2).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import httpx

from tests.e2e.support.builders import graph_create

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from playwright.sync_api import Page

    from tests.e2e.support.server import LiveServer

FOREIGN_ORIGIN: Final = "http://evil.example"
CLIENT_TIMEOUT_S: Final = 30.0
UPLOAD_PATH: Final = "/api/v1/sources/files"
#: ``make_client(origin=OWN_ORIGIN)``: the default, "send the server's own origin".
OWN_ORIGIN: Final = "own"
CONTENT_TYPES: Final = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".ndjson": "application/x-ndjson",
}
DEFAULT_CONTENT_TYPE: Final = "text/plain"

#: A multipart part: ``(file name, bytes, content type)``.
Part = tuple[str, bytes, str]


def make_client(server: LiveServer, *, origin: str | None = OWN_ORIGIN) -> httpx.Client:
    """An ``httpx.Client`` for ``server``; see the module doc for ``origin``.

    ``origin`` omitted (``OWN_ORIGIN``) means the server's own origin, another string is sent as
    the ``Origin`` header, ``None`` sends none. Close the client (the fixtures do).
    """
    headers: dict[str, str] = {"Accept": "application/json"}
    if origin == OWN_ORIGIN:
        headers["Origin"] = server.url
    elif origin is not None:
        headers["Origin"] = origin
    return httpx.Client(
        base_url=server.url,
        headers=headers,
        timeout=CLIENT_TIMEOUT_S,
        follow_redirects=False,
        trust_env=False,
    )


def json_of(response: httpx.Response, status: int = 200) -> Any:
    """Assert ``response.status_code == status`` and return the parsed JSON (``None`` if empty)."""
    request = response.request
    assert response.status_code == status, (
        f"{request.method} {request.url.path}: expected {status}, got {response.status_code}: "
        f"{response.text[:500]}"
    )
    return response.json() if response.content else None


def content_type_of(name: str) -> str:
    """The upload content type for a file name (by suffix; ``text/plain`` otherwise)."""
    return CONTENT_TYPES.get(PurePosixPath(name).suffix.lower(), DEFAULT_CONTENT_TYPE)


def post_multipart(
    client: httpx.Client,
    path: str,
    parts: Mapping[str, Part],
    fields: Mapping[str, str] | None = None,
) -> httpx.Response:
    """POST a multipart form: file ``parts`` by field name and plain ``fields``."""
    return client.post(path, files=dict(parts), data=dict(fields or {}))


def upload_source(
    client: httpx.Client, name: str, content: str | bytes, *, overwrite: bool = False
) -> httpx.Response:
    """Upload ``name`` to the managed sources directory (multipart, field ``file``)."""
    data = content.encode() if isinstance(content, str) else content
    fields = {"overwrite": "true"} if overwrite else None
    part: Part = (name, data, content_type_of(name))
    return post_multipart(client, UPLOAD_PATH, {"file": part}, fields)


def seed_graph(
    client: httpx.Client,
    name: str,
    draft: Mapping[str, Any] | None = None,
    *,
    tags: Sequence[str] = (),
) -> dict[str, Any]:
    """Create a saved graph through the API and return it (asserts the 201)."""
    body = graph_create(name, draft, tags=tags)
    return dict(json_of(client.post("/api/v1/graphs", json=body), 201))


class FetchResult(NamedTuple):
    """What ``fetch_json`` returns: the status, the parsed body (or ``None``) and a text excerpt."""

    status: int
    json: Any
    text: str


_FETCH_JS = """async ([method, path, body]) => {
    const init = {method, headers: {}};
    if (body !== null) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(body);
    }
    const response = await fetch(path, init);
    const text = await response.text();
    let json = null;
    try { json = JSON.parse(text); } catch (error) { json = null; }
    return {status: response.status, json, text: text.slice(0, 300)};
}"""


def fetch_json(page: Page, method: str, path: str, body: Any = None) -> FetchResult:
    """``fetch(path)`` inside ``page`` (same-origin headers of the browser) and return the result.

    The page must already be on an app URL (not ``about:blank``). A 4xx/5xx the call provokes is
    still a "failed response" for the page watcher: allow it with ``page.allow_http`` when intended.
    """
    result = page.evaluate(_FETCH_JS, [method, path, body])
    return FetchResult(result["status"], result["json"], result["text"])
