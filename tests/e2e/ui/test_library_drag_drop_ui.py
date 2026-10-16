# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.6, the library collections: drag and drop of graphs and collections.

The same two moves as the Move dialog, with the pointer: a graph (or the picked graphs) onto a
collection card or a crumb, a collection onto another collection card or a crumb. The refusing
places, the foreign drags and the failing drops are in ``test_library_drag_drop_edges_ui.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.ui_b_dnd import DragLibrary
from tests.e2e.support.ui_b_folders import seed_filed_graph, seed_folder

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage


@pytest.fixture
def library(page: WatchedPage, live_server: LiveServer) -> DragLibrary:
    return DragLibrary(page, live_server)


def test_a_graph_dragged_onto_a_collection_card_moves_into_it(
    library: DragLibrary, api: httpx.Client
) -> None:
    graph, target = unique_name("Dragged"), unique_name("Target")
    seed_graph(api, graph)
    seed_graph(api, unique_name("Stays"))  # a non-empty list keeps the summary line
    seed_folder(api, target)
    library.goto()
    writes = library.record_writes()
    source = library.card(graph)
    expect(source).to_have_attribute("draggable", "true")
    library.drag(source, library.folder_card(target), release=False)
    expect(source).to_have_attribute("data-dragging", "true")
    library.release()
    library.expect_toast(f"Moved “{graph}” to “{target}”.", "success")
    expect(library.card(graph)).to_have_count(0)
    expect(library.folder_card(target)).to_contain_text("1 graph, 0 collections")
    assert [w.split(" ")[0] for w in writes] == ["POST"]
    assert writes[0].endswith("/api/v1/graphs/move")
    expect(library.count).to_be_focused()


def test_a_collection_dragged_onto_a_card_and_out_through_a_crumb(
    library: DragLibrary, api: httpx.Client
) -> None:
    moving, target = unique_name("Moving"), unique_name("Target")
    seed_folder(api, moving)
    seed_folder(api, target)
    library.goto()
    library.drag(library.folder_card(moving), library.folder_card(target))
    library.expect_toast(f"Moved “{moving}” to “{target}”.", "success")
    expect(library.folder_card(moving)).to_have_count(0)
    library.open_folder(target)
    library.drag(library.folder_card(moving), library.crumb(None))
    library.expect_toast(f"Moved “{moving}” to the library.", "success")
    expect(library.folder_card(moving)).to_have_count(0)
    library.crumb(None).click()
    expect(library.folder_card(moving)).to_be_visible()


def test_a_graph_dragged_out_of_the_open_collection_lands_on_a_crumb(
    library: DragLibrary, api: httpx.Client
) -> None:
    outer, inner, graph = (unique_name(word) for word in ("Outer", "Inner", "Filed"))
    parent = seed_folder(api, outer)
    child = seed_folder(api, inner, parent["id"])
    seed_filed_graph(api, graph, child["id"])
    library.goto(f"?folder={child['id']}")
    library.drag(library.card(graph), library.crumb(outer))
    library.expect_toast(f"Moved “{graph}” to “{outer}”.", "success")
    expect(library.card(graph)).to_have_count(0)


def test_a_graph_dragged_out_of_a_collection_lands_on_the_library_crumb(
    library: DragLibrary, api: httpx.Client
) -> None:
    home, graph = unique_name("Home"), unique_name("Filed")
    folder = seed_folder(api, home)
    seed_filed_graph(api, graph, folder["id"])
    library.goto(f"?folder={folder['id']}")
    library.drag(library.card(graph), library.crumb(None))
    library.expect_toast(f"Moved “{graph}” to the library.", "success")
    expect(library.card(graph)).to_have_count(0)
    library.crumb(None).click()
    expect(library.card(graph)).to_be_visible()


def test_a_picked_graph_carries_every_picked_graph_in_one_request(
    library: DragLibrary, api: httpx.Client
) -> None:
    first, second, other, target = (unique_name(word) for word in ("One", "Two", "Other", "Target"))
    for name in (first, second, other):
        seed_graph(api, name)
    seed_folder(api, target)
    library.goto()
    library.tick(first).check()
    library.tick(second).check()
    writes = library.record_writes()
    library.drag(library.card(second), library.folder_card(target))
    library.expect_toast(f"Moved 2 graphs to “{target}”.", "success")
    expect(library.card(first)).to_have_count(0)
    expect(library.card(second)).to_have_count(0)
    expect(library.card(other)).to_be_visible()
    expect(library.tid("selection-bar")).to_be_hidden()
    assert len(writes) == 1


def test_an_unpicked_graph_moves_alone_and_keeps_the_picks(
    library: DragLibrary, api: httpx.Client
) -> None:
    picked, loose, target = (unique_name(word) for word in ("Picked", "Loose", "Target"))
    seed_graph(api, picked)
    seed_graph(api, loose)
    seed_folder(api, target)
    library.goto()
    library.tick(picked).check()
    library.drag(library.card(loose), library.folder_card(target))
    library.expect_toast(f"Moved “{loose}” to “{target}”.", "success")
    expect(library.card(picked)).to_be_visible()
    expect(library.tick(picked)).to_be_checked()
