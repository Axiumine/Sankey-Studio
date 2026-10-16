# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.6, the library collections: move, delete, search, paging and changes made elsewhere.

Every test has a server of its own (a clean library). The browse and create flows are in
``test_library_folders_ui.py``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import graph_create, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_b_common import PHONE, overflows_horizontally
from tests.e2e.support.ui_b_folders import FolderLibrary, seed_filed_graph, seed_folder

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage


@pytest.fixture
def library(page: WatchedPage, live_server: LiveServer) -> FolderLibrary:
    return FolderLibrary(page, live_server)


# ------------------------------------------------------------------------------ move a collection


def test_a_collection_moves_into_another_and_the_dialog_refuses_impossible_places(
    library: FolderLibrary, api: httpx.Client
) -> None:
    outer, inner, other = (unique_name(word) for word in ("Outer", "Inner", "Other"))
    parent = seed_folder(api, outer)
    seed_folder(api, inner, parent["id"])
    seed_folder(api, other)
    library.goto()
    library.folder_card(outer).get_by_test_id("folder-move").click()
    expect(library.move_option(None)).to_contain_text("already here")
    for blocked in (outer, inner):
        expect(library.move_option(blocked).locator("input")).to_be_disabled()
        expect(library.move_option(blocked)).to_contain_text("inside the collection being moved")
    expect(library.tid("move-confirm")).to_be_disabled()  # nothing is chosen yet
    library.choose_target(other)
    expect(library.move_dialog).to_be_hidden()
    library.expect_toast(f"Moved “{outer}” to “{other}”.", "success")
    expect(library.folder_card(outer)).to_have_count(0)
    expect(library.folder_card(other)).to_contain_text("0 graphs, 1 collection")
    library.open_folder(other)
    expect(library.folder_names).to_have_text([outer])


def test_the_move_dialog_refuses_a_place_that_is_too_deep(
    library: FolderLibrary, api: httpx.Client
) -> None:
    chain: list[dict[str, str]] = []
    for level in range(1, 9):  # eight levels is the most there can be
        parent_id = chain[-1]["id"] if chain else None
        chain.append(seed_folder(api, unique_name(f"Level{level}"), parent_id))
    moving = seed_folder(api, unique_name("Moving"))
    seed_folder(api, unique_name("Below"), moving["id"])  # two levels tall
    library.goto(f"?folder={chain[-1]['id']}")
    expect(library.tid("folder-new")).to_be_hidden()  # a ninth level cannot be made
    library.goto()
    library.folder_card(moving["name"]).get_by_test_id("folder-move").click()
    for index, enabled in ((5, True), (6, False), (7, False)):  # level 6 is the deepest fit
        row = library.move_option(chain[index]["name"])
        expect(row.locator("input")).to_be_enabled(enabled=enabled)
        if not enabled:
            expect(row).to_contain_text("too deep (at most 8 levels)")
    library.page.keyboard.press("Escape")
    expect(library.move_dialog).to_be_hidden()


def test_moving_into_a_place_that_has_the_same_name_keeps_the_dialog_open(
    library: FolderLibrary, api: httpx.Client
) -> None:
    same, target = unique_name("Same"), unique_name("Target")
    seed_folder(api, same, seed_folder(api, target)["id"])
    seed_folder(api, same)
    library.goto()
    library.page.allow_http(409, "/api/v1/folders/")  # the clash is the point of the test
    library.folder_card(same).get_by_test_id("folder-move").click()
    library.choose_target(target)
    expect(library.tid("folder-name-error")).to_contain_text("already exists in that place")
    expect(library.move_dialog).to_be_visible()
    library.page.keyboard.press("Escape")
    expect(library.folder_card(same)).to_be_visible()


# ------------------------------------------------------------------------------ move graphs


