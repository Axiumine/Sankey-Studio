"""Page object of the entries table and its category tools (UI-A suites).

``EntriesPanel(page)`` wraps the part of the editor below the chart: the table with one row per
source -> target pair, the category input of each row (``category-cell``), its clear button, the
search box with the bulk "categorise all matching" row, and the one error line
(``category-error``). Rows are found by their ``data-source`` / ``data-target`` attributes.
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
