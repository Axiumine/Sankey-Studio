"""B5, part 2: reading pasted text: format detection, column mapping, the category column, bad rows.

The "How to read the data" block: automatic format detection (CSV with another delimiter, TSV,
JSON), the four column selects, the header checkbox, the "no category column" switch, columns that
need a pick, and rows the server skips (reported with their line numbers while the rest draws).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_sources import SourcePanel

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

UNNAMED = "a,b,c,d\nSalary,Budget,3000,1\nBudget,Rent,1200,2\nBudget,Food,640,3\n"
BAD_ROWS = (
    "source,target,value\nSalary,Budget,3000\nBudget,Rent,abc\nBudget,Food,-5\n"
    "Budget,,10\nBudget,Savings,200\n"
)
JSON_TEXT = (
    '[{"source":"A","target":"B","value":5,"category":"X"},{"source":"B","target":"C","value":5}]'
)


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    return editor


@pytest.fixture
def source(page: WatchedPage) -> SourcePanel:
    return SourcePanel(page)


def allow_unmapped_source(page: WatchedPage) -> None:
    # A source the server cannot read yet is a 422 on the preview and on the entries list.
    page.allow_http(422, "/api/v1/preview")
    page.allow_http(422, "/api/v1/entries")


# ------------------------------------------------------------------------------ columns


def step_unknown_headers_need_picks(editor: EditorPage, source: SourcePanel) -> None:
    allow_unmapped_source(editor.page)

    editor.fill_source(UNNAMED)
    editor.wait_settled()

    expect(editor.tid("state-error").first).to_be_visible()
    expect(editor.tid("section-source")).to_contain_text("1 problem")
    message = "No column is chosen yet for source, target, value."
    expect(editor.page.get_by_text(message)).to_be_visible()
    source.expect_columns(source="", target="", value="", category="")

    source.pick_column("source", "a")
    source.pick_column("target", "b")
    source.pick_column("value", "c")
    editor.wait_preview()

    editor.expect_stats(nodes=4, links=3, total_in=3000, total_out=1840, columns=3)
    expect(editor.tid("state-error")).to_have_count(0)
    source.pick_column("value", "d")
    editor.wait_preview()
    editor.expect_stats(nodes=4, links=3, total_in=1, total_out=5, columns=3)


def step_category_column_is_found_and_the_switch_turns_it_off(
    editor: EditorPage, source: SourcePanel
) -> None:
    editor.paste(BUDGET_CATEGORISED.csv)

    source.expect_columns(source="", target="", value="", category="")
    expect(source.column("category").locator("option").first).to_have_text("Auto (category)")
    expect(source.column("value").locator("option").first).to_have_text("Auto (value)")
    expect(editor.tid("chart-tab-donut")).to_be_visible()
    expect(source.tid("source-no-category-switch")).not_to_be_checked()
    editor.expect_stats(nodes=10, links=9, total_in=3800, total_out=3800, columns=4, categories=5)

    source.tid("source-no-category-switch").check()
    editor.wait_preview()

    expect(editor.tid("chart-tab-donut")).to_have_count(0)
    expect(editor.tid("donut-hint")).to_be_visible()
    expect(source.column("category")).to_be_disabled()
    editor.expect_stats(nodes=10, links=9, total_in=3800, total_out=3800, columns=4)

    source.tid("source-no-category-switch").uncheck()
    editor.wait_preview()

    expect(source.column("category")).to_be_enabled()
    expect(editor.tid("chart-tab-donut")).to_be_visible()


def step_a_text_without_a_header_row_numbers_its_columns(
    editor: EditorPage, source: SourcePanel
) -> None:
    editor.fill_source(BUDGET.csv.split("\n", 1)[1])
    editor.wait_settled()
    expect(source.tid("source-has-header")).to_be_checked()
    expect(editor.tid("section-source")).to_contain_text("1 problem")

    source.tid("source-has-header").uncheck()
    editor.wait_preview()

    editor.expect_stats(nodes=10, links=9, total_in=3800, total_out=3800, columns=4)
    expect(editor.tid("section-source")).not_to_contain_text("1 problem")
    source.expect_options("value", ["Auto (col 3)", "Column 1", "Column 2", "Column 3"])


def test_columns_are_picked_the_category_column_is_optional_and_a_headerless_text_is_numbered(
    editor: EditorPage, source: SourcePanel
) -> None:
    step_unknown_headers_need_picks(editor, source)
    step_category_column_is_found_and_the_switch_turns_it_off(editor, source)
    step_a_text_without_a_header_row_numbers_its_columns(editor, source)


# ------------------------------------------------------------------------------ formats


def test_bad_rows_are_listed_with_line_numbers_and_every_format_is_detected(
    editor: EditorPage, source: SourcePanel
) -> None:
    editor.paste(BAD_ROWS)

    editor.expect_stats(nodes=3, links=2, total_in=3000, total_out=200, columns=3)
    expect(editor.tid("warnings")).to_be_visible()
    expect(editor.tid("warning-item")).to_have_text(
        [
            "inline:3: value must be a positive number",
            "inline:4: value must be a positive number",
            "inline:5: target is empty",
        ]
    )
    expect(editor.tid("state-error")).to_have_count(0)

    editor.paste("source\ttarget\tvalue\nA\tB\t5\nB\tC\t5\n")
    expect(editor.tid("warning-item")).to_have_count(0)
    expect(editor.tid("warnings")).to_be_hidden()
    expect(editor.page.get_by_text("Detected: TSV")).to_be_visible()
    editor.expect_stats(nodes=3, links=2, total_in=5, total_out=5, columns=3)

    editor.paste(JSON_TEXT)
    expect(editor.page.get_by_text("Detected: JSON")).to_be_visible()
    editor.expect_stats(nodes=3, links=2, total_in=5, total_out=5, columns=3, categories=1)

    allow_unmapped_source(editor.page)
    source.tid("source-format").select_option("csv")
    editor.wait_settled()
    expect(editor.tid("section-source")).to_contain_text("1 problem")

    source.tid("source-format").select_option("auto")
    editor.wait_preview()
    expect(editor.tid("section-source")).not_to_contain_text("1 problem")
    editor.expect_stats(nodes=3, links=2, total_in=5, total_out=5, columns=3, categories=1)
