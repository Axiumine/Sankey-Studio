# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""F6: a NEW category name typed on one entry shows up on that entry and in the data (rule 26).

The first test of the write-through work. The edited entry shows the new name, the chart agrees
(``category-row``: the new category holds that entry's value, ``Uncategorized`` holds the sum of
the untouched entries, it must not disappear), the OTHER entries keep the categories the data
already gives them (the owner's symptom: they used to fall back to "Uncategorized"), and the data
row of the pair (the Paste box, the Manual table) holds the new name too.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_entries import EntriesPanel
from tests.e2e.support.ui_a_sources import SourcePanel

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

RENT = ("Budget", "Rent")
UTILITIES = ("Budget", "Utilities")
SALARY = ("Salary", "Budget")
HEADERLESS = "Salary,Budget,3000,Income\nBudget,Rent,1200,Housing\nBudget,Food,640,Food\n"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    return editor


def category_rows(editor: EditorPage) -> dict[str, str]:
    """The category table as ``{name: value}`` (``category-row``: th = name, 2nd cell = value)."""
    rows = editor.tid("category-row")
    names = rows.locator("th").all_inner_texts()
    values = rows.locator("td:nth-child(2)").all_inner_texts()
    return dict(zip(names, values, strict=True))


def test_a_new_name_on_one_entry_of_uncategorised_data_lands_in_the_data(
    editor: EditorPage,
) -> None:
    editor.paste(BUDGET.csv)
    entries = EntriesPanel(editor.page)

    entries.set_category(*RENT, "Housing")

    expect(entries.cell(*RENT)).to_have_value("Housing")
    expect(editor.content).to_have_value("source,target,value,category\n" + _rows_with_housing())
    editor.wait_preview()
    rows = editor.tid("category-row")
    expect(rows.locator("th")).to_have_text(["Housing", "Uncategorized"])
    expect(rows.locator("td:nth-child(2)")).to_have_text(["1,200", "7,040"])
    expect(entries.cell(*UTILITIES)).to_have_value("")
    hint = editor.expect_toast("8 other entries have no category.", "info")
    hint.get_by_role("button", name="Show them").click()
    expect(editor.tid("entries-uncategorized-only")).to_be_checked()
    expect(entries.tid("entries-row")).to_have_count(8)


def _rows_with_housing() -> str:
    lines = BUDGET.csv.splitlines()[1:]
    return (
        "\n".join(f"{line},Housing" if line.startswith("Budget,Rent,") else line for line in lines)
        + "\n"
    )


def test_a_new_name_on_one_entry_keeps_the_categories_the_data_already_has(
    editor: EditorPage,
) -> None:
    editor.paste(BUDGET_CATEGORISED.csv)
    entries = EntriesPanel(editor.page)
    expect(entries.cell(*RENT)).to_have_value("Housing")

    entries.set_category(*UTILITIES, "Gifts")

    expect(entries.cell(*UTILITIES)).to_have_value("Gifts")
    expect(entries.cell(*RENT)).to_have_value("Housing")
    expect(entries.cell(*SALARY)).to_have_value("Income")
    expect(editor.content).to_have_value(re.compile(r"^Budget,Utilities,260,Gifts$", re.MULTILINE))
    editor.wait_preview()
    expect(editor.tid("category-row")).to_have_count(6)
    assert category_rows(editor) == {
        "Income": "3,800",
        "Savings": "1,470",
        "Food": "1,280",
        "Housing": "1,200",
        "Gifts": "260",
        "Transport": "230",
    }


def test_a_new_name_on_a_headerless_four_column_paste_keeps_the_other_categories(
    editor: EditorPage,
) -> None:
    source = SourcePanel(editor.page)
    editor.page.allow_http(422, "/api/v1/preview")
    editor.page.allow_http(422, "/api/v1/entries")
    editor.fill_source(HEADERLESS)
    editor.wait_settled()
    source.tid("source-has-header").uncheck()
    editor.wait_preview()
    entries = EntriesPanel(editor.page)
    expect(entries.cell(*RENT)).to_have_value("Housing")

    entries.set_category(*RENT, "Home")

    expect(entries.cell(*RENT)).to_have_value("Home")
    expect(entries.cell("Salary", "Budget")).to_have_value("Income")
    expect(entries.cell("Budget", "Food")).to_have_value("Food")
    expect(editor.content).to_have_value(HEADERLESS.replace("1200,Housing", "1200,Home"))
    editor.wait_preview()
    assert category_rows(editor) == {"Income": "3,000", "Home": "1,200", "Food": "640"}