def test_one_graph_moves_into_a_collection_and_back_through_its_card(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Target"))
    name, anchor = unique_name("Mover"), unique_name("Anchor")
    seed_graph(api, name)
    seed_graph(api, anchor)
    library.goto()
    library.card(name).get_by_test_id("graph-move").click()
    expect(library.move_option(None)).to_contain_text("already here")
    library.choose_target(folder["name"])
    library.expect_toast(f"Moved “{name}” to “{folder['name']}”.", "success")
    expect(library.folder_card(folder["name"])).to_contain_text("1 graph, 0 collections")
    expect(library.count).to_be_focused()  # its card is gone: the summary line takes the focus
    library.open_folder(folder["name"])
    library.card(name).get_by_test_id("graph-move").click()
    expect(library.move_option(folder["name"])).to_contain_text("already here")
    library.choose_target(None)
    library.expect_toast(f"Moved “{name}” to the library.", "success")
    expect(library.tid("library-folder-empty")).to_be_visible()
    loose = json_of(api.get("/api/v1/graphs", params={"folder": "root"}))["items"]
    assert {item["name"] for item in loose} == {name, anchor}


def test_picked_graphs_move_together_from_the_selection_bar(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Bundle"))
    names = [unique_name("Pick") for _ in range(3)]
    for name in names:
        seed_graph(api, name)
    library.goto()
    library.tick(names[0]).check()
    library.tick(names[1]).check()
    library.move_picked(folder["name"])
    library.expect_toast(f"Moved 2 graphs to “{folder['name']}”.", "success")
    expect(library.names).to_have_count(1)
    expect(library.tid("selection-bar")).to_be_hidden()  # the selection was used up
    expect(library.folder_card(folder["name"])).to_contain_text("2 graphs")
    listing = json_of(api.get("/api/v1/graphs", params={"folder": folder["id"]}))
    assert {item["name"] for item in listing["items"]} == set(names[:2])


# ------------------------------------------------------------------------------ delete


def test_deleting_a_collection_moves_its_graphs_and_collections_up_and_deletes_nothing(
    library: FolderLibrary, api: httpx.Client
) -> None:
    doomed, inner, graph = unique_name("Doomed"), unique_name("Inner"), unique_name("Kept")
    folder = seed_folder(api, doomed)
    seed_folder(api, inner, folder["id"])
    made = seed_filed_graph(api, graph, folder["id"])
    library.goto()
    library.folder_card(doomed).get_by_test_id("folder-delete").click()
    dialog = library.tid("folder-delete-dialog")
    expect(dialog).to_contain_text("1 graph and 1 collection will move up to the library")
    expect(library.tid("confirm-dialog-cancel")).to_be_focused()  # the safe choice
    library.page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(library.folder_card(doomed)).to_be_visible()
    library.folder_card(doomed).get_by_test_id("folder-delete").click()
    library.tid("folder-delete-confirm").click()
    library.expect_toast(f"Deleted the collection “{doomed}”. Its contents moved up.", "success")
    expect(library.folder_card(doomed)).to_have_count(0)
    expect(library.folder_card(inner)).to_be_visible()  # now at the top level
    library.expect_names([graph])
    assert json_of(api.get(f"/api/v1/graphs/{made['id']}"))["folder_id"] is None


# ------------------------------------------------------------------------------ search and paging


def test_a_search_looks_in_every_collection_and_names_where_each_graph_lives(
    library: FolderLibrary, api: httpx.Client
) -> None:
    top, inner = unique_name("Top"), unique_name("Inner")
    folder = seed_folder(api, top)
    deeper = seed_folder(api, inner, folder["id"])
    name = unique_name("Needle")
    seed_filed_graph(api, name, deeper["id"])
    library.goto(f"?folder={folder['id']}")
    expect(library.folder_card(inner)).to_be_visible()
    library.search(name)
    library.expect_names([name])
    chip = library.card(name).get_by_test_id("graph-folder")
    expect(chip).to_have_text(f"{top} / {inner}")
    expect(library.tid("library-scope-note")).to_have_text("Searching all collections.")
    expect(library.breadcrumb).to_be_hidden()
    expect(library.folder_cards).to_have_count(0)
    expect(library.tid("folder-new")).to_be_hidden()
    expect(library.tid("library-export")).to_contain_text("Export results (1)")
    library.search("")
    expect(library.tid("library-scope-note")).to_be_hidden()
    expect(library.folder_card(inner)).to_be_visible()  # back in the open collection
    library.search(name)
    chip.click()
    expect(library.page).to_have_url(re.compile(rf"folder={deeper['id']}"))
    library.expect_ready()
    library.expect_names([name])


def test_paging_and_sorting_stay_inside_the_open_collection(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Many"))
    for number in range(14):
        body = graph_create(f"Chart {number:02d}")
        json_of(api.post("/api/v1/graphs", params={"folder": folder["id"]}, json=body), 201)
    seed_graph(api, unique_name("Outsider"))
    library.goto(f"?folder={folder['id']}")
    expect(library.count).to_contain_text("of 14 graphs")
    library.next_page()
    expect(library.names).to_have_count(2)
    library.sort_by("name-desc")  # back on page 1, newest letters first
    expect(library.names.first).to_have_text("Chart 13")
    expect(library.count).to_contain_text("of 14 graphs")
    library.next_page()
    expect(library.names).to_have_text(["Chart 01", "Chart 00"])
    library.page.reload()
    library.expect_ready()
    expect(library.names).to_have_text(["Chart 01", "Chart 00"])
    assert f"folder={folder['id']}" in library.page.url


# ------------------------------------------------------------------------------ changes elsewhere


def test_a_collection_deleted_elsewhere_is_reported_and_the_list_reloads(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Ghost"))
    library.goto()
    expect(library.folder_card(folder["name"])).to_be_visible()
    assert api.delete(f"/api/v1/folders/{folder['id']}").status_code == 204
    library.page.allow_http(404, "/api/v1/folders/")
    library.folder_card(folder["name"]).get_by_test_id("folder-rename").click()
    library.fill_name(unique_name("Late"))
    library.expect_toast("That collection no longer exists, so the list was reloaded.", "info")
    expect(library.name_dialog).to_be_hidden()
    expect(library.folder_cards).to_have_count(0)


def test_a_collection_changed_elsewhere_asks_to_try_again_with_the_new_state(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Stale"))
    library.goto()
    elsewhere = unique_name("Elsewhere")
    body = {"name": elsewhere, "parent_id": None, "revision": folder["revision"]}
    json_of(api.put(f"/api/v1/folders/{folder['id']}", json=body))
    library.page.allow_http(409, "/api/v1/folders/")
    library.folder_card(folder["name"]).get_by_test_id("folder-rename").click()
    library.fill_name(unique_name("Mine"))
    library.expect_toast("That collection was changed elsewhere", "info")
    expect(library.folder_card(elsewhere)).to_be_visible()  # the reloaded list has the new name
    expect(library.name_dialog).to_be_hidden()


def test_moving_into_a_collection_that_vanished_moves_nothing(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Vanishing"))
    name = unique_name("Stays")
    graph = seed_graph(api, name)
    library.goto()
    library.card(name).get_by_test_id("graph-move").click()
    assert api.delete(f"/api/v1/folders/{folder['id']}").status_code == 204
    library.page.allow_http(404, "/api/v1/graphs/move")
    library.choose_target(folder["name"])
    library.expect_toast("That collection no longer exists, so the list was reloaded.", "info")
    expect(library.move_dialog).to_be_hidden()
    library.expect_names([name])
    assert json_of(api.get(f"/api/v1/graphs/{graph['id']}"))["folder_id"] is None


# ------------------------------------------------------------------------------ phone


@pytest.mark.parametrize("viewport", [PHONE])
def test_the_collection_view_fits_a_phone(library: FolderLibrary, api: httpx.Client) -> None:
    long_name = ("Long collection name " * 5)[:100].strip()
    folder = seed_folder(api, long_name)
    seed_folder(api, unique_name("Child"), folder["id"])
    library.goto(f"?folder={folder['id']}")
    expect(library.breadcrumb).to_be_visible()
    assert not overflows_horizontally(library.page)
    library.tid("folder-new").click()
    expect(library.name_dialog).to_be_visible()
    assert not overflows_horizontally(library.page)
