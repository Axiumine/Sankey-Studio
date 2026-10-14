"""B2: draw a graph from pasted CSV without categories (UI.md flows F1 and F3).

Live preview, stats that match the drawn chart, the optional donut (a hint, never an error),
saving (needs a name), the address after the first save, persistence after a reload, the viewer
and the library. Every test uses its own graph name, so one server serves the whole module.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, LAYERED, unique_name
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_a_charts import ChartDom
from tests.e2e.support.ui_a_editor import EditGraphPage, EditorPage
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    return editor


def graphs_named(api: httpx.Client, name: str) -> list[dict[str, object]]:
    """The saved graphs whose name, description or tags match ``name`` (the library search)."""
    page = json_of(api.get("/api/v1/graphs", params={"q": name}))
    return [item for item in page["items"] if item["name"] == name]


# ------------------------------------------------------------------------------ steps


def expect_budget_drawn(editor: EditorPage) -> ChartDom:
    """The pasted budget is drawn and every number on the page agrees with the data."""
    editor.expect_stats(
        nodes=BUDGET.nodes,
        links=BUDGET.links,
        total_in=BUDGET.total,
        total_out=BUDGET.total,
        columns=BUDGET.layers,
    )
    charts = ChartDom(editor.page)
    charts.expect_counts(BUDGET.nodes, BUDGET.links)
    expect(editor.tid("entries-total")).to_have_text(f"{BUDGET.links} entries")
    expect(editor.tid("entries-row")).to_have_count(BUDGET.links)
    expect(editor.tid("source-format")).to_have_value("auto")
    expect(editor.page.get_by_text("Detected: CSV")).to_be_visible()
    expect(editor.tid("warnings")).to_be_hidden()
    expect(editor.tid("warning-item")).to_have_count(0)
    expect(editor.tid("state-error")).to_have_count(0)
    return charts


def expect_donut_is_only_a_hint(editor: EditorPage) -> None:
    """No categories: the donut is an optional hint, never an error."""
    expect(editor.tid("chart-tab-donut")).to_have_count(0)
    hint = editor.tid("donut-hint")
    expect(hint).to_contain_text("No donut yet")
    expect(hint).to_contain_text("Categories are optional")
    expect(editor.tid("legend-item")).to_have_count(0)
    expect(editor.tid("source-column-category")).to_contain_text("Auto (none found)")
    hint.get_by_role("button", name="Go to entries").click()
    expect(editor.tid("entries-search")).to_be_focused()
    editor.open_export()  # last: the open popover would cover the hint
    expect(editor.tid("export-donut-svg")).to_be_disabled()
    expect(editor.tid("export-donut-png")).to_be_disabled()


def expect_a_cycle_to_be_refused_until_broken(editor: EditorPage) -> None:
    """A cycle is the server's refusal, shown above the last good chart, until it is broken."""
    editor.page.allow_http(422, "/api/v1/preview")
    editor.page.allow_http(422, "/api/v1/entries")
    editor.fill_source("source,target,value\nStart,A,4\nA,B,5\nB,C,3\nC,A,2\n")
    editor.open_section("transform")
    expect(editor.tid("section-transform")).to_contain_text("1 problem")
    alert = editor.page.get_by_role("alert").filter(has_text="The graph could not be built")
    expect(alert).to_contain_text("The links form a cycle: A -> B -> C -> A.")

    editor.tid("transform-on-cycle").select_option("break")
    editor.wait_preview()

    expect(editor.tid("section-transform")).not_to_contain_text("1 problem")
    editor.expect_stats(nodes=4, links=3, total_in=4, total_out=3, columns=4)
    expect(editor.tid("warning-item").first).to_contain_text("cycle")


def expect_a_name_is_required_and_a_dirty_editor_asks(
    editor: EditorPage, api: httpx.Client
) -> None:
    before = json_of(api.get("/api/v1/graphs"))["total"]
    address = editor.page.url
    emptied = editor.open_details()  # the wizard gave the graph a name: take it away again
    emptied.fill(name="")
    emptied.dismiss()
    expect(editor.heading).to_have_text("New graph")

    editor.save_button.click()

    details = editor.tid("details-dialog")
    expect(details).to_be_visible()
    expect(details.get_by_text("Give the graph a name so you can find it later.")).to_be_visible()
    assert editor.page.url == address
    expect(editor.save_status).to_have_text("Give the graph a name before saving.")
    assert json_of(api.get("/api/v1/graphs"))["total"] == before

    editor.name_field.fill("A name that is not saved")
    editor.tid("details-done").click()
    expect(details).to_be_hidden()
    expect(editor.heading).to_have_text("New graph: A name that is not saved")
    editor.nav("library").click()
    dialog = editor.tid("confirm-dialog")
    expect(dialog).to_contain_text("Leave without saving?")
    dialog.get_by_role("button", name="Stay and keep editing").click()
    expect(dialog).to_be_hidden()
    editor.expect_name("A name that is not saved")
    assert editor.page.url == address


