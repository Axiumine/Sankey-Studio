# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.6, the library collections: what drag and drop refuses, ignores and survives.

Refusing places (with their reason), drags that did not start on the page, cards that are not drag
sources, drops that fail on the server, and the parts of a card that stay usable with the mouse
(text selection, a click that wobbles). The moves that work are in ``test_library_drag_drop_ui.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import graph_create, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_b_dnd import DragLibrary
from tests.e2e.support.ui_b_folders import seed_filed_graph, seed_folder

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

MARKS = "[data-dragging], [data-drop], [data-drop-reason]"
TAKEN = "A collection with this name already exists in that place. Choose another name."


@pytest.fixture
def library(page: WatchedPage, live_server: LiveServer) -> DragLibrary:
    return DragLibrary(page, live_server)


# ------------------------------------------------------------------------------ refusing places


def test_the_open_collection_refuses_a_drop_and_says_why(
    library: DragLibrary, api: httpx.Client
) -> None:
    outer, inner = unique_name("Outer"), unique_name("Inner")
    parent = seed_folder(api, outer)
    seed_folder(api, inner, parent["id"])
    library.goto(f"?folder={parent['id']}")
    writes = library.record_writes()
    source, last = library.folder_card(inner), library.crumb(outer)
    transfer = library.begin(source)
    assert library.has_private_data(transfer)
    assert library.over(last, transfer) is False  # not cancelled: the browser shows no-drop
    expect(last).to_have_attribute("data-drop", "denied")
    expect(last).to_have_attribute("data-drop-reason", "already here")
    expect(library.page.locator("#a11y-polite")).to_have_text("Not possible: already here")
    assert library.drop(last, transfer) is True  # a dropped link must never navigate
    expect(library.page.locator(MARKS)).to_have_count(0)
    assert writes == []


def test_a_graph_refuses_the_collection_it_is_in_and_accepts_the_library(
    library: DragLibrary, api: httpx.Client
) -> None:
    home, graph = unique_name("Home"), unique_name("Filed")
    folder = seed_folder(api, home)
    seed_filed_graph(api, graph, folder["id"])
    library.goto(f"?folder={folder['id']}")
    writes = library.record_writes()
    card, last = library.card(graph), library.crumb(home)
    transfer = library.begin(card)
    assert library.over(library.crumb(None), transfer) is True
    expect(library.crumb(None)).to_have_attribute("data-drop", "ok")
    assert library.over(last, transfer) is False
    expect(last).to_have_attribute("data-drop", "denied")
    expect(last).to_have_attribute("data-drop-reason", "already here")
    expect(library.crumb(None)).not_to_have_attribute("data-drop", "ok")
    assert library.drop(last, transfer) is True
    expect(library.page.locator(MARKS)).to_have_count(0)
    assert writes == []


def test_a_collection_refuses_a_drop_on_itself(library: DragLibrary, api: httpx.Client) -> None:
    name = unique_name("Alone")
    seed_folder(api, name)
    library.goto()
    writes = library.record_writes()
    card = library.folder_card(name)
    transfer = library.begin(card)
    assert library.over(card, transfer) is False
    expect(card).to_have_attribute("data-drop", "denied")
    expect(card).to_have_attribute("data-drop-reason", "inside the collection being moved")
    library.finish(card, transfer)
    expect(library.page.locator(MARKS)).to_have_count(0)
    assert writes == []


def test_a_collection_is_refused_a_place_where_its_tree_would_pass_eight_levels(
    library: DragLibrary, api: httpx.Client
) -> None:
    parent_id = None
    for level in range(1, 7):  # the open collection is the sixth level, its cards the seventh
        parent_id = seed_folder(api, unique_name(f"Level{level}"), parent_id)["id"]
    place, tall, flat = (unique_name(word) for word in ("Place", "Tall", "Flat"))
    seed_folder(api, place, parent_id)
    seed_folder(api, unique_name("Below"), seed_folder(api, tall, parent_id)["id"])
    seed_folder(api, flat, parent_id)
    library.goto(f"?folder={parent_id}")
    writes = library.record_writes()
    zone = library.folder_card(place)
    transfer = library.begin(library.folder_card(tall))  # two levels tall: 7 + 2 is one too many
    assert library.over(zone, transfer) is False
    expect(zone).to_have_attribute("data-drop", "denied")
    expect(zone).to_have_attribute("data-drop-reason", "too deep (at most 8 levels)")
    assert library.drop(zone, transfer) is True
    transfer = library.begin(library.folder_card(flat))  # one level tall: 7 + 1 just fits
    assert library.over(zone, transfer) is True
    expect(zone).to_have_attribute("data-drop", "ok")
    library.finish(library.folder_card(flat), transfer)
    expect(library.page.locator(MARKS)).to_have_count(0)
    assert writes == []


