"""The display menu of the viewer, part 2: the donut switches, the exports, the saved graph.

The percentage and value switches change the text on every slice (the name stays only with four
slices or fewer), the switches start from the saved style and are sent as query parameters of the
render request and of every download, nothing the person switches changes the saved graph, and the
editor's own options (the renamed Sankey option, the new donut "Show values") feed the same
switches. The icon, the panel and the Sankey switch are in ``test_viewer_display_ui.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET_CATEGORISED, csv_text, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_a_charts import ChartDom
from tests.e2e.support.ui_a_display import (
    DONUT_PERCENT,
    DONUT_VALUE,
    NODE_VALUES,
    DisplayMenu,
    RequestLog,
)
from tests.e2e.support.ui_a_downloads import download
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_seed import SavedGraph, save_graph
from tests.e2e.support.ui_a_viewer import ViewerPage
from tests.e2e.support.uiwait import wait_chart, wait_preview

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: Three categories: few enough slices for the name to stay on each slice.
FEW = csv_text(
    [
        ("Salary", "Budget", 3000, "Income"),
        ("Budget", "Rent", 1200, "Housing"),
        ("Budget", "Food", 800, "Living"),
    ]
)
PERCENTS = ["46.1%", "17.8%", "17.7%", "15.5%", "2.79%"]
VALUES = ["3,800", "1,470", "1,460", "1,280", "230"]
LEGEND = ["Income", "Savings", "Housing", "Food", "Transport"]
CHOSEN = {"node_values": "true", "donut_percent": "false", "donut_value": "true"}
SAVED_STYLE = {"show_values_in_labels": True, "donut": {"show_percent": False, "show_value": True}}


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def saved(module_server: LiveServer) -> SavedGraph:
    return save_graph(module_server, "Display donut")


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, saved: SavedGraph) -> ViewerPage:
    viewer = ViewerPage(page, live_server)
    viewer.open(saved.id)
    return viewer


# ------------------------------------------------------------------------------ the donut


def test_the_percent_and_value_switches_change_the_text_on_every_slice_of_a_big_donut(
    viewer: ViewerPage,
) -> None:
    menu, charts, log = DisplayMenu(viewer), ChartDom(viewer.page), RequestLog(viewer.page)
    viewer.open_donut()
    expect(charts.donut_texts).to_have_text(PERCENTS)  # the default: the percentage, no name
    menu.open()

    menu.set(DONUT_VALUE, True)
    expect(charts.donut_slice(0).locator("tspan")).to_have_text(["46.1%", "3,800"])
    expect(charts.donut_texts).to_have_count(len(PERCENTS))
    assert log.last("render") == {"theme": "light", "donut_value": "true"}

    menu.set(DONUT_PERCENT, False)
    expect(charts.donut_texts).to_have_text(VALUES)
    assert log.last("render") == {"theme": "light", "donut_value": "true", "donut_percent": "false"}

    menu.set(DONUT_VALUE, False)
    expect(charts.donut_texts).to_have_count(0)  # neither: the slices are bare
    expect(viewer.page.locator("[data-testid=donut-chart] .legendtext")).to_have_text(LEGEND)
    assert charts.donut_center() == "8,240"

    menu.set(DONUT_PERCENT, True)
    expect(charts.donut_texts).to_have_text(PERCENTS)
    assert log.last("render")["donut_percent"] == "true"
    assert log.last("render")["donut_value"] == "false"


def test_with_four_slices_or_fewer_the_name_stays_on_the_slice(
    page: WatchedPage, live_server: LiveServer
) -> None:
    few = save_graph(live_server, "Few slices", FEW)
    viewer = ViewerPage(page, live_server)
    viewer.open(few.id)
    menu, charts = DisplayMenu(viewer), ChartDom(page)
    viewer.open_donut()
    expect(charts.donut_slice(0).locator("tspan")).to_have_text(["Income", "60%"])
    menu.open()

    menu.set(DONUT_VALUE, True)
    expect(charts.donut_slice(0).locator("tspan")).to_have_text(["Income", "60%", "3,000"])

    menu.set(DONUT_PERCENT, False)
    expect(charts.donut_slice(0).locator("tspan")).to_have_text(["Income", "3,000"])

    menu.set(DONUT_VALUE, False)
    expect(charts.donut_slice(0)).to_have_text("Income")
    expect(charts.donut_texts).to_have_text(["Income", "Housing", "Living"])


# ------------------------------------------------------------------------------ the saved style


def test_the_switches_start_from_the_saved_style_and_the_first_render_asks_for_nothing_extra(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(BUDGET_CATEGORISED.csv, style=SAVED_STYLE)
    graph = seed_graph(api, unique_name("Saved switches"), draft)
    viewer = ViewerPage(page, live_server)
    log = RequestLog(page)
    viewer.open(graph["id"])
    menu, charts = DisplayMenu(viewer), ChartDom(page)

    menu.open()

    expect(menu.switch(NODE_VALUES)).to_be_checked()
    expect(menu.switch(DONUT_PERCENT)).not_to_be_checked()
    expect(menu.switch(DONUT_VALUE)).to_be_checked()
    expect(charts.node_label("Salary").locator("tspan")).to_have_text(["Salary", "3,000"])
    assert log.queries("render") == [{"theme": "light"}]  # nothing chosen yet, nothing sent
    viewer.open_donut()  # a press on the tab closed the panel
    expect(charts.donut_texts).to_have_text(VALUES)
    menu.open()
    menu.set(DONUT_PERCENT, True)  # only the touched switch is sent
    assert log.last("render") == {"theme": "light", "donut_percent": "true"}
    expect(charts.donut_slice(0).locator("tspan")).to_have_text(["46.1%", "3,800"])


def test_the_switches_never_change_the_saved_graph_and_a_reload_starts_from_it_again(
    page: WatchedPage, viewer: ViewerPage, saved: SavedGraph, api: httpx.Client
) -> None:
    before = json_of(api.get(f"/api/v1/graphs/{saved.id}"))
    menu, charts = DisplayMenu(viewer), ChartDom(page)
    menu.open()
    menu.set(NODE_VALUES, True)
    menu.set(DONUT_PERCENT, False)
    menu.set(DONUT_VALUE, True)

    assert json_of(api.get(f"/api/v1/graphs/{saved.id}")) == before
    assert before["style"]["show_values_in_labels"] is False
    assert before["style"]["donut"]["show_percent"] is True
    assert before["style"]["donut"]["show_value"] is False
    page.reload()
    wait_chart(page)
    menu.open()

    expect(menu.switch(NODE_VALUES)).not_to_be_checked()
    expect(menu.switch(DONUT_PERCENT)).to_be_checked()
    expect(menu.switch(DONUT_VALUE)).not_to_be_checked()
    expect(charts.node_label("Salary")).to_have_text("Salary")
    assert json_of(api.get(f"/api/v1/graphs/{saved.id}")) == before


# ------------------------------------------------------------------------------ the downloads


def test_every_download_of_the_sankey_carries_the_switches(viewer: ViewerPage) -> None:
    menu, log, page = DisplayMenu(viewer), RequestLog(viewer.page), viewer.page
    menu.open()
    for testid, on in ((NODE_VALUES, True), (DONUT_PERCENT, False), (DONUT_VALUE, True)):
        menu.set(testid, on)
    files = {}

    for button in ("export-json", "export-csv", "export-html", "export-sankey-svg"):
        files[button] = download(page, viewer.tid(button))
        query = log.last("export")
        assert CHOSEN.items() <= query.items(), button
        assert query["chart"] == "sankey"

    figure = json.loads(files["export-json"].text)
    assert "Salary<br>3,000" in figure["data"][0]["node"]["label"]
    assert "3,000" in files["export-sankey-svg"].text


def test_every_download_of_the_donut_carries_the_switches(viewer: ViewerPage) -> None:
    menu, log, page = DisplayMenu(viewer), RequestLog(viewer.page), viewer.page
    viewer.open_donut()
    menu.open()
    for testid, on in ((DONUT_PERCENT, False), (DONUT_VALUE, True)):
        menu.set(testid, on)

    json_file = download(page, viewer.tid("export-json"))
    assert log.last("export")["chart"] == "donut"
    assert {"donut_percent": "false", "donut_value": "true"}.items() <= log.last("export").items()
    pie = json.loads(json_file.text)["data"][0]
    assert pie["textinfo"] == "text"
    assert pie["text"][0] == "3,800"
    svg = download(page, viewer.tid("export-donut-svg"))
    assert {"donut_percent": "false", "donut_value": "true"}.items() <= log.last("export").items()
    assert "3,800" in svg.text


# ------------------------------------------------------------------------------ the editor


def test_the_editor_options_feed_the_viewer_switches(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(BUDGET_CATEGORISED.csv)
    editor.name_field.fill(unique_name("Editor display"))
    editor.open_section("style")
    expect(page.get_by_label("Show values in node labels")).to_have_count(0)  # renamed
    charts = ChartDom(page)

    page.get_by_label("Show values under the node names").check()
    editor.wait_preview()
    expect(charts.node_label("Salary").locator("tspan")).to_have_text(["Salary", "3,000"])
    editor.open_donut()
    page.get_by_label("Show values", exact=True).check()
    wait_preview(page, "donut-chart")
    expect(charts.donut_slice(0).locator("tspan")).to_have_text(["46.1%", "3,800"])
    graph_id = editor.save()

    style = json_of(api.get(f"/api/v1/graphs/{graph_id}"))["style"]
    assert style["show_values_in_labels"] is True
    assert style["donut"]["show_value"] is True
    assert style["donut"]["show_percent"] is True
    viewer = ViewerPage(page, live_server)
    viewer.open(graph_id)
    DisplayMenu(viewer).open()
    expect(viewer.tid(NODE_VALUES)).to_be_checked()
    expect(viewer.tid(DONUT_PERCENT)).to_be_checked()
    expect(viewer.tid(DONUT_VALUE)).to_be_checked()
