# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.6, actions on cards: duplicate, delete with its confirmation, picking graphs to compare.

One server for the module; every test seeds graphs with a unique name and looks at them through
``?q=<name>``, so the order and the size of the library never matter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_b_library import LibraryPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def library(page: WatchedPage, live_server: LiveServer) -> LibraryPage:
    return LibraryPage(page, live_server)


def stored_names(api: httpx.Client, query: str) -> list[str]:
    """Names of the graphs the API finds for ``query`` (newest first)."""
    found = json_of(api.get("/api/v1/graphs", params={"q": query}))
    return [item["name"] for item in found["items"]]


# ------------------------------------------------------------------------------ duplicate


def test_duplicate_copies_the_graph_offers_to_open_it_and_the_copy_is_independent(
    library: LibraryPage, api: httpx.Client
) -> None:
    name = unique_name("Dup")
    original = seed_graph(api, name, tags=["keepme"])
    library.goto(f"?q={name}")
    library.card(name).get_by_test_id("graph-duplicate").click()
    library.expect_toast(f"Created “{name} (copy)”.", "success")
    library.expect_names([f"{name} (copy)", name])  # the search matches the copy by its name too
    listing = json_of(api.get("/api/v1/graphs", params={"q": name}))["items"]
    copy = next(item for item in listing if item["id"] != original["id"])
    assert (copy["tags"], copy["revision"]) == (["keepme"], 1)
    library.card(f"{name} (copy)").get_by_test_id(
        "graph-delete"
    ).click()  # the copy is its own graph
    library.tid("delete-confirm").click()
    library.expect_toast(f"Deleted “{name} (copy)”.", "success")
    assert json_of(api.get(f"/api/v1/graphs/{original['id']}"))["name"] == name
    library.expect_names([name])


def test_open_copy_leads_to_the_copy(library: LibraryPage, api: httpx.Client) -> None:
    name = unique_name("Open")
    seed_graph(api, name)
    library.goto(f"?q={name}")
    library.card(name).get_by_test_id("graph-duplicate").click()
    toast = library.expect_toast(f"Created “{name} (copy)”.", "success")
    toast.get_by_role("button", name="Open copy").click()
    library.page.wait_for_url("**/graphs/*")
    expect(library.heading).to_have_text(f"{name} (copy)")


# ------------------------------------------------------------------------------ delete


def test_the_delete_dialog_cancels_with_escape_and_with_the_button_then_deletes(
    library: LibraryPage, api: httpx.Client
) -> None:
    name = unique_name("Doomed")
    graph = seed_graph(api, name)
    library.goto(f"?q={name}")
    opener = library.card(name).get_by_test_id("graph-delete")
    dialog = library.tid("delete-dialog")
    cancel = library.tid("confirm-dialog-cancel")
    opener.click()
    expect(dialog).to_contain_text(f"Delete “{name}”?")
    expect(cancel).to_be_focused()  # the safe choice has the focus
    library.page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(opener).to_be_focused()  # and the focus goes back to where it was
    assert stored_names(api, name) == [name]
    opener.click()
    library.page.keyboard.press("Tab")
    expect(library.tid("delete-confirm")).to_be_focused()
    library.page.keyboard.press("Tab")
    expect(cancel).to_be_focused()  # the focus is trapped inside the dialog
    cancel.click()
    expect(dialog).to_be_hidden()
    assert stored_names(api, name) == [name]
    expect(library.toasts()).to_have_count(0)
    opener.click()
    library.tid("delete-confirm").click()
    library.expect_toast(f"Deleted “{name}”.", "success")
    expect(library.tid("library-no-results")).to_be_visible()
    assert api.get(f"/api/v1/graphs/{graph['id']}").status_code == 404
    library.page.reload()
    library.expect_ready()
    expect(library.tid("library-no-results")).to_be_visible()


def test_deleting_a_graph_that_is_already_gone_says_so_and_refreshes_the_list(
    library: LibraryPage, api: httpx.Client
) -> None:
    name = unique_name("Ghost")
    graph = seed_graph(api, name)
    library.goto(f"?q={name}")
    assert api.delete(f"/api/v1/graphs/{graph['id']}").status_code == 204  # deleted elsewhere
    # The page still lists it; the server answers 404 and Chrome logs that request once.
    library.page.allow_http(404, f"/api/v1/graphs/{graph['id']}")
    library.card(name).get_by_test_id("graph-delete").click()
    library.tid("delete-confirm").click()
    toast = library.expect_toast("That graph was already gone.", "info")
    expect(toast).not_to_contain_text("{")
    expect(library.cards).to_have_count(0)
    assert library.page.watch.matching(r"^http 404: DELETE ")


# ------------------------------------------------------------------------------ picking graphs


def test_ticking_graphs_opens_the_selection_bar_and_the_compare_link(
    library: LibraryPage, api: httpx.Client
) -> None:
    prefix = unique_name("Pick")
    ids = [seed_graph(api, f"{prefix} {letter}")["id"] for letter in "ABC"]
    library.goto(f"?q={prefix}")
    bar = library.tid("selection-bar")
    expect(bar).to_be_hidden()
    library.tick(f"{prefix} A").check()
    expect(bar).to_contain_text("1 graph selected")
    expect(library.tid("compare-open")).to_have_attribute("aria-disabled", "true")
    library.tick(f"{prefix} B").check()
    library.tick(f"{prefix} C").check()
    expect(bar).to_contain_text("3 graphs selected")
    expect(library.tid("compare-open")).to_have_attribute("href", f"/compare?ids={','.join(ids)}")
    library.tid("selection-clear").click()
    expect(bar).to_be_hidden()
    expect(library.tick(f"{prefix} A")).not_to_be_checked()
