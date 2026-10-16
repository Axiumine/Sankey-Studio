# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Folders on the graph routes: ``?folder=`` listing and creation, duplicate, PUT, move."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import FolderCreate, GraphCreate
from sankey_studio.web.routers import folders, graphs
from tests.web.test_routes_graphs_support import (
    API,
    MALFORMED_IDS,
    PLAIN,
    UNKNOWN_ID,
    code,
    graph_json,
    put_graph,
    save,
)

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

GRAPHS = f"{API}/graphs"
MOVE = f"{GRAPHS}/move"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router, folders.router])


def folder(web: WebApp, name: str, parent: str | None = None) -> str:
    return web.services.folders().create_folder(FolderCreate(name=name, parent_id=parent)).id


def listing(web: WebApp, **params: Any) -> dict[str, Any]:
    response = web.client.get(GRAPHS, params=params)
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()
    return page


def names(page: dict[str, Any]) -> list[str]:
    return [item["name"] for item in page["items"]]


# --------------------------------------------------------------------------- GET /graphs?folder=


def test_a_plain_listing_is_the_whole_library_whatever_the_folders(web: WebApp) -> None:
    inside = folder(web, "F")
    put_graph(web, 1, "Loose")
    body = GraphCreate.model_validate(graph_json("In", *PLAIN))
    web.services.graphs().create(body, folder_id=inside)
    assert sorted(names(listing(web))) == ["In", "Loose"]


def test_root_lists_the_graphs_outside_every_folder_newest_first(web: WebApp) -> None:
    inside = folder(web, "F")
    first, second = put_graph(web, 1, "Older"), put_graph(web, 2, "Newer")
    web.services.folders().move_graphs([put_graph(web, 3, "Hidden")], inside)
    page = listing(web, folder="root")
    assert (names(page), page["total"], page["limit"], page["offset"]) == (
        ["Newer", "Older"],
        2,
        200,
        0,
    )
    assert [item["id"] for item in page["items"]] == [second, first]
    assert page["items"][0]["folder_id"] is None


def test_a_folder_id_lists_the_graphs_directly_in_it(web: WebApp) -> None:
    outer, inner = folder(web, "Outer"), None
    inner = folder(web, "Inner", outer)
    a, b, c = (put_graph(web, n, f"g{n}") for n in (1, 2, 3))
    web.services.folders().move_graphs([a, b], outer)
    web.services.folders().move_graphs([c], inner)
    in_outer, in_inner = listing(web, folder=outer), listing(web, folder=inner)
    assert (names(in_outer), in_outer["total"]) == (["g2", "g1"], 2)
    assert (names(in_inner), in_inner["total"]) == (["g3"], 1)
    assert in_inner["items"][0]["folder_id"] == inner


def test_an_unknown_folder_is_an_empty_page(web: WebApp) -> None:
    put_graph(web, 1, "g")
    assert listing(web, folder=UNKNOWN_ID) == {"items": [], "total": 0, "limit": 200, "offset": 0}


def test_a_graph_in_a_folder_that_is_gone_reads_as_top_level(web: WebApp) -> None:
    gone = folder(web, "Gone")
    graph = put_graph(web, 1, "g")
    web.services.folders().move_graphs([graph], gone)
    web.services.folders().delete_folder(gone)
    assert names(listing(web, folder="root")) == ["g"]


def test_a_folder_page_obeys_limit_and_offset(web: WebApp) -> None:
    inside = folder(web, "F")
    ids = [put_graph(web, n, f"g{n}") for n in (1, 2, 3, 4, 5)]
    web.services.folders().move_graphs(ids, inside)
    page = listing(web, folder=inside, limit=2, offset=1)
    assert (names(page), page["total"], page["limit"], page["offset"]) == (["g4", "g3"], 5, 2, 1)
    assert names(listing(web, folder=inside, limit=2, offset=4)) == ["g1"]
    assert names(listing(web, folder=inside, offset=5)) == []


@pytest.mark.parametrize("value", ["", "x", "ROOT", "root1", *MALFORMED_IDS, "A" * 32])
def test_a_folder_that_is_neither_root_nor_an_id_is_a_422(web: WebApp, value: str) -> None:
    response = web.client.get(GRAPHS, params={"folder": value})
    assert (response.status_code, code(response)) == (422, "validation_error")


@pytest.mark.parametrize("search", [{"q": "x"}, {"tag": "t"}, {"q": "x", "tag": "t"}])
@pytest.mark.parametrize("scope", ["root", UNKNOWN_ID])
def test_a_folder_cannot_be_combined_with_a_search(
    web: WebApp, scope: str, search: dict[str, str]
) -> None:
    response = web.client.get(GRAPHS, params={"folder": scope, **search})
    assert (response.status_code, code(response)) == (422, "validation_error")
    assert "folder cannot be combined with q or tag" in response.text


def test_a_blank_search_is_no_search_so_it_can_share_the_query_with_a_folder(web: WebApp) -> None:
    put_graph(web, 1, "g")
    assert names(listing(web, folder="root", q="", tag="")) == ["g"]


# --------------------------------------------------------------------------- POST /graphs?folder=


def test_a_graph_is_saved_in_the_folder_the_query_names(web: WebApp) -> None:
    inside = folder(web, "F")
    response = web.client.post(GRAPHS, params={"folder": inside}, json=graph_json("New", *PLAIN))
    assert response.status_code == 201
    created = response.json()
    assert created["folder_id"] == inside
    assert web.services.graphs().get(created["id"]).folder_id == inside
    assert names(listing(web, folder=inside)) == ["New"]


