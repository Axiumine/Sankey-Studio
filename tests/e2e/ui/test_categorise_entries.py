"""B3, part 1: categorise entries in the editor (UI.md flow F2 and its negatives).

The entries table (one row per source -> target pair), the category input with its datalist, the
single-entry commit, "None, on purpose" for a cleared entry, the bulk rule for all entries that
match a search (with Undo), the reserved name ``Other`` and the empty bulk category as inline
errors, and the promise that categories are optional. Every test starts a fresh editor on the
module's server and saves nothing except where a test says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_entries import EntriesPanel

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

RENT = ("Budget", "Rent")
UTILITIES = ("Budget", "Utilities")
RESERVED = '"Other" is reserved for the chart (it labels the leftovers). Pick another name.'


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(BUDGET.csv)
    return editor


@pytest.fixture
def entries(editor: EditorPage) -> EntriesPanel:
    return EntriesPanel(editor.page)


def expect_category_rows(editor: EditorPage, expected: list[tuple[str, str]]) -> None:
    """The category table shows exactly these (name, value) rows, in this order (retries)."""
    rows = editor.tid("category-row")
    expect(rows.locator("th")).to_have_text([name for name, _ in expected])
    expect(rows.locator("td:nth-child(2)")).to_have_text([value for _, value in expected])


# ------------------------------------------------------------------------------ steps


def step_look_at_the_table_and_search(editor: EditorPage, entries: EntriesPanel) -> None:
    expect(editor.tid("entries-total")).to_have_text("9 entries")
    expect(editor.tid("entries-row")).to_have_count(BUDGET.links)
    expect(entries.row("Salary", "Budget")).to_have_count(1)
    expect(entries.row(*RENT)).to_contain_text("1,200")
    expect(entries.cell(*RENT)).to_have_value("")
    expect(editor.tid("category-clear").first).to_be_disabled()
    expect(editor.tid("category-table")).to_have_count(0)
    expect(editor.tid("categorise-all-matching")).to_have_count(0)
    entries.expect_datalist([])

    entries.search("Food")
    expect(editor.tid("entries-row")).to_have_count(3)
    expect(editor.page.get_by_text('3 entries match "Food".')).to_be_visible()
    expect(editor.tid("categorise-all-matching")).to_be_visible()
    entries.search("")
    expect(editor.tid("entries-row")).to_have_count(BUDGET.links)
    expect(editor.tid("categorise-all-matching")).to_have_count(0)


def step_type_categories_and_clear_one(editor: EditorPage, entries: EntriesPanel) -> None:
    pending = entries.cell(*UTILITIES)
    pending.fill("Housing")
    pending.press("Escape")
    expect(pending).to_have_value("")
    expect(editor.tid("chart-tab-donut")).to_have_count(0)

    entries.cell(*RENT).fill("Housing")
    entries.cell(*UTILITIES).click()  # leaving the cell commits it, no Enter needed

    expect(editor.tid("chart-tab-donut")).to_be_visible()
    editor.wait_preview()
    editor.expect_stats(nodes=10, links=9, total_in=3800, total_out=3800, columns=4, categories=1)
    expect(editor.tid("donut-hint")).to_have_count(0)
    expect_category_rows(editor, [("Housing", "1,200"), ("Uncategorized", "7,040")])
    entries.expect_datalist(["Housing"])
    expect(entries.cell(*UTILITIES)).to_have_value("")

    entries.set_category(*UTILITIES, "Housing")
    expect(editor.tid("category-row").first).to_contain_text("1,460")
    entries.clear_category(*UTILITIES)

    expect(entries.cell(*UTILITIES)).to_have_value("")
    expect(entries.row(*UTILITIES)).to_contain_text("None, on purpose")
    expect_category_rows(editor, [("Housing", "1,200"), ("Uncategorized", "7,040")])


def step_bulk_rule_ranks_below_single_choices_and_is_undone(
    editor: EditorPage, entries: EntriesPanel
) -> None:
    entries.set_category("Food", "Groceries", "Pantry")
    entries.search("Food")

    entries.bulk_categorise("Living")

    toast = editor.expect_toast(
        'Rule added: names containing "Food" get "Living". You can edit it under Transform.',
        "success",
    )
    expect(editor.tid("transform-rules").locator("tbody tr")).to_have_count(1)
    expect(editor.tid("section-transform")).to_contain_text("1 category rule")
    entries.search("")
    entries.expect_categories(
        {
            ("Budget", "Food"): "Living",
            ("Food", "Groceries"): "Pantry",
            ("Food", "Restaurants"): "Living",
            RENT: "Housing",
        }
    )
    expect_category_rows(
        editor,
        [("Housing", "1,200"), ("Living", "780"), ("Pantry", "500"), ("Uncategorized", "5,760")],
    )

    toast.get_by_role("button", name="Undo").click()

    expect(editor.tid("section-transform")).not_to_contain_text("1 category rule")
    expect(entries.cell("Food", "Restaurants")).to_have_value("")
    expect(entries.cell("Food", "Groceries")).to_have_value("Pantry")


def step_reserved_names_and_empty_bulk_are_inline_errors(
    editor: EditorPage, entries: EntriesPanel
) -> None:
    entries.set_category("Salary", "Budget", "Other")
    expect(entries.error).to_have_text(RESERVED)
    expect(entries.cell("Salary", "Budget")).to_have_value("Other")
    entries.search("Rent")
    entries.bulk_categorise("other")
    expect(entries.error).to_have_text(RESERVED.replace('"Other"', '"other"'))
    entries.bulk_categorise("")
    expect(entries.error).to_have_text("Type the category these entries should get.")
    expect(editor.tid("transform-rules").locator("tbody tr")).to_have_count(0)
    expect(editor.save_status).not_to_contain_text("All changes saved")
    expect_category_rows(
        editor, [("Housing", "1,200"), ("Pantry", "500"), ("Uncategorized", "6,540")]
    )

    entries.search("")
    entries.set_category("Salary", "Budget", "Income")
    expect(entries.error).to_be_hidden()
    expect(entries.cell("Salary", "Budget")).to_have_value("Income")


# ------------------------------------------------------------------------------ test


def test_the_entries_table_takes_categories_one_by_one_in_bulk_and_refuses_reserved_names(
    editor: EditorPage, entries: EntriesPanel
) -> None:
    step_look_at_the_table_and_search(editor, entries)
    step_type_categories_and_clear_one(editor, entries)
    step_bulk_rule_ranks_below_single_choices_and_is_undone(editor, entries)
    step_reserved_names_and_empty_bulk_are_inline_errors(editor, entries)
