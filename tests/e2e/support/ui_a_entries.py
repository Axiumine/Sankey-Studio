"""Page objects of the entries table, its category tools and its additions (UI-A suites).

``EntriesPanel(page)`` wraps the part of the editor below the chart: the table with one row per
source -> target pair, the category input of each row (``category-cell``), its clear button, the
search box with the bulk "categorise all matching" row, and the one error line
(``category-error``). Rows are found by their ``data-source`` / ``data-target`` attributes.
It also reaches the header additions: ``add_button`` / ``add_entry(...)``, the ``AddEntryDialog``
("Add a flow"), the ``entries-overlays`` chip with its ``OverlaysDialog`` and the ``unmatched``
notice.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class EntriesPanel:
    """The entries table of the editor."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def tid(self, testid: str) -> Locator:
        return self.page.get_by_test_id(testid)

    # ------------------------------------------------------------------ rows

    def row(self, source: str, target: str) -> Locator:
        selector = (
            f"[data-testid=entries-row][data-source={json.dumps(source)}]"
            f"[data-target={json.dumps(target)}]"
        )
        return self.page.locator(selector)

    def cell(self, source: str, target: str) -> Locator:
        return self.row(source, target).get_by_test_id("category-cell")

    def expect_categories(self, expected: dict[tuple[str, str], str]) -> None:
        """Each listed pair shows exactly this category (``""`` = empty input)."""
        for (source, target), category in expected.items():
            expect(self.cell(source, target)).to_have_value(category)

    # ------------------------------------------------------------------ single entries

    def set_category(self, source: str, target: str, category: str) -> None:
        """Type ``category`` into the cell of a pair and press Enter (the commit)."""
        cell = self.cell(source, target)
        cell.fill(category)
        cell.press("Enter")

    def clear_category(self, source: str, target: str) -> None:
        self.row(source, target).get_by_test_id("category-clear").click()

    def expect_datalist(self, names: list[str]) -> None:
        """The category suggestions are exactly ``names`` (retries until the page agrees)."""
        options = self.page.locator("#category-datalist option")
        expect(options).to_have_count(len(names))
        for name in names:
            expect(
                self.page.locator(f"#category-datalist option[value={json.dumps(name)}]")
            ).to_have_count(1)

    # ------------------------------------------------------------------ search and bulk

    def search(self, text: str) -> None:
        self.tid("entries-search").fill(text)

    def bulk_categorise(self, category: str) -> None:
        """Fill the bulk category and click "Categorise all entries matching this filter"."""
        self.tid("categorise-category").fill(category)
        self.tid("categorise-all-matching").click()

    @property
    def error(self) -> Locator:
        return self.tid("category-error")

    # ------------------------------------------------------------------ add, graph-only edits

    @property
    def add_button(self) -> Locator:
        """The "Add entry" button of the card header."""
        return self.tid("entries-add")

    @property
    def add_dialog(self) -> AddEntryDialog:
        return AddEntryDialog(self.page)

    @property
    def overlays_chip(self) -> Locator:
        """The "Graph-only edits (N)" chip (hidden while there is none)."""
        return self.tid("entries-overlays")

    @property
    def overlays(self) -> OverlaysDialog:
        return OverlaysDialog(self.page)

    @property
    def unmatched(self) -> Locator:
        """The notice that category edits no longer match an entry."""
        return self.tid("entries-unmatched")

    def add_entry(self, source: str, target: str, value: str, category: str = "") -> None:
        """Open the dialog, fill it and press Add (the dialog may stay open on a refusal)."""
        self.add_button.click()
        self.add_dialog.fill(source, target, value, category)
        self.add_dialog.submit.click()

    # ------------------------------------------------------------------ pager

    @property
    def next_page(self) -> Locator:
        return self.tid("entries-pager-next")

    @property
    def previous_page(self) -> Locator:
        return self.tid("entries-pager-prev")

    def expect_page(self, number: int, pages: int, rows: tuple[int, int, int]) -> None:
        """ "Page N of M" and "Rows first-last of total" (``rows``) are shown (retries)."""
        first, last, total = rows
        expect(self.page.get_by_text(f"Page {number} of {pages}", exact=True)).to_be_visible()
        expect(self.page.locator(".out-rows-label")).to_have_text(
            f"Rows {first}-{last} of {total:,}"
        )
        expect(self.tid("entries-row")).to_have_count(last - first + 1)

    def pairs(self) -> list[str]:
        """``source>target`` of every row on the page, in table order."""
        script = "rows => rows.map((row) => row.dataset.source + '>' + row.dataset.target)"
        return [str(pair) for pair in self.tid("entries-row").evaluate_all(script)]


class AddEntryDialog:
    """The "Add a flow" dialog (``entries-add`` opens it) and its fields."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def tid(self, testid: str) -> Locator:
        return self.page.get_by_test_id(testid)

    @property
    def dialog(self) -> Locator:
        return self.tid("add-entry-dialog")

    @property
    def submit(self) -> Locator:
        return self.tid("add-entry-submit")

    @property
    def cancel(self) -> Locator:
        return self.tid("add-entry-cancel")

    @property
    def error(self) -> Locator:
        return self.tid("add-entry-error")

    def field(self, name: str) -> Locator:
        return self.tid(f"add-entry-{name}")

    def hint(self, name: str) -> Locator:
        """The status line under the source or target input ("New node: X will be created.")."""
        return self.field(name).locator("xpath=..").get_by_role("status")

    def fill(self, source: str, target: str, value: str, category: str = "") -> None:
        """Type the four fields (an empty ``category`` leaves the optional field empty)."""
        for name, text in (("source", source), ("target", target), ("value", value)):
            self.field(name).fill(text)
        self.field("category").fill(category)

    def expect_open(self) -> None:
        expect(self.dialog).to_be_visible()

    def expect_gone(self) -> None:
        expect(self.dialog).to_have_count(0)


class OverlaysDialog:
    """The "Graph-only edits" dialog opened by the ``entries-overlays`` chip."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def dialog(self) -> Locator:
        return self.page.get_by_test_id("overlays-dialog")

    @property
    def rows(self) -> Locator:
        return self.dialog.locator("li")

    def remove(self, text: str) -> None:
        """Press Remove on the row that says ``text``."""
        self.rows.filter(has_text=text).get_by_test_id("overlay-remove").click()
