# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``SettingsPage``: the page object of ``/settings`` (docs/ui/settings.md).

``stored()`` reads the settings the SERVER holds (``GET /api/v1/settings`` from inside the page), so
a test can tell "the screen says saved" from "the server has it". The connection cards are found by
position (``connection(n)``) or by the name field's value (``connection_named``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from playwright.sync_api import expect

from tests.e2e.support.clients import fetch_json
from tests.e2e.support.pages import AppPage, ThemeValue
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


def stored_theme(page: Page) -> str:
    """The theme the SERVER holds (``GET /api/v1/settings`` from inside ``page``)."""
    result = fetch_json(page, "GET", "/api/v1/settings")
    assert result.status == 200, result.text
    return str(result.json["theme"])


def wait_theme_saved(page: Page, theme: str) -> None:
    """Wait until the server holds ``theme``: a theme click saves in the background (GET, then PUT).

    A test that navigates away, or ends, before the save has landed would cancel it or hit a
    stopped server.
    """
    wait_until(lambda: stored_theme(page) == theme, what=f"the server to store theme {theme}")


THEME_ORDER: Final = ("system", "light", "dark")
LIMIT_IDS: Final = {
    "max_links": "settings-max-links",
    "max_drawn_links": "settings-max-drawn-links",
    "max_upload_mb": "settings-max-upload-mb",
    "mongo_timeout_ms": "settings-mongo-timeout",
}


class SettingsPage(AppPage):
    path = "/settings"
    name = "settings"

    def expect_ready(self) -> None:
        super().expect_ready()
        expect(self.tid("settings-save")).to_be_visible()

    # ------------------------------------------------------------------ locators

    @property
    def save_button(self) -> Locator:
        return self.tid("settings-save")

    @property
    def save_status(self) -> Locator:
        return self.tid("settings-save-status")

    @property
    def connections(self) -> Locator:
        return self.tid("settings-connection")

    @property
    def theme_status(self) -> Locator:
        """The line under the theme cards ("Theme saved."), not a toast."""
        return self.page.locator("#settings-appearance p.hint")

    def connection(self, index: int = 0) -> Locator:
        return self.connections.nth(index)

    def connection_named(self, name: str) -> Locator:
        """The card whose name field currently holds ``name``."""
        return self.page.locator(
            f"[data-testid=settings-connection][data-connection-name={name!r}]"
        )

    def theme_card(self, value: ThemeValue) -> Locator:
        return self.tid("settings-theme-option").nth(THEME_ORDER.index(value))

    def limit(self, key: str) -> Locator:
        return self.tid(LIMIT_IDS[key])

    # ------------------------------------------------------------------ actions

    def save(self) -> None:
        self.save_button.click()

    def choose_theme_card(self, value: ThemeValue) -> None:
        """Pick a theme with the cards of the Appearance section (the radio is visually hidden)."""
        self.page.get_by_role("radio", name=value.capitalize(), exact=True).check(force=True)

    def add_connection(self, name: str, uri: str, database: str = "") -> Locator:
        """Add a card, fill it and return it (nothing is saved yet)."""
        before = self.connections.count()
        self.tid("connection-add").click()
        expect(self.connections).to_have_count(before + 1)
        card = self.connection(before)
        card.get_by_test_id("connection-name").fill(name)
        card.get_by_test_id("connection-uri").fill(uri)
        if database:
            card.get_by_test_id("connection-default-db").fill(database)
        return card

    def set_limit(self, key: str, value: str) -> None:
        field = self.limit(key)
        field.fill(value)
        field.blur()

    # ------------------------------------------------------------------ the server's view

    def stored(self) -> dict[str, Any]:
        result = fetch_json(self.page, "GET", "/api/v1/settings")
        assert result.status == 200, result.text
        return dict(result.json)

    def choose_mongo_storage(self, connection: str, database: str) -> None:
        """Pick MongoDB as the store (connection and database fields appear)."""
        self.tid("settings-storage-backend").select_option("mongo")
        self.tid("settings-storage-connection").select_option(label=connection)
        self.tid("settings-storage-database").fill(database)

    def choose_file_storage(self) -> None:
        self.tid("settings-storage-backend").select_option("file")
