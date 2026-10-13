"""The two colour pickers of the editor: the category swatches and the One colour field.

A real category row of "Totals by category" carries a colour input laid over its swatch; picking
a colour writes ``style.category_colors`` and the swatch follows the redrawn preview. The style
panel has a "One colour" picker that exists only in the One colour mode: filling it saves
``style.mono_color``, its reset button removes it again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, csv_text, unique_name
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_a_charts import ChartDom, rgb_of
from tests.e2e.support.ui_a_editor import EditorPage

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import Locator

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

RED = "#ff0000"
GREEN = "#12ab34"
#: Two real categories (Income, Housing) and one link without a category (Uncategorized).
MIXED = csv_text(
    [
        ("Salary", "Budget", 3000, "Income"),
        ("Budget", "Rent", 1200, "Housing"),
        ("Budget", "Savings", 1800, ""),
    ]
)


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def open_editor(page: WatchedPage, server: LiveServer, text: str) -> EditorPage:
    editor = EditorPage(page, server)
    editor.goto()
    editor.paste(text)
    return editor


def row_of(editor: EditorPage, category: str) -> Locator:
    return editor.tid("category-row").filter(has_text=category)


def swatch_of(editor: EditorPage, category: str) -> Locator:
    return row_of(editor, category).locator(".out-swatch")


def expect_link_fills(page: WatchedPage, color: str, *, drawn: bool = True) -> None:
    """Every Sankey link is (or, ``drawn=False``, is not) filled with ``color``.

    Retried per link: Plotly can finish restyling the links after the chart says it is ready.
    """
    links = ChartDom(page).sankey_links
    expect(links.first).to_be_attached()
    for link in links.all():
        if drawn:
            expect(link).to_have_css("fill", rgb_of(color))
        else:
            expect(link).not_to_have_css("fill", rgb_of(color))


# ------------------------------------------------------------------------------ category colours


def test_only_real_categories_get_a_colour_input_in_the_category_table(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = open_editor(page, live_server, MIXED)
    editor.open_donut()

    expect(editor.tid("category-row")).to_have_count(3)
    kinds = editor.tid("category-row").evaluate_all("els => els.map(e => e.dataset.kind)")
    assert sorted(kinds) == ["category", "category", "uncategorized"]
    expect(editor.tid("category-colour")).to_have_count(2)
    types = editor.tid("category-colour").evaluate_all("els => els.map(e => e.type)")
    assert types == ["color", "color"]
    expect(row_of(editor, "Uncategorized").get_by_test_id("category-colour")).to_have_count(0)
    expect(row_of(editor, "Housing").get_by_test_id("category-colour")).to_have_count(1)
    expect(row_of(editor, "Income").get_by_test_id("category-colour")).to_have_count(1)
    expect(row_of(editor, "Housing").get_by_test_id("category-colour")).to_have_attribute(
        "aria-label", "Change the colour of Housing"
    )


def test_picking_a_category_colour_recolours_the_swatch_and_marks_the_graph_unsaved(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor = open_editor(page, live_server, BUDGET_CATEGORISED.csv)
    editor.name_field.fill(unique_name("Picked colour"))
    graph_id = editor.save()
    expect(editor.save_status).to_have_attribute("data-state", "saved")
    editor.open_donut()
    expect(editor.tid("category-colour")).to_have_count(BUDGET_CATEGORISED.category_count)
    before = swatch_of(editor, "Housing").evaluate("el => getComputedStyle(el).backgroundColor")
    assert before != rgb_of(RED)

    row_of(editor, "Housing").get_by_test_id("category-colour").fill(RED)

    expect(swatch_of(editor, "Housing")).to_have_css("background-color", rgb_of(RED))
    expect(editor.save_status).to_have_attribute("data-state", "dirty")
    expect(editor.save_status).to_contain_text("Unsaved changes")
    others = {name for name in BUDGET_CATEGORISED.categories if name != "Housing"}
    for name in others:
        expect(swatch_of(editor, name)).not_to_have_css("background-color", rgb_of(RED))
    expect(row_of(editor, "Housing").get_by_test_id("category-colour")).to_have_value(RED)

    editor.save_button.click()
    expect(editor.save_status).to_contain_text("Revision 2")
    expect(editor.save_status).to_have_attribute("data-state", "saved")
    saved = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    assert saved["style"]["category_colors"] == {"Housing": RED}


def test_the_picked_category_colour_drives_the_legend_of_the_by_category_mode(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = open_editor(page, live_server, BUDGET_CATEGORISED.csv)
    editor.open_section("style")
    editor.tid("style-color-mode").select_option("category")
    editor.wait_preview()
    editor.open_donut()

    row_of(editor, "Food").get_by_test_id("category-colour").fill(RED)

    expect(swatch_of(editor, "Food")).to_have_css("background-color", rgb_of(RED))
    editor.wait_preview()
    expect(editor.tid("legend-item").filter(has_text="Food").locator(".out-swatch")).to_have_css(
        "background-color", rgb_of(RED)
    )
    editor.tid("chart-tab-sankey").click()
    editor.wait_preview()
    assert ChartDom(page).legend_colours()["Food"] == rgb_of(RED)


# ------------------------------------------------------------------------------ One colour


def test_the_one_colour_field_shows_only_in_the_mono_mode_and_saves_and_resets_the_colour(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor = open_editor(page, live_server, BUDGET.csv)
    editor.name_field.fill(unique_name("One colour"))
    graph_id = editor.save()
    editor.open_section("style")
    mode = editor.tid("style-color-mode")
    picker = editor.tid("style-mono-color")
    reset = editor.tid("style-mono-reset")
    expect(mode).to_have_value("node")
    expect(picker).to_be_hidden()
    expect(reset).to_be_hidden()

    mode.select_option("mono")
    editor.wait_preview()

    expect(picker).to_be_visible()
    expect(reset).to_be_visible()
    expect(reset).to_be_disabled()  # nothing saved yet: the palette colour applies

    picker.fill(GREEN)
    editor.wait_preview()

    expect(reset).to_be_enabled()
    expect(picker).to_have_value(GREEN)
    expect(editor.save_status).to_have_attribute("data-state", "dirty")
    expect_link_fills(page, GREEN)

    editor.save_button.click()
    expect(editor.save_status).to_have_attribute("data-state", "saved")
    saved = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    assert saved["style"]["mono_color"] == GREEN

    reset.click()
    editor.wait_preview()

    expect(reset).to_be_disabled()
    expect(picker).to_be_visible()
    expect(editor.save_status).to_have_attribute("data-state", "dirty")
    expect_link_fills(page, GREEN, drawn=False)

    mode.select_option("node")
    expect(picker).to_be_hidden()
    expect(reset).to_be_hidden()
