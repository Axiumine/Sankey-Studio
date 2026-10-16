# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The display menu of the viewer, part 1: the icon, its panel, the tab strip and the Sankey switch.

An icon button at the right of the chart card's tab row opens a panel of view-only switches. This
file covers the icon and the panel (open, close on Escape / a click elsewhere / focus leaving), the
tab strip that must not scroll vertically, the Sankey switch (the value on a second line under the
node name, sent as ``node_values`` to ``GET /graphs/<id>/render``), the absent donut group of a
graph without categories and a failed redraw that puts the switch back. The donut switches, the
exports and the saved style are in ``test_viewer_display_charts_ui.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET
from tests.e2e.support.ui_a_charts import ChartDom
from tests.e2e.support.ui_a_display import (
    DONUT_PERCENT,
    DONUT_VALUE,
    NODE_VALUES,
    DisplayMenu,
    RequestLog,
    tab_strip_overflow,
)
from tests.e2e.support.ui_a_seed import SavedGraph, save_graph
from tests.e2e.support.ui_a_viewer import ViewerPage
from tests.e2e.support.ui_b_common import DESKTOP, PHONE

if TYPE_CHECKING:
    from playwright.sync_api import Route

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

SECOND_LINES = (("Salary", "3,000"), ("Budget", "3,800"), ("Rent", "1,200"))
FAILURE = {"error": {"code": "internal_error", "message": "Something went wrong.", "details": []}}


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def saved(module_server: LiveServer) -> SavedGraph:
    return save_graph(module_server, "Display menu")


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, saved: SavedGraph) -> ViewerPage:
    viewer = ViewerPage(page, live_server)
    viewer.open(saved.id)
    return viewer


def asks_for_node_values(url: str) -> bool:
    return "node_values=true" in url


def fail(route: Route) -> None:
    route.fulfill(status=500, json=FAILURE)


def expect_second_line(charts: ChartDom) -> None:
    for name, value in SECOND_LINES:
        expect(charts.node_label(name).locator("tspan")).to_have_text([name, value])


# ------------------------------------------------------------------------------ icon and panel


def test_the_icon_sits_at_the_right_of_the_tab_row_and_opens_a_panel_of_three_switches(
    viewer: ViewerPage,
) -> None:
    menu = DisplayMenu(viewer)
    expect(menu.button).to_be_visible()
    expect(menu.button).to_have_attribute("aria-label", "Chart display options")
    expect(menu.button).to_have_attribute("aria-expanded", "false")
    expect(menu.panel).to_be_hidden()
    donut_tab = viewer.tid("chart-tab-donut").bounding_box()
    icon = menu.button.bounding_box()
    assert donut_tab is not None
    assert icon is not None
    assert icon["x"] >= donut_tab["x"] + donut_tab["width"]  # at the right of the tabs ...
    assert abs(icon["y"] - donut_tab["y"]) < donut_tab["height"]  # ... on the same row

    menu.open()

    expect(menu.panel).to_contain_text("Show values under the node names")
    expect(menu.panel).to_contain_text("Show percentages")
    expect(menu.panel).to_contain_text("Show values")
    expect(menu.switch(NODE_VALUES)).not_to_be_checked()
    expect(menu.switch(DONUT_PERCENT)).to_be_checked()
    expect(menu.switch(DONUT_VALUE)).not_to_be_checked()
    menu.button.click()
    expect(menu.panel).to_be_hidden()
    expect(menu.button).to_have_attribute("aria-expanded", "false")


def test_the_panel_closes_on_escape_with_focus_back_on_the_icon_and_on_a_click_elsewhere(
    viewer: ViewerPage,
) -> None:
    menu = DisplayMenu(viewer)
    menu.open()
    menu.switch(NODE_VALUES).focus()

    viewer.page.keyboard.press("Escape")

    expect(menu.panel).to_be_hidden()
    expect(menu.button).to_be_focused()
    expect(menu.button).to_have_attribute("aria-expanded", "false")
    menu.open()
    viewer.heading.click()  # a pointer press outside the menu
    expect(menu.panel).to_be_hidden()
    menu.open()
    viewer.tid("chart-tab-donut").click()  # a press on the tabs is outside it too
    expect(menu.panel).to_be_hidden()


def test_the_panel_stays_open_while_the_keyboard_walks_its_switches_and_closes_when_focus_leaves(
    viewer: ViewerPage,
) -> None:
    menu = DisplayMenu(viewer)
    menu.button.focus()
    viewer.page.keyboard.press("Enter")
    expect(menu.panel).to_be_visible()

    for testid in (NODE_VALUES, DONUT_PERCENT, DONUT_VALUE):
        viewer.page.keyboard.press("Tab")
        expect(menu.switch(testid)).to_be_focused()
        expect(menu.panel).to_be_visible()
    viewer.page.keyboard.press("Tab")  # the next control after the panel

    expect(menu.panel).to_be_hidden()
    expect(menu.button).to_have_attribute("aria-expanded", "false")
    assert not menu.switch(DONUT_VALUE).evaluate("el => el === document.activeElement")


