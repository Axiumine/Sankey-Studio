"""``LibraryPage``: the page object of the library (``/``, UI.md section 4.2).

Locators: ``cards``, ``card(name)``, ``names`` (the card title links), ``count`` (the
``library-count`` line), ``pager``, ``tag_chip(tag)``, ``tick(name)`` (the compare checkbox).
Actions: ``search``, ``sort_by``, ``next_page`` / ``previous_page``, ``toggle_tag``,
``expect_names``. Waits after an action are only a head start: assert the outcome with ``expect``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.uiwait import wait_idle

if TYPE_CHECKING:
    from playwright.sync_api import Locator

SETTLED: Final = (
    "[data-testid=graph-card], [data-testid=library-empty], [data-testid=library-no-results]"
)
PAGE_SIZE: Final = 12


def exact(text: str) -> re.Pattern[str]:
    """A regex matching exactly ``text`` (for ``has_text`` / ``to_have_text``)."""
    return re.compile(rf"^{re.escape(text)}$")


class LibraryPage(AppPage):
    path = "/"
    name = "library"

    def expect_ready(self) -> None:
        super().expect_ready()
        expect(self.page.locator(SETTLED).first).to_be_visible()

    # ------------------------------------------------------------------ locators

    @property
    def cards(self) -> Locator:
        return self.tid("graph-card")

    @property
    def names(self) -> Locator:
        """The title links of the cards of the current page, in order."""
        return self.tid("graph-open")

    @property
    def count(self) -> Locator:
        return self.tid("library-count")

    @property
    def pager(self) -> Locator:
        return self.page.get_by_role("navigation", name="Pages of graphs")

    def card(self, name: str) -> Locator:
        """The card whose title is exactly ``name``."""
        title = self.tid("graph-open").filter(has_text=exact(name))
        return self.cards.filter(has=title)

    def tag_chip(self, tag: str) -> Locator:
        return self.page.locator(f"[data-testid=library-tag-filter][data-tag={tag!r}]")

    def tick(self, name: str) -> Locator:
        """The compare checkbox of the card named ``name``."""
        return self.card(name).get_by_test_id("compare-select")

    # ------------------------------------------------------------------ actions

    def search(self, text: str) -> None:
        self.tid("library-search").fill(text)
        wait_idle(self.page)

    def sort_by(self, value: str) -> None:
        self.tid("library-sort").select_option(value)
        wait_idle(self.page)

    def next_page(self) -> None:
        self.tid("library-pager-next").click()
        wait_idle(self.page)

    def previous_page(self) -> None:
        self.tid("library-pager-prev").click()
        wait_idle(self.page)

    def toggle_tag(self, tag: str) -> None:
        self.tag_chip(tag).click()
        wait_idle(self.page)

    def expect_names(self, names: list[str]) -> None:
        """The current page lists exactly ``names`` in this order."""
        expect(self.names).to_have_text(names)
