# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""GET /graphs/export measures and serves UTF-8, like POST /graphs/import measures it.

A character outside the BMP is four bytes of UTF-8 but twelve of ``json.dumps`` with its default
``ensure_ascii`` (two ``\\uXXXX`` escapes): a graph the library accepted could not be exported.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import pytest

from sankey_studio.web.routers import graphs
from sankey_studio.web.security import IMPORT_BODY_BYTES, JSON_BODY_BYTES
from tests.web.test_routes_graphs_support import API, save

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

CREATE: Final = f"{API}/graphs"
EXPORT: Final = f"{API}/graphs/export"
IMPORT: Final = f"{API}/graphs/import"
JSON_HEADERS: Final = {"Content-Type": "application/json"}
EMOJI: Final = "\U0001f600"
#: Emoji of one graph: 8,000,000 bytes of UTF-8, 24,000,000 once escaped as ``\\uXXXX`` pairs.
EMOJI_COUNT: Final = 2_000_000
NAME: Final = "Café 日本語 \U0001f600"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


def text_graph(name: str, content: str) -> bytes:
    """The UTF-8 JSON body of ``POST /graphs`` for an inline text source (no ``\\u`` escapes)."""
    source = {"type": "text", "origin": "inline", "format": "csv", "content": content}
    return json.dumps({"name": name, "source": source}, ensure_ascii=False).encode()


def test_text_outside_the_ascii_range_is_served_as_utf8_not_as_escapes(web: WebApp) -> None:
    stored = save(web, NAME, ("ü", "\U0001f600", 1.0, None), tags=["été"])
    response = web.client.get(f"{EXPORT}?ids={stored.id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"  # JSON is UTF-8 by definition
    assert "\\u" not in response.content.decode("utf-8")
    for text in (NAME, "ü", EMOJI, "été"):
        assert text.encode("utf-8") in response.content
    graph = json.loads(response.content)["graphs"][0]
    assert graph["name"] == NAME
    assert graph["tags"] == ["été"]
    assert graph["source"]["links"][0]["source"] == "ü"


def test_an_exported_graph_with_such_text_imports_again(web: WebApp) -> None:
    stored = save(web, NAME, ("ü", "\U0001f600", 1.0, None), description="☃ snow")
    exported = web.client.get(f"{EXPORT}?ids={stored.id}").content
    report = web.client.post(IMPORT, content=exported, headers=JSON_HEADERS).json()
    assert (report["imported"], report["failed"]) == (1, 0)
    copy = web.services.graphs().get(report["ids"][0])
    assert (copy.name, copy.description) == (NAME, "☃ snow")
    assert copy.source == stored.source


def test_a_graph_the_library_accepts_at_8_million_bytes_of_emoji_exports_and_imports(
    web: WebApp,
) -> None:
    body = text_graph("Emoji", EMOJI * EMOJI_COUNT)
    assert 8_000_000 < len(body) < JSON_BODY_BYTES  # accepted, but 2 x the text in 4-byte emoji
    created = web.client.post(CREATE, content=body, headers=JSON_HEADERS)
    assert created.status_code == 201
    exported = web.client.get(f"{EXPORT}?ids={created.json()['id']}")
    assert exported.status_code == 200
    assert len(body) < len(exported.content) < IMPORT_BODY_BYTES  # 4 bytes an emoji, not 12
    report = web.client.post(IMPORT, content=exported.content, headers=JSON_HEADERS)
    assert report.status_code == 200
    assert (report.json()["imported"], report.json()["failed"]) == (1, 0)
    (copy_id,) = report.json()["ids"]
    copy = web.client.get(f"{CREATE}/{copy_id}").json()
    assert copy["source"]["content"] == EMOJI * EMOJI_COUNT
    assert copy["name"] == "Emoji"
