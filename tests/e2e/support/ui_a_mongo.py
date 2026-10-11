"""Page object of the MongoDB source tab (UI-A suites), for servers with a mongomock connection.

Connection, database and collection pickers (the last two are text inputs with ``<datalist>``
suggestions), the sample documents viewer with "Use the suggested fields", the Find / Aggregate
switch, the JSON boxes and the four field inputs. Inputs without a test id are found by their
visible label.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final, Literal

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

Mode = Literal["find", "aggregate"]
MODE_LABELS: Final = {"find": "Find (filter)", "aggregate": "Aggregate (pipeline)"}
FIELD_LABELS: Final = {
    "source": "Source field",
    "target": "Target field",
    "value": "Value field",
    "category": "Category field (optional)",
}


class MongoTab:
    """The MongoDB tab of the source section."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def tid(self, testid: str) -> Locator:
        return self.page.get_by_test_id(testid)

    def open(self) -> None:
        self.tid("source-tab-mongo").click()
        expect(self.tid("source-tab-mongo")).to_have_attribute("aria-selected", "true")

    def expect_suggestions(self, testid: str, names: list[str]) -> None:
        """The ``<datalist>`` of the input ``testid`` offers exactly ``names`` (retries)."""
        list_id = self.tid(testid).get_attribute("list")
        assert list_id, f"{testid} has no datalist"
        options = self.page.locator(f"datalist#{list_id} option")
        expect(options).to_have_count(len(names))
        for name in names:
            expect(
                self.page.locator(f"datalist#{list_id} option[value={json.dumps(name)}]")
            ).to_have_count(1)

    def field(self, name: str) -> Locator:
        return self.page.get_by_label(FIELD_LABELS[name], exact=True)

    def expect_fields(self, **expected: str) -> None:
        for name, value in expected.items():
            expect(self.field(name)).to_have_value(value)

    def fill_fields(self, **values: str) -> None:
        """Type into the field inputs: ``source=``, ``target=``, ``value=``, ``category=``."""
        for name, text in values.items():
            self.field(name).fill(text)

    def set_mode(self, mode: Mode) -> None:
        button = self.page.get_by_role("button", name=MODE_LABELS[mode], exact=True)
        button.click()
        expect(button).to_have_attribute("aria-pressed", "true")

    def show_sample(self) -> None:
        self.page.get_by_role("button", name="Show sample documents").click()
        expect(self.tid("mongo-sample")).to_be_visible()

    @property
    def counting_switch(self) -> Locator:
        return self.page.get_by_label("Count documents instead of adding up a value field")

    def expect_field_errors(self, expected: list[str]) -> None:
        """The visible inline error texts of the page are exactly ``expected`` (retries)."""
        expect(self.page.locator("#main .field-error:visible")).to_have_text(expected)
