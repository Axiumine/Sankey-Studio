# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The viewer's tables behind a link: "Table view of the links" and "Table view of the categories".

Both charts keep their HTML twin out of sight until the person opens it: the Sankey tab has the
links table, the Donut tab has the category table, and the two blocks look and work the same. A
redraw of the chart (a display switch) keeps the block as the person left it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.ui_a_display import DONUT_VALUE, DisplayMenu
from tests.e2e.support.ui_a_seed import SavedGraph, save_graph
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    from playwright.sync_api import Locator

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

CATEGORY_LABEL = "Table view of the categories"
LINKS_LABEL = "Table view of the links"
#: Marks the block that is on screen; a redraw builds a new one, which does not carry it.
_MARK_JS = "el => el.setAttribute('data-before-redraw', '')"
STALE = "[data-testid=category-details][data-before-redraw]"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def saved(module_server: LiveServer) -> SavedGraph:
    return save_graph(module_server, "Tables")


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, saved: SavedGraph) -> ViewerPage:
    viewer = ViewerPage(page, live_server)
    viewer.open(saved.id)
    return viewer


def summary_of(block: Locator) -> Locator:
    return block.locator("summary")


def test_the_donut_table_is_a_closed_link_that_opens_the_category_table(viewer: ViewerPage) -> None:
    viewer.open_donut()
    block, table = viewer.tid("category-details"), viewer.tid("category-table")

    expect(summary_of(block)).to_have_text(CATEGORY_LABEL)
    expect(block).not_to_have_attribute("open", "")
    expect(table).to_be_hidden()
    expect(viewer.tid("donut-chart")).to_be_visible()

    summary_of(block).click()
    expect(block).to_have_attribute("open", "")
    expect(table).to_be_visible()
    expect(viewer.tid("category-row")).to_have_count(5)
    expect(table.locator("tfoot")).to_have_text("Total8,240100%")

    summary_of(block).click()
    expect(table).to_be_hidden()


def test_the_donut_and_the_sankey_open_their_table_the_same_way(viewer: ViewerPage) -> None:
    links = viewer.tid("links-table")
    expect(summary_of(links)).to_have_text(LINKS_LABEL)
    expect(links).to_have_class("table-view")
    expect(links.locator("table")).to_have_count(0)  # built on the first open
    viewer.open_donut()
    category = viewer.tid("category-details")

    expect(category).to_have_class("table-view")
    cursor = summary_of(category).evaluate("el => getComputedStyle(el).cursor")
    assert cursor == "pointer"
    assert summary_of(category).evaluate("el => getComputedStyle(el).color") == summary_of(
        links
    ).evaluate("el => getComputedStyle(el).color")


def test_the_basis_note_stays_above_the_link_in_the_donut_tab(viewer: ViewerPage) -> None:
    viewer.open_donut()
    panel = viewer.tid("donut-chart").locator("xpath=ancestor::div[contains(@class,'chart-panel')]")

    expect(panel.locator(".donut-basis")).to_be_visible()
    expect(panel.locator(".donut-basis ~ details")).to_have_count(1)
    expect(panel.locator("details")).to_have_count(1)


@pytest.mark.parametrize("opened", [False, True], ids=["closed", "open"])
def test_a_redraw_keeps_the_category_table_as_the_person_left_it(
    viewer: ViewerPage, opened: bool
) -> None:
    viewer.open_donut()
    block = viewer.tid("category-details")
    if opened:
        summary_of(block).click()
    block.evaluate(_MARK_JS)
    menu = DisplayMenu(viewer)
    menu.open()

    menu.set(DONUT_VALUE, True)

    expect(viewer.page.locator(STALE)).to_have_count(0)  # the block was rebuilt
    expect(viewer.tid("category-details")).to_have_count(1)
    if opened:
        expect(viewer.tid("category-details")).to_have_attribute("open", "")
        expect(viewer.tid("category-table")).to_be_visible()
    else:
        expect(viewer.tid("category-details")).not_to_have_attribute("open", "")
        expect(viewer.tid("category-table")).to_be_hidden()
