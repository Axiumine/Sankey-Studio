# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The viewer's legends: the Sankey shows one, the list under the chart; the donut keeps its own.

The legend list under the Sankey names the same entries as the legend row the server draws in the
figure, so the page draws the Sankey without that row and uses its room for the plot. The donut
legend hides and shows slices: it stays in the figure and its coloured squares keep the pointer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import make_client, seed_graph
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: The cursor of the element under the middle of the first legend square of a chart.
_CURSOR_UNDER_SQUARE_JS = """chart => {
    const square = chart.querySelector('.legend .legendpoints path');
    const box = square.getBoundingClientRect();
    const under = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return getComputedStyle(under).cursor;
}"""
#: How far the top of the highest node is below the top of the chart, in pixels.
_PLOT_OFFSET_JS = """chart => {
    const tops = [...chart.querySelectorAll('.sankey-node rect.node-rect')]
        .map(rect => rect.getBoundingClientRect().top);
    return Math.min(...tops) - chart.getBoundingClientRect().top;
}"""
#: A legend row above the plot needs about 40 px (the margin of the figure); the bare margin is 16.
_MAX_OFFSET_WITHOUT_LEGEND_ROW = 30


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def graph_id(module_server: LiveServer) -> str:
    draft = graph_draft(BUDGET_CATEGORISED.csv, style={"color_mode": "category"})
    with make_client(module_server) as client:
        return str(seed_graph(client, unique_name("Legend"), draft)["id"])


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, graph_id: str) -> ViewerPage:
    viewer = ViewerPage(page, live_server)
    viewer.open(graph_id)
    return viewer


def test_the_sankey_shows_its_legend_once_as_the_list_under_the_chart(viewer: ViewerPage) -> None:
    expect(viewer.tid("sankey-chart").locator(".legend")).to_have_count(0)
    expect(viewer.tid("sankey-chart").locator(".legendtext")).to_have_count(0)
    expect(viewer.tid("legend")).to_have_count(1)
    expect(viewer.tid("legend-item")).to_have_count(BUDGET_CATEGORISED.category_count)


def test_the_plot_starts_at_the_top_of_the_chart_where_the_legend_row_used_to_be(
    viewer: ViewerPage,
) -> None:
    chart = viewer.tid("sankey-chart")

    assert 0 <= chart.evaluate(_PLOT_OFFSET_JS) <= _MAX_OFFSET_WITHOUT_LEGEND_ROW


def test_the_cursor_over_a_donut_legend_square_stays_the_pointer_that_toggles_a_slice(
    viewer: ViewerPage,
) -> None:
    viewer.open_donut()

    assert viewer.tid("donut-chart").evaluate(_CURSOR_UNDER_SQUARE_JS) == "pointer"