# ------------------------------------------------------------------------------ the tab strip


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_the_tab_strip_has_no_vertical_scrollbar_beside_the_donut_tab(
    page: WatchedPage, viewer: ViewerPage, viewport: dict[str, int]
) -> None:
    assert page.viewport_size == viewport
    strip = page.get_by_role("tablist", name="Chart type")
    expect(strip).to_have_css("overflow-y", "hidden")

    scroll_height, client_height = tab_strip_overflow(page)

    assert scroll_height == client_height
    viewer.tid("chart-tab-donut").click()
    assert tab_strip_overflow(page) == (scroll_height, client_height)
    expect(DisplayMenu(viewer).button).to_be_visible()


# ------------------------------------------------------------------------------ the Sankey switch


def test_the_sankey_switch_puts_the_value_on_a_second_line_under_each_node_name(
    viewer: ViewerPage,
) -> None:
    menu, charts, log = DisplayMenu(viewer), ChartDom(viewer.page), RequestLog(viewer.page)
    expect(charts.node_label("Salary")).to_have_text("Salary")  # the name alone
    expect(charts.node_label("Salary").locator("tspan")).to_have_count(0)
    menu.open()

    menu.set(NODE_VALUES, True)

    expect_second_line(charts)
    assert log.last("render") == {"theme": "light", "node_values": "true"}
    expect(viewer.tid("sankey-chart")).to_have_attribute("data-ready", "true")
    expect(menu.switch(NODE_VALUES)).to_be_checked()
    menu.set(NODE_VALUES, False)
    expect(charts.node_label("Salary")).to_have_text("Salary")
    expect(charts.node_label("Salary").locator("tspan")).to_have_count(0)
    assert log.last("render") == {"theme": "light", "node_values": "false"}


def test_a_graph_without_categories_offers_the_sankey_switch_and_no_donut_group(
    page: WatchedPage, live_server: LiveServer
) -> None:
    plain = save_graph(live_server, "No categories", BUDGET.csv)
    viewer = ViewerPage(page, live_server)
    viewer.open(plain.id)
    menu, charts, log = DisplayMenu(viewer), ChartDom(page), RequestLog(page)
    expect(viewer.tid("chart-tab-donut")).to_have_count(0)

    menu.open()

    expect(menu.switch(NODE_VALUES)).to_be_visible()
    expect(menu.switch(DONUT_PERCENT)).to_be_hidden()
    expect(menu.switch(DONUT_VALUE)).to_be_hidden()
    expect(menu.panel.get_by_text("Donut", exact=True)).to_be_hidden()
    menu.set(NODE_VALUES, True)
    expect_second_line(charts)
    assert log.last("render") == {"theme": "light", "node_values": "true"}


# ------------------------------------------------------------------------------ a failed redraw


def test_a_failed_redraw_puts_the_switch_back_and_the_next_try_works(
    page: WatchedPage, viewer: ViewerPage
) -> None:
    menu, charts = DisplayMenu(viewer), ChartDom(page)
    page.allow_http(500, "/render")  # the answer served below, and Chrome's console line for it
    page.route(asks_for_node_values, fail)
    menu.open()

    with page.expect_response(lambda r: "/render" in r.url and r.status == 500):
        menu.switch(NODE_VALUES).click()  # no check(): it verifies the state, which is set back

    viewer.expect_toast("The chart could not be redrawn.", "error")
    expect(menu.switch(NODE_VALUES)).not_to_be_checked()
    expect(charts.node_label("Salary")).to_have_text("Salary")
    assert page.watch.matching(r"^http 500: GET .*/render\?.*node_values=true")
    page.unroute(asks_for_node_values, fail)

    menu.set(NODE_VALUES, True)

    expect(menu.switch(NODE_VALUES)).to_be_checked()
    expect_second_line(charts)


# ------------------------------------------------------------------------------ the numbers strip


def test_the_numbers_strip_shows_the_flow_and_the_categories_and_not_the_graph_size(
    viewer: ViewerPage,
) -> None:
    stats = viewer.tid("stats")

    expect(stats.locator(".stat-label")).to_have_text(["Total in", "Total out", "Categories"])
    expect(stats).not_to_contain_text("Nodes")
    expect(stats).not_to_contain_text("Links")
    expect(stats).not_to_contain_text("Layers")
