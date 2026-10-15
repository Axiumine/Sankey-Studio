"""B3, part 2: the donut that categories bring, link colours by category, folding, persistence.

The donut (labels with percent, centre total, hover tooltip, legend, the category table that
mirrors it), the colour mode "category" that recolours the Sankey links and fills the legend,
more categories than hues folding into ``Other``, and the round trip save -> reload -> viewer.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, csv_text, unique_name
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_a_charts import ChartDom
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_entries import EntriesPanel
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: The budget with a category on four of nine rows: Housing 1,200, Living 1,280, the rest none.
PARTLY = csv_text(
    [
        ("Salary", "Budget", 3000, ""),
        ("Freelance", "Budget", 800, ""),
        ("Budget", "Rent", 1200, "Housing"),
        ("Budget", "Utilities", 260, ""),
        ("Budget", "Food", 640, "Living"),
        ("Budget", "Transport", 230, ""),
        ("Budget", "Savings", 1470, ""),
        ("Food", "Groceries", 500, "Living"),
        ("Food", "Restaurants", 140, "Living"),
    ]
)
PARTLY_LABELS = ["Living15.5%", "Housing14.6%", "Uncategorized69.9%"]
MANY_LABELS = ["46.1%", "17.8%", "17.7%", "15.5%", "2.79%"]
TWELVE = csv_text([(f"Src{i}", f"Dst{i}", 10 + i, f"Cat{i}") for i in range(12)])
HUES = 8


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def open_editor(page: WatchedPage, server: LiveServer, text: str) -> EditorPage:
    editor = EditorPage(page, server)
    editor.goto()
    editor.paste(text)
    return editor


def links_per_category(text: str) -> Counter[str]:
    rows = list(csv.DictReader(io.StringIO(text)))
    return Counter(row["category"] for row in rows)


# ------------------------------------------------------------------------------ the donut


def test_the_donut_has_percent_labels_a_centre_total_a_tooltip_a_legend_and_a_table(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = open_editor(page, live_server, PARTLY)

    editor.open_donut()

    charts = ChartDom(page)
    expect(charts.donut_slices).to_have_count(3)
    assert charts.donut_labels() == PARTLY_LABELS
    assert charts.donut_center() == "8,240"
    assert charts.hover_slice(0) == "Living1,280 (15.5%)"
    expect(editor.tid("category-table").locator("tfoot")).to_have_text("Total8,240100%")
    expect(editor.tid("category-row")).to_have_text(
        ["Living1,28015.5%", "Housing1,20014.6%", "Uncategorized5,76069.9%"]
    )
    expect(editor.tid("sankey-chart")).to_be_hidden()
    editor.open_export()
    expect(editor.tid("export-donut-svg")).to_be_enabled()

    # More than four categories: the slices carry the percentage only (the name is in the legend
    # and the table), never the name.
    editor.paste(BUDGET_CATEGORISED.csv)

    legend = page.locator("[data-testid=donut-chart] .legendtext")
    expect(legend).to_have_text(["Income", "Savings", "Housing", "Food", "Transport"])
    expect(editor.tid("category-row")).to_have_count(5)
    assert charts.donut_labels() == MANY_LABELS
    assert charts.donut_center() == "8,240"
    assert "Transport230 (2.79%)" in charts.hover_slice(4)
    editor.expect_stats(nodes=10, links=9, total_in=3800, total_out=3800, columns=4, categories=5)

    # The categories of the data column fill the entries table and its suggestions, and a single
    # choice for one entry overrides the data for that entry only.
    entries = EntriesPanel(page)
    entries.expect_categories(
        {
            ("Budget", "Rent"): "Housing",
            ("Budget", "Food"): "Food",
            ("Salary", "Budget"): "Income",
        }
    )
    entries.expect_datalist(sorted(BUDGET_CATEGORISED.categories))
    entries.set_category("Budget", "Rent", "Home")
    expect(entries.cell("Budget", "Rent")).to_have_value("Home")
    expect(entries.cell("Budget", "Utilities")).to_have_value("Housing")


# ------------------------------------------------------------------------------ colours and folding


def test_link_colours_by_category_recolour_the_sankey_and_extra_categories_fold_into_other(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = open_editor(page, live_server, BUDGET.csv)
    editor.open_section("style")
    mode = editor.tid("style-color-mode")
    expect(mode.locator("option[value=category]")).to_have_count(0)  # no categories, no such mode

    editor.paste(BUDGET_CATEGORISED.csv)

    expect(mode.locator("option")).to_have_count(4)
    charts = ChartDom(page)
    by_node = Counter(charts.link_fills())
    expect(editor.tid("legend-item")).to_have_count(0)
    editor.open_section("style")  # the chart settings popover closes when the page is used
    mode.select_option("category")
    editor.wait_preview()

    expect(editor.tid("legend-item")).to_have_count(BUDGET_CATEGORISED.category_count)
    colours = charts.legend_colours()
    assert sorted(colours) == sorted(BUDGET_CATEGORISED.categories)
    assert len(set(colours.values())) == BUDGET_CATEGORISED.category_count
    expect(charts.sankey_legend_labels).to_have_count(0)  # the legend list says it, once
    fills = Counter(charts.link_fills())
    assert fills != by_node
    for category, links in links_per_category(BUDGET_CATEGORISED.csv).items():
        assert fills[colours[category]] == links, f"links of {category}"
    assert sum(fills.values()) == BUDGET_CATEGORISED.links
    expect(editor.tid("legend-item").first).to_contain_text("3,800")

    # Twelve categories: eight hues at most, the rest is folded into Other (legend and donut).
    editor.paste(TWELVE)

    editor.expect_stats(nodes=24, links=12, total_in=186, total_out=186, columns=2, categories=12)
    colours = charts.legend_colours()
    assert "Other" in colours
    assert len(colours) <= HUES + 1
    assert len(set(charts.link_fills())) <= HUES + 1
    editor.open_donut()
    kinds = editor.tid("category-row").evaluate_all("els => els.map(e => e.dataset.kind)")
    assert kinds.count("other") == 1
    assert kinds[-1] == "other"
    assert kinds.count("category") <= HUES
    expect(editor.tid("category-row").last).to_contain_text("Other")
    expect(charts.donut_slices).to_have_count(len(kinds))


# ------------------------------------------------------------------------------ persistence


def test_categories_and_rules_survive_save_reload_and_show_in_the_viewer(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor = open_editor(page, live_server, BUDGET.csv)
    entries = EntriesPanel(page)
    name = unique_name("Categorised budget")
    editor.set_name(name)
    entries.set_category("Budget", "Rent", "Housing")
    entries.search("Food")
    entries.bulk_categorise("Living")
    editor.expect_toast("Rule added", "success")
    entries.search("")
    expect(entries.cell("Food", "Groceries")).to_have_value("Living")
    graph_id = editor.save()

    saved = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    # the typed category is written into the pasted data (write-through), not kept as an override
    assert saved["transform"].get("entry_categories", []) == []
    assert "Budget,Rent,1200,Housing" in saved["source"]["content"].splitlines()
    assert [(r["pattern"], r["category"]) for r in saved["transform"]["category_rules"]] == [
        ("*Food*", "Living")
    ]
    reopened = editor.reopened()
    page.reload()
    reopened.expect_ready()
    expect(reopened.tid("chart-tab-donut")).to_be_visible()
    expect(reopened.tid("section-transform")).to_contain_text("1 category rule")
    EntriesPanel(page).expect_categories(
        {("Budget", "Rent"): "Housing", ("Food", "Restaurants"): "Living", ("Salary", "Budget"): ""}
    )

    viewer = ViewerPage(page, live_server)
    viewer.open(graph_id)
    viewer.open_donut()
    charts = ChartDom(page)
    assert charts.donut_labels() == PARTLY_LABELS
    assert charts.donut_center() == "8,240"
    expect(viewer.tid("category-row")).to_have_count(3)
