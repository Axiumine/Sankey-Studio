# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""F4: drag a bar of the Sankey to reorder the nodes; the order is stored with the graph.

A drag (snap, perpendicular and freeform, horizontal and vertical) puts the dropped bar where it
was dropped and keeps it there after every redraw, a reload and Save; a plain click is not a drag;
fixed bars cannot be dragged; "Reset order" goes back to the automatic layout; the rows of pasted
text follow when the colours do not move; the viewer and the SVG export draw the stored order. The
buttons "Order nodes" and the dialog are the keyboard twin of the drag (WCAG 2.1.1, 2.5.7).
The chart carries ``data-node-order`` (the node names in figure order) once it is drawn: the tests
wait on it, never on a clock.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_a_charts import ChartDom
from tests.e2e.support.ui_a_downloads import download
from tests.e2e.support.ui_a_editor import EditGraphPage
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: The sinks of the budget sample stand in one column, top to bottom in this order.
SINKS = ["Rent", "Utilities", "Transport", "Savings", "Groceries", "Restaurants"]
SAVED_NOTE = re.compile(r"Node order saved with this graph\. .*press Reset order\.")
PINNED_NOTE = re.compile(r"\d+ colours were pinned so the chart keeps its colours")
HEX = re.compile(r"#[0-9a-f]{6}")
UNSAVED = "Unsaved changes"
MODES = [
    pytest.param(("h", "snap", 0, -300), id="horizontal-snap"),
    pytest.param(("h", "perpendicular", 0, -300), id="horizontal-perpendicular"),
    pytest.param(("h", "freeform", 0, -300), id="horizontal-freeform"),
    pytest.param(("v", "snap", -600, 0), id="vertical-snap"),
    pytest.param(("v", "perpendicular", -600, 0), id="vertical-perpendicular"),
]
SVG_NODE = re.compile(
    r'<g class="sankey-node" transform="translate\(([\d.]+),([\d.-]+)\)".*?'
    r'class="node-label"[^>]*>([^<]*)</text>',
    re.DOTALL,
)


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def open_editor(
    page: WatchedPage, server: LiveServer, api: httpx.Client, draft: dict[str, Any] | None = None
) -> tuple[EditGraphPage, ChartDom, str]:
    """Seed a graph (the budget, unless ``draft`` says otherwise) and open its editor."""
    given = draft if draft is not None else graph_draft()
    graph_id = str(seed_graph(api, unique_name("Node order"), given)["id"])
    editor = EditGraphPage(page, server)
    editor.open(graph_id)
    charts = ChartDom(page)
    expect(page.locator("[data-testid=sankey-chart]")).to_have_attribute(
        "data-node-order", re.compile(r".+")
    )
    return editor, charts, graph_id


def style_of(api: httpx.Client, graph_id: str) -> dict[str, Any]:
    stored = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    style: dict[str, Any] = stored["style"]
    return style


# ------------------------------------------------------------------------------ the drag


@pytest.mark.parametrize("mode", MODES)
def test_a_dropped_bar_stays_where_it_was_dropped(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client, mode: tuple[str, str, int, int]
) -> None:
    orientation, arrangement, dx, dy = mode
    style = {"orientation": orientation, "arrangement": arrangement}
    editor, charts, graph_id = open_editor(page, live_server, api, graph_draft(style=style))
    axis = "y" if orientation == "h" else "x"
    charts.expect_stack(["Rent", "Utilities"], axis=axis)

    charts.drag_bar("Utilities", dx=dx, dy=dy)

    order = charts.wait_before("Utilities", "Rent")
    expect(editor.save_status).to_contain_text(UNSAVED)
    expect(editor.tid("chart-reset-order")).to_be_visible()
    expect(editor.tid("chart-order-open")).to_be_enabled()
    expect(page.get_by_test_id("sankey-chart")).to_have_attribute("data-ready", "true")
    charts.expect_stack(["Utilities", "Rent"], axis=axis)
    editor.save()
    assert style_of(api, graph_id)["node_order"] == order