def expect_the_saved_graph_to_persist(
    editor: EditorPage, graph_id: str, api: httpx.Client
) -> EditGraphPage:
    """Reload the edit address: everything typed is back, nothing categorised is stored."""
    editor.page.reload()
    reopened = editor.reopened()
    reopened.expect_ready()
    reopened.expect_details(description="pasted from a spreadsheet", tags=("qa-draw",))
    expect(reopened.content).to_have_value(BUDGET.csv)
    expect(reopened.save_status).to_contain_text("All changes saved")
    reopened.expect_stats(nodes=10, links=9, total_in=3800, total_out=3800, columns=4)
    stored = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    assert stored["tags"] == ["qa-draw"]
    assert stored["source"]["content"] == BUDGET.csv
    assert stored["transform"]["entry_categories"] == []
    assert stored["transform"]["category_rules"] == []
    bundle = json_of(api.get(f"/api/v1/graphs/{graph_id}/render"))
    assert bundle["donut_available"] is False
    assert bundle["stats"]["category_count"] == 0
    return reopened


# ------------------------------------------------------------------------------ tests


def test_pasting_csv_draws_a_live_preview_whose_counts_match_and_edits_redraw_it(
    editor: EditorPage, api: httpx.Client
) -> None:
    before = json_of(api.get("/api/v1/graphs"))["total"]
    expect(editor.heading).to_have_text(f"New graph: {editor.wizard_name}")
    expect(editor.save_status).to_have_text("Not saved yet")
    expect(editor.tid("source-tab-paste")).to_have_attribute("aria-selected", "true")
    expect(editor.tid("state-empty").first).to_contain_text("Nothing to draw yet")
    expect(editor.tid("sankey-chart")).to_be_hidden()
    expect(editor.tid("view-graph")).to_be_hidden()

    editor.paste(BUDGET.csv)
    charts = expect_budget_drawn(editor)
    expect_donut_is_only_a_hint(editor)

    editor.paste(LAYERED.csv)
    editor.expect_stats(
        nodes=LAYERED.nodes,
        links=LAYERED.links,
        total_in=LAYERED.total,
        total_out=LAYERED.total,
        columns=LAYERED.layers,
    )
    charts.expect_counts(LAYERED.nodes, LAYERED.links)
    labels = charts.node_labels()
    assert "M1" in labels
    assert "Salary" not in labels

    expect_a_cycle_to_be_refused_until_broken(editor)

    # Nothing was saved: leaving asks first and, when confirmed, throws the draft away.
    editor.nav("library").click()
    editor.tid("confirm-dialog").get_by_role("button", name="Leave without saving").click()
    editor.page.wait_for_url(re.compile(r"/$"))
    assert json_of(api.get("/api/v1/graphs"))["total"] == before


def test_a_saved_graph_needs_a_name_persists_and_opens_in_the_viewer_and_the_library(
    editor: EditorPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor.set_details(description="pasted from a spreadsheet", tags=("qa-draw",))
    editor.paste(BUDGET.csv)
    expect_a_name_is_required_and_a_dirty_editor_asks(editor, api)
    name = unique_name("Persisted")
    editor.set_name(name)

    graph_id = editor.save()

    assert re.fullmatch(r"[0-9a-f]{32}", graph_id)
    expect(editor.save_status).to_contain_text("Revision 1")
    expect(editor.heading).to_have_text(f"Edit {name}")
    expect(editor.tid("view-graph")).to_have_attribute("href", f"/graphs/{graph_id}")
    expect(editor.save_button).to_be_focused()
    assert [item["id"] for item in graphs_named(api, name)] == [graph_id]

    reopened = expect_the_saved_graph_to_persist(editor, graph_id, api)
    reopened.expect_name(name)
    reopened.tid("view-graph").click()
    viewer = ViewerPage(editor.page, live_server)
    viewer.expect_ready()
    expect(viewer.heading).to_have_text(name)
    expect(viewer.tid("chart-tab-donut")).to_have_count(0)
    expect(viewer.tid("donut-hint")).to_be_visible()
    ChartDom(editor.page).expect_counts(BUDGET.nodes, BUDGET.links)
    expect(viewer.tid("links-table")).not_to_have_attribute("open", "")

    viewer.nav("library").click()
    editor.page.wait_for_url(live_server.url_for("/"))
    editor.tid("library-search").fill(name)
    card = editor.tid("graph-card").filter(has_text=name)
    expect(card).to_have_count(1)
    expect(card).to_contain_text("qa-draw")