def test_without_a_folder_the_graph_is_saved_at_the_top_level(web: WebApp) -> None:
    created = web.client.post(GRAPHS, json=graph_json("New", *PLAIN)).json()
    assert created["folder_id"] is None


def test_an_unknown_folder_is_a_404_and_nothing_is_stored(web: WebApp) -> None:
    response = web.client.post(GRAPHS, params={"folder": UNKNOWN_ID}, json=graph_json("N", *PLAIN))
    assert (response.status_code, code(response)) == (404, "not_found")
    assert response.json()["error"]["message"] == "Folder not found"
    assert web.services.graphs().count() == 0


@pytest.mark.parametrize("value", ["root", "short", "A" * 32, ""])
def test_a_malformed_folder_in_the_query_is_a_422_and_nothing_is_stored(
    web: WebApp, value: str
) -> None:
    response = web.client.post(GRAPHS, params={"folder": value}, json=graph_json("N", *PLAIN))
    assert (response.status_code, code(response)) == (422, "validation_error")
    assert web.services.graphs().count() == 0


def test_an_unknown_query_parameter_on_create_is_a_422(web: WebApp) -> None:
    response = web.client.post(GRAPHS, params={"bogus": "1"}, json=graph_json("N", *PLAIN))
    assert (response.status_code, code(response)) == (422, "validation_error")


# --------------------------------------------------------------------------- duplicate and PUT


def test_a_duplicate_sits_next_to_its_original(web: WebApp) -> None:
    inside = folder(web, "F")
    original = save(web, "Orig", *PLAIN)
    web.services.folders().move_graphs([original.id], inside)
    copy = web.client.post(f"{GRAPHS}/{original.id}/duplicate").json()
    assert (copy["name"], copy["folder_id"]) == ("Orig (copy)", inside)
    assert sorted(names(listing(web, folder=inside))) == ["Orig", "Orig (copy)"]


def test_a_duplicate_of_a_top_level_graph_is_top_level(web: WebApp) -> None:
    original = save(web, "Orig", *PLAIN)
    assert web.client.post(f"{GRAPHS}/{original.id}/duplicate").json()["folder_id"] is None


def test_a_put_keeps_the_folder_and_cannot_change_it(web: WebApp) -> None:
    inside, other = folder(web, "A"), folder(web, "B")
    stored = save(web, "g", *PLAIN)
    web.services.folders().move_graphs([stored.id], inside)
    body = {**graph_json("renamed", *PLAIN), "revision": 1}
    updated = web.client.put(f"{GRAPHS}/{stored.id}", json=body)
    assert (updated.status_code, updated.json()["folder_id"]) == (200, inside)
    sneaky = web.client.put(
        f"{GRAPHS}/{stored.id}", json={**body, "revision": 2, "folder_id": other}
    )
    assert (sneaky.status_code, code(sneaky)) == (422, "validation_error")
    assert web.services.graphs().get(stored.id).folder_id == inside


# --------------------------------------------------------------------------- POST /graphs/move


def test_a_move_puts_the_graphs_in_the_folder_and_reports_them(web: WebApp) -> None:
    target = folder(web, "F")
    one, two = put_graph(web, 1, "one"), put_graph(web, 2, "two")
    response = web.client.post(MOVE, json={"ids": [one, two], "folder_id": target})
    assert (response.status_code, response.json()) == (200, {"moved": 2, "missing": []})
    assert sorted(names(listing(web, folder=target))) == ["one", "two"]
    assert names(listing(web, folder="root")) == []


def test_a_move_to_null_goes_to_the_top_level(web: WebApp) -> None:
    target = folder(web, "F")
    graph = put_graph(web, 1, "g")
    web.services.folders().move_graphs([graph], target)
    response = web.client.post(MOVE, json={"ids": [graph], "folder_id": None})
    assert response.json() == {"moved": 1, "missing": []}
    assert names(listing(web, folder="root")) == ["g"]


def test_graphs_that_do_not_exist_are_listed_not_an_error(web: WebApp) -> None:
    target = folder(web, "F")
    real = put_graph(web, 1, "g")
    response = web.client.post(MOVE, json={"ids": [UNKNOWN_ID, real], "folder_id": target})
    assert (response.status_code, response.json()) == (200, {"moved": 1, "missing": [UNKNOWN_ID]})


def test_an_unknown_target_is_a_404_and_nothing_moves(web: WebApp) -> None:
    graph = put_graph(web, 1, "g")
    response = web.client.post(MOVE, json={"ids": [graph], "folder_id": UNKNOWN_ID})
    assert (response.status_code, code(response)) == (404, "not_found")
    assert web.services.graphs().get(graph).folder_id is None


def test_a_move_changes_neither_the_revision_nor_the_update_time(web: WebApp) -> None:
    target = folder(web, "F")
    graph = put_graph(web, 1, "g")
    before = web.services.graphs().get(graph)
    web.client.post(MOVE, json={"ids": [graph], "folder_id": target})
    after = web.services.graphs().get(graph)
    assert (after.revision, after.updated_at) == (before.revision, before.updated_at)
    assert after.folder_id == target


def test_the_static_move_route_is_not_read_as_a_graph_id(web: WebApp) -> None:
    body = {**graph_json("g", *PLAIN), "revision": 1}
    assert web.client.get(f"{GRAPHS}/move").status_code == 404  # an unknown id, not a method error
    assert web.client.put(f"{GRAPHS}/move", json=body).status_code == 404
    assert web.client.post(MOVE, json={"ids": [UNKNOWN_ID], "folder_id": None}).status_code == 200