# ------------------------------------------------------------------------------ not our drag


@pytest.mark.parametrize("kind", ["text", "file"])
def test_a_drag_that_did_not_start_on_the_page_is_ignored_completely(
    library: DragLibrary, api: httpx.Client, kind: str
) -> None:
    graph, target = unique_name("Graph"), unique_name("Target")
    seed_graph(api, graph)
    seed_folder(api, target)
    library.goto()
    writes = library.record_writes()
    card, zone = library.card(graph), library.folder_card(target)
    foreign = library.foreign(kind)
    assert library.over(zone, foreign) is False
    assert library.drop(zone, foreign) is False  # the browser keeps its own behaviour
    expect(library.page.locator(MARKS)).to_have_count(0)
    ours = library.begin(card)  # a drag of ours is on: another transfer is still not ours
    assert library.over(zone, library.foreign(kind)) is False
    assert library.over(zone, ours) is True
    expect(zone).to_have_attribute("data-drop", "ok")
    library.finish(card, ours)
    expect(library.page.locator(MARKS)).to_have_count(0)
    assert writes == []


def test_search_results_are_not_drag_sources(library: DragLibrary, api: httpx.Client) -> None:
    graph = unique_name("Found")
    seed_graph(api, graph)
    seed_folder(api, unique_name("Target"))
    library.goto(f"?q={graph}")
    card = library.card(graph)
    expect(card).to_be_visible()
    assert card.get_attribute("draggable") is None
    transfer = library.begin(card)
    assert not library.has_private_data(transfer)
    expect(library.page.locator(MARKS)).to_have_count(0)


def test_a_library_without_collections_leaves_a_link_drag_to_the_browser(
    library: DragLibrary, api: httpx.Client
) -> None:
    graph = unique_name("Lonely")
    seed_graph(api, graph)
    library.goto()
    card = library.card(graph)
    assert card.get_attribute("draggable") is None
    transfer = library.begin(card.get_by_test_id("graph-open"))
    assert not library.has_private_data(transfer)
    expect(library.page.locator(MARKS)).to_have_count(0)


# ------------------------------------------------------------------------------ a drag that stops

LEAVE_JS = (
    "(el, dt) => el.dispatchEvent(new DragEvent('dragleave', "
    "{dataTransfer: dt, relatedTarget: document.body, bubbles: true}))"
)


def test_leaving_the_page_clears_the_target_and_losing_the_window_ends_the_drag(
    library: DragLibrary, api: httpx.Client
) -> None:
    moving, target = unique_name("Moving"), unique_name("Target")
    seed_folder(api, moving)
    seed_folder(api, target)
    library.goto()
    writes = library.record_writes()
    card, zone = library.folder_card(moving), library.folder_card(target)
    transfer = library.begin(card)
    assert library.over(zone, transfer) is True
    expect(zone).to_have_attribute("data-drop", "ok")
    zone.evaluate(LEAVE_JS, transfer)  # the pointer went out of the page: the target mark goes
    expect(library.page.locator("[data-drop]")).to_have_count(0)
    expect(card).to_have_attribute("data-dragging", "true")
    assert library.over(zone, transfer) is True  # and it comes back with the pointer
    expect(zone).to_have_attribute("data-drop", "ok")
    library.page.evaluate("() => window.dispatchEvent(new Event('blur'))")
    expect(library.page.locator(MARKS)).to_have_count(0)
    assert library.drop(zone, transfer) is False  # the drag is over: a late drop is not ours
    assert writes == []


# ------------------------------------------------------------------------------ failing drops


