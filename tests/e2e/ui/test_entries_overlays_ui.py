# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Graph-only edits stay visible: the chip "Graph-only edits (N)", its list, the unmatched notice.

Category edits, added entries and a custom node order that live in the graph (not in its data) are
counted on a chip in the Entries card header. The chip opens a list with one row per item and a
Remove button on each; removing changes the graph at once (the table and the chart follow) and
leaves it unsaved. Category edits that match no entry any more are called out above the table.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_a_editor import EditGraphPage
from tests.e2e.support.ui_a_entries import EntriesPanel

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

RENT = ("Budget", "Rent")
ORDER = ["Salary", "Freelance", "Budget"]


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def category(source: str, target: str, name: str | None) -> dict[str, Any]:
    return {"source": source, "target": target, "category": name}


def overlay_draft() -> dict[str, Any]:
    """Two category edits, one added entry and a custom order on top of the budget text."""
    transform = {
        "entry_categories": [category(*RENT, "Housing"), category("Budget", "Food", None)],
        "extra_links": [{"source": "Budget", "target": "Gifts", "value": 50, "category": "Fun"}],
    }
    return graph_draft(transform=transform, style={"node_order": ORDER})


def open_graph(
    page: WatchedPage, server: LiveServer, api: httpx.Client, draft: dict[str, Any]
) -> tuple[EditGraphPage, EntriesPanel, str]:
    graph_id = str(seed_graph(api, unique_name("Graph only"), draft)["id"])
    editor = EditGraphPage(page, server)
    editor.open(graph_id)
    return editor, EntriesPanel(page), graph_id


def test_the_chip_counts_every_item_and_the_list_names_them(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, entries, _ = open_graph(page, live_server, api, overlay_draft())

    expect(entries.overlays_chip).to_have_text("Graph-only edits (4)")
    entries.overlays_chip.click()

    expect(entries.overlays.dialog).to_be_visible()
    expect(entries.overlays.dialog).to_contain_text(
        "These edits are stored in this graph, not in your data."
    )
    expect(entries.overlays.rows).to_have_text(
        [
            "Budget to Rent: category HousingRemove",
            "Budget to Food: no categoryRemove",
            "Budget to Gifts: 50, category FunRemove",
            "Custom node order (3 nodes)Remove",
        ]
    )
    expect(entries.overlays.dialog.get_by_role("button", name="Done")).to_be_focused()
    expect(entries.overlays.dialog).not_to_contain_text("null")


def test_removing_items_changes_the_graph_and_leaves_it_unsaved(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, graph_id = open_graph(page, live_server, api, overlay_draft())
    expect(entries.cell(*RENT)).to_have_value("Housing")
    entries.overlays_chip.click()

    entries.overlays.remove("Budget to Rent")

    expect(entries.cell(*RENT)).to_have_value("")
    expect(entries.overlays_chip).to_have_text("Graph-only edits (3)")
    expect(entries.overlays.rows).to_have_count(3)
    expect(entries.overlays.rows.first.get_by_test_id("overlay-remove")).to_be_focused()
    entries.overlays.remove("Custom node order")
    entries.overlays.remove("Budget to Gifts")
    expect(entries.row("Budget", "Gifts")).to_have_count(0)
    entries.overlays.dialog.get_by_role("button", name="Done").click()
    expect(editor.save_status).to_contain_text(re.compile("unsaved", re.IGNORECASE))
    editor.save()
    graph = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    assert graph["transform"]["entry_categories"] == [category("Budget", "Food", None)]
    assert graph["transform"]["extra_links"] == []
    assert graph["style"]["node_order"] == []


def test_the_last_removal_hides_the_chip_and_the_focus_goes_to_add_entry(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(style={"node_order": ORDER})
    _, entries, _ = open_graph(page, live_server, api, draft)
    expect(entries.overlays_chip).to_have_text("Graph-only edits (1)")
    entries.overlays_chip.click()

    entries.overlays.remove("Custom node order")

    expect(entries.overlays.dialog).to_contain_text("No graph-only edits are left.")
    expect(entries.overlays.dialog).not_to_contain_text("null")
    entries.overlays.dialog.get_by_role("button", name="Done").click()
    expect(entries.overlays.dialog).to_have_count(0)
    expect(entries.overlays_chip).to_be_hidden()
    expect(entries.add_button).to_be_focused()


def test_a_long_list_shows_the_first_rows_and_counts_the_rest(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    pairs = [category(f"S{n}", "Nowhere", "Misc") for n in range(250)]
    _, entries, _ = open_graph(
        page, live_server, api, graph_draft(transform={"entry_categories": pairs})
    )

    expect(entries.overlays_chip).to_have_text("Graph-only edits (250)")
    entries.overlays_chip.click()

    expect(entries.overlays.rows).to_have_count(200)
    expect(entries.overlays.dialog).to_contain_text("50 more are not shown.")


def test_category_edits_that_match_no_entry_are_called_out_and_listed(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    stale = [category("Gone", "Away", "Old"), category("Never", "There", "Old")]
    draft = graph_draft(transform={"entry_categories": [category(*RENT, "Housing"), *stale]})
    _, entries, _ = open_graph(page, live_server, api, draft)

    expect(entries.unmatched).to_be_visible()
    expect(entries.unmatched).to_contain_text(
        "2 of your category edits no longer match an entry (the names changed)."
    )
    entries.overlays_chip.click()
    entries.overlays.remove("Gone to Away")
    entries.overlays.remove("Never to There")

    expect(entries.unmatched).to_have_count(0)
    expect(entries.cell(*RENT)).to_have_value("Housing")


def test_a_graph_without_stale_edits_has_no_notice_and_no_chip(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, entries, _ = open_graph(page, live_server, api, graph_draft())

    expect(entries.add_button).to_be_visible()
    expect(entries.overlays_chip).to_be_hidden()
    expect(entries.unmatched).to_have_count(0)


@pytest.mark.parametrize("viewport", [{"width": 390, "height": 844}])
@pytest.mark.parametrize("color_scheme", ["dark"])
def test_a_phone_in_the_dark_keeps_the_header_and_both_dialogs_inside_the_window(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, entries, _ = open_graph(page, live_server, api, overlay_draft())
    inside = "box => box.left >= 0 && box.right <= window.innerWidth"
    entries.overlays_chip.scroll_into_view_if_needed()

    for button in (entries.overlays_chip, entries.add_button):
        expect(button).to_be_visible()
        assert button.evaluate(f"el => ({inside})(el.getBoundingClientRect())")
    entries.add_button.click()
    assert entries.add_dialog.dialog.evaluate(f"el => ({inside})(el.getBoundingClientRect())")
    entries.add_dialog.cancel.click()
    entries.overlays_chip.click()
    assert entries.overlays.dialog.evaluate(f"el => ({inside})(el.getBoundingClientRect())")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