def test_the_order_survives_a_reload_and_a_style_change(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    style = {"arrangement": "perpendicular"}
    editor, charts, graph_id = open_editor(page, live_server, api, graph_draft(style=style))
    charts.drag_bar("Utilities", dy=-300)
    order = charts.wait_before("Utilities", "Rent")
    editor.save()

    editor.open(graph_id)
    expect(page.get_by_test_id("sankey-chart")).to_have_attribute(
        "data-node-order", "|".join(order)
    )
    charts.expect_stack(["Utilities", "Rent"])
    editor.open_section("style")
    editor.tid("style-height").fill("620")
    editor.wait_preview()
    assert charts.drawn_order() == order
    charts.expect_stack(["Utilities", "Rent"])


def test_a_plain_click_on_a_bar_does_not_dirty_the_draft(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, charts, _ = open_editor(page, live_server, api)
    before = charts.drawn_order()
    charts.watch_restyles()

    charts.click_bar("Food")
    charts.wait_restyles(1)  # Plotly restyles after a click as it does after a drag

    assert charts.drawn_order() == before
    expect(editor.save_status).not_to_contain_text(UNSAVED)
    expect(editor.tid("chart-reset-order")).to_be_hidden()


#: Crossing links: the automatic layout may draw a column in another order than the rows list it.
CROSSING = "source,target,value\nA,X,1\nB,Y,1\nA,Y,10\nB,X,10\n"


def test_a_drag_is_compared_with_the_drawn_order_not_the_order_of_the_rows(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(CROSSING, style={"arrangement": "freeform"})
    editor, charts, graph_id = open_editor(page, live_server, api, draft)
    expect(page.get_by_test_id("sankey-chart")).to_have_attribute("data-ready", "true")
    charts.expect_stack(["B", "A"])  # the layout crosses the rows (A, X, B, Y)
    top, low = "B", "A"
    charts.watch_restyles()

    charts.drag_bar(top, dy=12)  # a small move: the bars keep their order, whatever the rows say
    charts.wait_restyles(1)

    expect(editor.save_status).not_to_contain_text(UNSAVED)
    expect(editor.tid("chart-reset-order")).to_be_hidden()
    charts.drag_bar(low, dy=-400)  # now really above the other one
    charts.wait_before(low, top)
    expect(editor.save_status).to_contain_text(UNSAVED)
    editor.save()
    saved = style_of(api, graph_id)["node_order"]
    assert saved.index(low) < saved.index(top)


def test_fixed_bars_cannot_be_dragged_or_ordered(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(style={"arrangement": "fixed"})
    editor, charts, _ = open_editor(page, live_server, api, draft)
    before = charts.bar("Utilities").bounding_box()

    charts.drag_bar("Utilities", dy=-300)

    assert charts.bar("Utilities").bounding_box() == before
    expect(editor.save_status).not_to_contain_text(UNSAVED)
    expect(editor.tid("chart-order-open")).to_be_disabled()
    expect(editor.tid("chart-order-open")).to_have_attribute("title", re.compile("Fixed"))
    expect(editor.tid("chart-reset-order")).to_be_hidden()


# ------------------------------------------------------------------------------ reset


def test_reset_order_goes_back_to_the_automatic_layout(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    style = {"arrangement": "perpendicular"}
    editor, charts, graph_id = open_editor(page, live_server, api, graph_draft(style=style))
    charts.drag_bar("Utilities", dy=-300)
    charts.wait_before("Utilities", "Rent")
    editor.save()
    assert style_of(api, graph_id)["node_order"]

    editor.tid("chart-reset-order").click()

    # The rows were rewritten by the drag, so the automatic layout follows the new rows.
    expect(editor.tid("chart-reset-order")).to_be_hidden()
    charts.expect_stack(["Utilities", "Rent"])
    editor.save()
    assert style_of(api, graph_id)["node_order"] == []


# ------------------------------------------------------------------------------ the rows


def test_the_rows_follow_the_drag_when_the_colours_do_not_move(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    style = {"arrangement": "perpendicular", "color_mode": "mono"}
    editor, charts, _ = open_editor(page, live_server, api, graph_draft(style=style))
    expect(editor.content).to_have_value(BUDGET.csv)

    charts.drag_bar("Utilities", dy=-300)

    charts.wait_before("Utilities", "Rent")
    expect(editor.content).to_have_value(
        re.compile(r"Budget,Utilities,260\nBudget,Rent,1200\n"), timeout=15_000
    )
    editor.expect_toast(SAVED_NOTE)


def test_the_rows_follow_the_drag_and_the_colours_are_pinned_in_the_default_colour_mode(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    style = {"arrangement": "perpendicular"}  # the default colour mode gives every node its colour
    editor, charts, graph_id = open_editor(page, live_server, api, graph_draft(style=style))

    charts.drag_bar("Utilities", dy=-300)

    charts.wait_before("Utilities", "Rent")
    expect(editor.content).to_have_value(
        re.compile(r"Budget,Utilities,260\nBudget,Rent,1200\n"), timeout=15_000
    )
    editor.expect_toast(SAVED_NOTE)
    editor.expect_toast(PINNED_NOTE)
    editor.save()
    pinned = style_of(api, graph_id)["node_colors"]
    assert "Rent" in pinned  # a node whose hue the new row order would have changed
    assert all(HEX.fullmatch(colour) for colour in pinned.values())


# ------------------------------------------------------------------------------ elsewhere


def test_the_viewer_and_the_svg_export_draw_the_stored_order(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    style = {"arrangement": "perpendicular"}
    editor, charts, graph_id = open_editor(page, live_server, api, graph_draft(style=style))
    charts.drag_bar("Utilities", dy=-300)
    charts.wait_before("Utilities", "Rent")
    editor.save()

    editor.open_export()
    svg = download(page, editor.tid("export-sankey-svg")).text
    places = {label.strip(): float(y) for _, y, label in SVG_NODE.findall(svg)}
    assert places["Utilities"] < places["Rent"]

    viewer = ViewerPage(page, live_server)
    viewer.open(graph_id)
    ChartDom(page).expect_stack(["Utilities", "Rent"])


# ------------------------------------------------------------------------------ the keyboard twin


def test_the_order_dialog_lists_the_nodes_column_by_column(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, _, _ = open_editor(page, live_server, api)

    editor.tid("chart-order-open").click()

    dialog = editor.tid("order-dialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator("h3")).to_have_text([f"Column {n} of 4" for n in range(1, 5)])
    expect(dialog.locator("section").nth(3).locator(".order-node-name")).to_have_text(SINKS)
    expect(dialog.get_by_test_id("order-up")).to_have_count(BUDGET.nodes)
    expect(dialog.get_by_role("button", name="Move Rent up")).to_be_disabled()
    expect(dialog.get_by_role("button", name="Move Restaurants down")).to_be_disabled()
    expect(dialog.get_by_role("button", name="Move Utilities up")).to_be_enabled()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(editor.tid("chart-order-open")).to_be_focused()


def test_the_nodes_can_be_ordered_with_the_keyboard_alone(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, charts, graph_id = open_editor(page, live_server, api)
    editor.tid("chart-order-open").focus()
    page.keyboard.press("Enter")
    dialog = editor.tid("order-dialog")
    expect(dialog).to_be_visible()

    up = dialog.get_by_role("button", name="Move Utilities up")
    up.focus()
    page.keyboard.press("Enter")

    # Utilities is first now: its Up button is disabled, so the focus moved to its Down button
    expect(dialog.get_by_role("button", name="Move Utilities down")).to_be_focused()
    dialog.get_by_role("button", name="Done").focus()
    page.keyboard.press("Enter")
    expect(dialog).to_have_count(0)
    expect(editor.tid("chart-order-open")).to_be_focused()
    charts.wait_before("Utilities", "Rent")
    charts.expect_stack(["Utilities", "Rent"])
    expect(editor.tid("chart-reset-order")).to_be_visible()
    editor.save()
    stored = style_of(api, graph_id)["node_order"]
    assert stored.index("Utilities") < stored.index("Rent")