def test_a_drop_on_a_collection_deleted_elsewhere_is_reported_and_the_list_reloads(
    library: DragLibrary, api: httpx.Client
) -> None:
    graph, gone, stays = (unique_name(word) for word in ("Graph", "Gone", "Stays"))
    seed_graph(api, graph)
    doomed = seed_folder(api, gone)
    seed_folder(api, stays)
    library.goto()
    card, zone = library.card(graph), library.folder_card(gone)
    transfer = library.begin(card)
    assert library.over(zone, transfer) is True
    assert api.delete(f"/api/v1/folders/{doomed['id']}").status_code == 204
    library.page.allow_http(404, "/api/v1/graphs/move")  # the page learns it from the server
    library.drop(zone, transfer)
    library.expect_toast("That collection no longer exists", "info")
    expect(library.folder_card(gone)).to_have_count(0)
    expect(card).to_be_visible()  # nothing moved


def test_a_name_that_is_taken_in_the_target_is_an_error_toast_and_a_reload(
    library: DragLibrary, api: httpx.Client
) -> None:
    same, holder = unique_name("Same"), unique_name("Holder")
    seed_folder(api, same)
    seed_folder(api, same, seed_folder(api, holder)["id"])
    library.goto()
    library.page.allow_http(409, "/api/v1/folders/")  # the server refuses the name
    library.drag(library.folder_card(same), library.folder_card(holder))
    library.expect_toast(TAKEN, "error")
    expect(library.folder_card(same)).to_have_count(1)  # still at the top level
    expect(library.folder_card(holder)).to_contain_text("0 graphs, 1 collection")


# ------------------------------------------------------------------------------ a mixed pick


def test_graphs_picked_in_a_search_do_not_make_the_open_collection_look_like_home(
    library: DragLibrary, api: httpx.Client
) -> None:
    here, away, home, elsewhere = (unique_name(word) for word in ("Here", "Away", "Home", "Else"))
    open_folder = seed_folder(api, home)
    seed_filed_graph(api, here, open_folder["id"])
    seed_graph(api, away)
    seed_folder(api, elsewhere)
    library.goto(f"?folder={open_folder['id']}")
    library.search(away)
    library.tick(away).check()  # a graph from outside the open collection
    library.search("")
    library.tick(here).check()
    transfer = library.begin(library.card(here))
    assert library.over(library.crumb(home), transfer) is True  # `away` is not in `home` yet
    expect(library.crumb(home)).to_have_attribute("data-drop", "ok")
    library.finish(library.card(here), transfer)


# ------------------------------------------------------------------------------ text and controls


def test_text_and_controls_of_a_card_are_not_drag_handles(
    library: DragLibrary, api: httpx.Client
) -> None:
    name, text = unique_name("Described"), "A description long enough to select with the mouse"
    json_of(api.post("/api/v1/graphs", json=graph_create(name, description=text)), 201)
    seed_folder(api, unique_name("Target"))
    library.goto()
    card = library.card(name)
    expect(card).to_have_attribute("draggable", "true")
    for part, grabbable in (
        (".graph-card-desc", "false"),
        ("[data-testid=compare-select]", "false"),
        ("[data-testid=graph-move]", "false"),
        ("[data-testid=graph-open]", "true"),
    ):
        card.locator(part).hover()
        expect(card).to_have_attribute("draggable", grabbable)
    library.page.mouse.move(1, 1)  # off the page root: the card is a source again
    expect(card).to_have_attribute("draggable", "true")


def test_a_press_on_the_text_selects_it_and_a_click_that_wobbles_still_counts(
    library: DragLibrary, api: httpx.Client
) -> None:
    name, text = unique_name("Described"), "A description long enough to select with the mouse"
    json_of(api.post("/api/v1/graphs", json=graph_create(name, description=text)), 201)
    seed_folder(api, unique_name("Target"))
    library.goto()
    card, mouse = library.card(name), library.page.mouse
    box = card.locator(".graph-card-desc").bounding_box()
    assert box is not None
    mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
    mouse.down()
    mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2, steps=8)
    mouse.up()
    assert library.page.evaluate("() => String(getSelection())")
    expect(library.page.locator(MARKS)).to_have_count(0)  # no drag started
    check = card.get_by_test_id("compare-select")
    spot = check.bounding_box()
    assert spot is not None
    x, y = spot["x"] + spot["width"] / 2, spot["y"] + spot["height"] / 2
    mouse.move(x, y)
    mouse.down()
    mouse.move(x + 6, y, steps=3)  # a few pixels away and back, as a shaky hand does
    mouse.move(x, y, steps=3)
    mouse.up()
    expect(check).to_be_checked()
