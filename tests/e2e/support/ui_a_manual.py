"""Page object of the Manual source tab (UI-A suites): the editable table of links.

Rows are numbered from 1, the way their inputs are labelled (``Source, row 1`` ...). Remove
buttons are ``Remove row N``. A multi-cell paste is a real ``paste`` event with the text a
spreadsheet puts on the clipboard (tab separated cells, one row per line).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from playwright.sync_api import expect

if TYPE_CHECKING:
    from collections.abc import Sequence

    from playwright.sync_api import Locator, Page

COLUMNS: Final = ("Source", "Target", "Value", "Category (optional)")
_PASTE_JS = """(el, text) => {
    const data = new DataTransfer();
    data.setData('text', text);
    const init = {clipboardData: data, bubbles: true, cancelable: true};
    el.dispatchEvent(new ClipboardEvent('paste', init));
}"""


class ManualTable:
    """The links table of the Manual tab."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def rows(self) -> Locator:
        return self.page.get_by_test_id("manual-row")

    def cell(self, column: str, row: int) -> Locator:
        assert column in COLUMNS, f"unknown column {column!r}"
        return self.page.get_by_label(f"{column}, row {row}", exact=True)

    def fill_row(self, row: int, texts: Sequence[str]) -> None:
        """Fill the cells of ``row``: ``(source, target, value)`` plus an optional category."""
        for column, text in zip(COLUMNS, texts, strict=False):
            self.cell(column, row).fill(text)

    def flag(self, row: int, text: str) -> Locator:
        """The note of row ``row`` that says ``text`` ("Not drawn yet", the same-pair badge)."""
        return self.rows.nth(row - 1).get_by_text(text, exact=True)

    def add_row(self) -> None:
        self.page.get_by_test_id("manual-add-row").click()

    def remove_row(self, row: int) -> None:
        self.page.get_by_role("button", name=f"Remove row {row}", exact=True).click()

    def paste_cells(self, column: str, row: int, text: str) -> None:
        """Paste ``text`` (tab separated) into one cell, as a spreadsheet copy would."""
        self.cell(column, row).evaluate(_PASTE_JS, text)

    def paste_rows_dialog(self, text: str) -> None:
        """Use the "Paste rows" dialog: type ``text`` and add the rows."""
        self.page.get_by_role("button", name="Paste rows").click()
        self.page.get_by_label("Rows to add").fill(text)
        self.page.get_by_role("button", name="Add rows").click()

    def expect_values(self, expected: list[tuple[str, str, str, str]]) -> None:
        """The rows hold exactly these (source, target, value, category) texts, in order."""
        expect(self.rows).to_have_count(len(expected))
        for index, texts in enumerate(expected, start=1):
            for column, text in zip(COLUMNS, texts, strict=True):
                expect(self.cell(column, index)).to_have_value(text)

    def expect_field_errors(self, expected: list[str]) -> None:
        """The visible inline error texts of the table cells are exactly ``expected`` (retries)."""
        errors = self.page.locator("[data-testid=manual-table] .field-error:visible")
        expect(errors).to_have_text(expected)
