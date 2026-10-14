"""F2: click a bar of the Sankey to add a flow at that node.

A click on a node (never a link) opens the "Add a flow" dialog with the node prefilled by its role
in the DRAWN chart: a bar nothing leaves gets a flow that ends at it, every other bar a flow that
starts at it. The dialog names the node, offers the two directions as radios (choosing the other
one moves the node to the other end) and focuses the empty end. A drag of a bar does not open it,
and a hostile node name stays text.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import csv_text, graph_draft, unique_name
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.ui_a_charts import ChartDom
from tests.e2e.support.ui_a_editor import EditGraphPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

HOSTILE = "<i onerror=1>"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def open_editor(
    page: WatchedPage, server: LiveServer, api: httpx.Client, draft: dict[str, Any] | None = None
) -> tuple[EditGraphPage, ChartDom]:
    """Seed a graph (the budget, unless ``draft`` says otherwise) and open its editor, drawn."""
    given = draft if draft is not None else graph_draft()
    graph_id = str(seed_graph(api, unique_name("Node click"), given)["id"])
    editor = EditGraphPage(page, server)
    editor.open(graph_id)
    expect(page.locator("[data-testid=sankey-chart]")).to_have_attribute(
        "data-node-order", re.compile(r".+")
    )
    return editor, ChartDom(page)


def test_a_source_bar_starts_a_flow_and_focuses_the_target(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, charts = open_editor(page, live_server, api)

    charts.click_bar("Salary")

    flow = charts.flow_dialog
    flow.expect_open()
    expect(flow.title).to_have_text("Add a flow from Salary")
    expect(flow.starts_at).to_be_checked()
    expect(flow.ends_at).not_to_be_checked()
    flow.expect_ends("Salary", "")
    expect(flow.field("target")).to_be_focused()
    flow.field("target").fill("Gifts")
    flow.field("value").fill("50")
    flow.submit.click()
    flow.expect_gone()
    expect(editor.content).to_have_value(re.compile(r"^Salary,Gifts,50$", re.MULTILINE))


def test_a_sink_bar_ends_a_flow_and_focuses_the_source(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, charts = open_editor(page, live_server, api)

    charts.click_bar("Rent")

    flow = charts.flow_dialog
    flow.expect_open()
    expect(flow.title).to_have_text("Add a flow into Rent")
    expect(flow.ends_at).to_be_checked()
    flow.expect_ends("", "Rent")
    expect(flow.field("source")).to_be_focused()
    flow.field("source").fill("Budget")
    flow.field("value").fill("75")
    flow.submit.click()
    flow.expect_gone()
    expect(editor.content).to_have_value(re.compile(r"^Budget,Rent,75$", re.MULTILINE))


def test_a_middle_bar_starts_a_flow_and_the_radios_move_the_node_to_the_other_end(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, charts = open_editor(page, live_server, api)

    charts.click_bar("Budget")

    flow = charts.flow_dialog
    flow.expect_open()
    expect(flow.direction).to_be_visible()
    expect(flow.starts_at).to_be_checked()
    flow.expect_ends("Budget", "")
    flow.field("target").fill("Gifts")
    flow.ends_at.check()
    expect(flow.title).to_have_text("Add a flow into Budget")
    flow.expect_ends("Gifts", "Budget")
    expect(flow.ends_at).to_be_focused()
    flow.starts_at.check()
    expect(flow.title).to_have_text("Add a flow from Budget")
    flow.expect_ends("Budget", "Gifts")


def test_the_arrow_keys_choose_the_direction_and_a_flipped_flow_is_added(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, charts = open_editor(page, live_server, api)
    charts.click_bar("Budget")
    flow = charts.flow_dialog
    flow.expect_open()

    flow.starts_at.focus()
    page.keyboard.press("ArrowDown")

    expect(flow.ends_at).to_be_checked()
    flow.expect_ends("", "Budget")
    flow.field("source").fill("Bonus")
    flow.field("value").fill("20")
    flow.submit.click()
    flow.expect_gone()
    expect(editor.content).to_have_value(re.compile(r"^Bonus,Budget,20$", re.MULTILINE))


def test_an_existing_node_as_the_other_end_raises_no_hint_and_cancel_adds_nothing(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, charts = open_editor(page, live_server, api)
    before = editor.content.input_value()

    charts.click_bar("Food")
    flow = charts.flow_dialog
    flow.expect_open()
    flow.field("target").fill("Rent")
    expect(flow.hint("target")).to_have_text("")
    flow.cancel.click()

    flow.expect_gone()
    assert editor.content.input_value() == before


def test_a_click_on_a_link_does_not_open_the_dialog(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, charts = open_editor(page, live_server, api)
    flow = charts.flow_dialog

    charts.sankey_links.first.click(force=True)
    expect(flow.dialog).to_have_count(0)
    charts.click_bar("Utilities")

    flow.expect_open()
    expect(flow.title).to_have_text("Add a flow into Utilities")


def test_a_drag_of_a_bar_does_not_open_the_dialog(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, charts = open_editor(page, live_server, api)
    charts.watch_restyles()

    charts.drag_bar("Utilities", dy=-300)
    charts.wait_restyles(1)

    expect(editor.tid("chart-reset-order")).to_be_visible()
    expect(charts.flow_dialog.dialog).to_have_count(0)


def test_a_bar_of_a_fixed_chart_can_be_clicked_too(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(style={"arrangement": "fixed"})
    _, charts = open_editor(page, live_server, api, draft)

    charts.click_bar("Budget")

    flow = charts.flow_dialog
    flow.expect_open()
    expect(flow.title).to_have_text("Add a flow from Budget")


def test_a_hostile_node_name_is_text_in_the_title_the_field_and_the_radio(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    rows = [(HOSTILE, "Budget", "5"), ("Budget", "Rent", "5")]
    _, charts = open_editor(page, live_server, api, graph_draft(csv_text(rows)))

    charts.click_bar(HOSTILE)

    flow = charts.flow_dialog
    flow.expect_open()
    expect(flow.title).to_have_text(f"Add a flow from {HOSTILE}")
    expect(flow.field("source")).to_have_value(HOSTILE)
    expect(flow.starts_at.locator("xpath=..")).to_have_text(f"The new flow starts at {HOSTILE}")
    assert flow.dialog.locator("i").count() == 0
    assert page.evaluate("document.querySelectorAll('[onerror]').length") == 0
