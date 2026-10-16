# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""A graph called ``<script>alert(1)</script>``: escaped in every page, embedded via tojson only."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.web.test_pages_support import DATA_ID, JSON_TYPE, Page, parse
from tests.web.test_routes_graphs_support import API, PLAIN, graph_json

if TYPE_CHECKING:
    from tests.web.conftest import WebApp

XSS: Final = "<script>alert(1)</script>"
BREAKOUT: Final = '"><img src=x onerror=alert(2)>'
ESCAPED_NAME: Final = "&lt;script&gt;alert(1)&lt;/script&gt;"
#: Indexes into ``pages_of``: the pages that show a graph (the others cannot contain its name).
GRAPH_PAGES = pytest.mark.parametrize(
    "index", [0, 2, 3, 4], ids=["library", "viewer", "edit", "compare"]
)


@pytest.fixture
def hostile(web: WebApp) -> str:
    """The id of a graph whose name, description and tag are all markup."""
    body = graph_json(XSS, *PLAIN, description=BREAKOUT, tags=[BREAKOUT])
    created = web.client.post(f"{API}/graphs", json=body)
    assert created.status_code == 201
    return str(created.json()["id"])


def graph_of(data: dict[str, Any]) -> dict[str, Any]:
    """The one graph a page embeds: the first of a list page, or the page's own graph."""
    graph: dict[str, Any] = data["graphs"][0] if "graphs" in data else data["graph"]
    return graph


def pages_of(graph_id: str) -> list[str]:
    return [
        "/",
        "/graphs/new",
        f"/graphs/{graph_id}",
        f"/graphs/{graph_id}/edit",
        f"/compare?ids={graph_id}",
        "/settings",
    ]


def test_the_hostile_graph_was_stored_verbatim(web: WebApp, hostile: str) -> None:
    stored = web.client.get(f"{API}/graphs/{hostile}").json()
    assert (stored["name"], stored["description"], stored["tags"]) == (XSS, BREAKOUT, [BREAKOUT])


def test_no_page_contains_the_raw_payload(web: WebApp, hostile: str) -> None:
    for path in pages_of(hostile):
        html = web.client.get(path).text
        assert XSS not in html, path
        assert BREAKOUT not in html, path
        assert "<img" not in html, path
        assert "alert(1)</script>" not in html, path


def shape(page: Page) -> tuple[list[str], list[str]]:
    """The tags and attribute names of a page: its markup, whatever the text in it says."""
    return page.tags, [name for name, _ in page.attrs]


def test_hostile_text_adds_no_tag_and_no_attribute(web: WebApp, hostile: str) -> None:
    hostile_pages = [parse(web.client.get(path)) for path in pages_of(hostile)]
    benign = {**graph_json("Quarterly", *PLAIN, description="Plain", tags=["plain"]), "revision": 1}
    assert web.client.put(f"{API}/graphs/{hostile}", json=benign).status_code == 200
    benign_pages = [parse(web.client.get(path)) for path in pages_of(hostile)]
    for path, before, after in zip(pages_of(hostile), hostile_pages, benign_pages, strict=True):
        assert shape(before) == shape(after), path
        assert all(not name.startswith("on") for name in shape(before)[1]), path


def test_every_script_is_a_src_file_or_the_one_json_data_block(web: WebApp, hostile: str) -> None:
    for path in pages_of(hostile):
        scripts = parse(web.client.get(path)).scripts
        data = [s for s in scripts if s.attrs.get("id") == DATA_ID]
        assert [s.attrs.get("type") for s in data] == [JSON_TYPE], path
        for script in scripts:
            is_json = script.attrs.get("type") == JSON_TYPE
            assert is_json or ("src" in script.attrs and script.text.strip() == ""), path


@GRAPH_PAGES
def test_the_name_is_html_escaped_in_the_text_of_the_pages_that_show_it(
    web: WebApp, hostile: str, index: int
) -> None:
    html = web.client.get(pages_of(hostile)[index]).text
    assert ESCAPED_NAME in html


def test_the_title_and_heading_of_the_viewer_and_editor_are_escaped(
    web: WebApp, hostile: str
) -> None:
    viewer = web.client.get(f"/graphs/{hostile}").text
    editor = web.client.get(f"/graphs/{hostile}/edit").text
    assert f"<title>{ESCAPED_NAME} - Sankey Studio</title>" in viewer
    assert f"<h1>{ESCAPED_NAME}</h1>" in viewer
    assert f"<h1>Edit {ESCAPED_NAME}</h1>" in editor


@GRAPH_PAGES
def test_the_data_block_is_tojson_with_no_raw_markup_characters(
    web: WebApp, hostile: str, index: int
) -> None:
    page = parse(web.client.get(pages_of(hostile)[index]))
    (block,) = [s for s in page.scripts if s.attrs.get("id") == DATA_ID]
    for raw in "<>&'":
        assert raw not in block.text
    assert "\\u003cscript\\u003ealert(1)\\u003c/script\\u003e" in block.text
    graph = graph_of(page.data())
    assert (graph["name"], graph["description"], graph["tags"]) == (XSS, BREAKOUT, [BREAKOUT])


@pytest.mark.usefixtures("hostile")
def test_the_pages_without_a_graph_embed_none_of_its_text(web: WebApp) -> None:
    for path in ("/graphs/new", "/settings"):
        assert XSS not in web.client.get(path).text
        assert BREAKOUT not in web.client.get(path).text
    assert parse(web.client.get("/graphs/new")).data()["graph"] is None
    assert "graph" not in parse(web.client.get("/settings")).data()


@pytest.mark.parametrize(
    "path",
    ["/graphs/<img src=x onerror=alert(1)>", "/graphs/<script>alert(1)<%2Fscript>/edit"],
)
def test_a_hostile_id_in_the_path_is_not_echoed(web: WebApp, path: str) -> None:
    response = web.client.get(path)
    assert response.status_code == 404
    assert "<img" not in response.text
    assert "alert" not in response.text


@pytest.mark.parametrize("ids", ["<img src=x onerror=alert(1)>", f"{'a' * 32},<script>alert(1)"])
def test_a_hostile_compare_id_is_not_echoed(web: WebApp, ids: str) -> None:
    response = web.client.get("/compare", params={"ids": ids})
    assert response.status_code == 422
    assert "alert" not in response.text
    assert "<img" not in response.text
