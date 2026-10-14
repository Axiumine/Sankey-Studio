"""B5, part 3: the Manual tab: links typed, pasted, added, removed and categorised in a table.

Rows are drawn only when source, target and a value above 0 are filled, cells explain what is
wrong with them, a spreadsheet paste fills many cells, and two links on one source -> target pair
are ONE entry whose category lands on both links (also in the saved graph).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_a_editor import EditGraphPage, EditorPage
from tests.e2e.support.ui_a_entries import EntriesPanel
from tests.e2e.support.ui_a_manual import ManualTable
from tests.e2e.support.ui_a_sources import SourcePanel

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

SAME_PAIR = "Same source and target as another row: they add up to one entry"
NOT_DRAWN = "Not drawn yet"
RESERVED = "Uncategorized and Other are reserved names. Pick another category."


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    SourcePanel(page).open_tab("manual")
    return editor


@pytest.fixture
def table(page: WatchedPage) -> ManualTable:
    return ManualTable(page)


def step_cells_explain_what_is_wrong(editor: EditorPage, table: ManualTable) -> None:
    table.expect_values([("", "", "", "")])
    expect(editor.tid("sankey-chart")).to_be_hidden()
    expect(editor.tid("stats")).to_be_hidden()

    table.fill_row(1, ("Salary", "Budget", "abc"))

    table.expect_field_errors(["Use a number above 0."])
    expect(table.flag(1, NOT_DRAWN)).to_be_visible()
    expect(editor.tid("sankey-chart")).to_be_hidden()

    table.cell("Value", 1).fill("3000")
    editor.wait_preview()
    editor.expect_stats(nodes=2, links=1, total_in=3000, total_out=3000, columns=2)
    expect(table.flag(1, NOT_DRAWN)).to_be_hidden()

    table.cell("Category (optional)", 1).fill("Other")
    table.expect_field_errors([RESERVED])
    table.cell("Category (optional)", 1).fill("Income")
    table.expect_field_errors([])


def step_only_complete_rows_are_drawn_and_rows_can_be_removed(
    editor: EditorPage, table: ManualTable
) -> None:
    table.add_row()
    table.cell("Source", 2).fill("Budget")
    expect(table.flag(2, NOT_DRAWN)).to_be_visible()
    expect(editor.page.get_by_text("1 of 2 rows drawn")).to_be_visible()
    editor.expect_stats(nodes=2, links=1, total_in=3000, total_out=3000, columns=2, categories=1)
    table.cell("Target", 2).fill("Rent")
    table.cell("Value", 2).fill("1200")
    editor.wait_preview()
    editor.expect_stats(nodes=3, links=2, total_in=3000, total_out=1200, columns=3, categories=1)

    table.remove_row(1)

    table.expect_values([("Budget", "Rent", "1200", "")])
    editor.wait_preview()
    editor.expect_stats(nodes=2, links=1, total_in=1200, total_out=1200, columns=2)


def step_rows_are_pasted_from_a_spreadsheet_and_from_csv_text(
    editor: EditorPage, table: ManualTable
) -> None:
    table.paste_cells("Source", 1, "Budget\tRent\t1200\tX\nRent\tFood\t400\t\nFood\tBin\t100\tX")
    table.expect_values(
        [("Budget", "Rent", "1200", "X"), ("Rent", "Food", "400", ""), ("Food", "Bin", "100", "X")]
    )
    editor.wait_preview()
    editor.expect_stats(nodes=4, links=3, total_in=1200, total_out=100, columns=4, categories=1)

    table.paste_rows_dialog("source,target,value,category\nBin,Out,50,Y\nOut,Last,25,")

    editor.expect_toast("The first row was skipped because it looks like a header.", "info")
    table.expect_values(
        [
            ("Budget", "Rent", "1200", "X"),
            ("Rent", "Food", "400", ""),
            ("Food", "Bin", "100", "X"),
            ("Bin", "Out", "50", "Y"),
            ("Out", "Last", "25", ""),
        ]
    )
    editor.wait_preview()
    editor.expect_stats(nodes=6, links=5, total_in=1200, total_out=25, columns=6, categories=2)


def test_cells_explain_what_is_wrong_and_rows_are_added_removed_and_pasted(
    editor: EditorPage, table: ManualTable
) -> None:
    step_cells_explain_what_is_wrong(editor, table)
    step_only_complete_rows_are_drawn_and_rows_can_be_removed(editor, table)
    step_rows_are_pasted_from_a_spreadsheet_and_from_csv_text(editor, table)


def test_two_links_on_one_pair_are_one_entry_and_a_category_applies_to_both(
    editor: EditorPage, table: ManualTable, api: httpx.Client
) -> None:
    entries = EntriesPanel(editor.page)
    editor.set_name(unique_name("Manual pair"))
    table.fill_row(1, ("A", "B", "10"))
    table.add_row()
    table.fill_row(2, ("A", "B", "5"))
    table.add_row()
    table.fill_row(3, ("B", "C", "7"))
    editor.wait_preview()

    expect(editor.tid("entries-row")).to_have_count(2)
    expect(entries.row("A", "B")).to_contain_text("15")
    expect(table.flag(1, SAME_PAIR)).to_be_visible()
    expect(table.flag(2, SAME_PAIR)).to_be_visible()
    expect(table.flag(3, SAME_PAIR)).to_be_hidden()

    entries.set_category("A", "B", "Grp")

    expect(editor.tid("chart-tab-donut")).to_be_visible()
    expect(table.cell("Category (optional)", 1)).to_have_value("Grp")
    expect(table.cell("Category (optional)", 2)).to_have_value("Grp")
    expect(table.cell("Category (optional)", 3)).to_have_value("")
    graph_id = editor.save()

    stored = json_of(api.get(f"/api/v1/graphs/{graph_id}"))["source"]
    assert stored["type"] == "manual"
    assert [
        (link["source"], link["target"], link["value"], link.get("category"))
        for link in stored["links"]
    ] == [
        ("A", "B", 10, "Grp"),
        ("A", "B", 5, "Grp"),
        ("B", "C", 7, None),
    ]

    editor.page.reload()
    EditGraphPage(editor.page, editor.server).expect_ready()
    expect(SourcePanel(editor.page).tid("source-tab-manual")).to_have_attribute(
        "aria-selected", "true"
    )
    table.expect_values([("A", "B", "10", "Grp"), ("A", "B", "5", "Grp"), ("B", "C", "7", "")])
