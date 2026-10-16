# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.8, the colour theme: instant, stored on the server, and restored by the next page load.

Settings are server-wide, so every test starts on its own server (a fresh ``settings.json``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from playwright.sync_api import expect

from tests.e2e.support.ui_b_common import DESKTOP, wait_background
from tests.e2e.support.ui_b_settings import SettingsPage, wait_theme_saved

if TYPE_CHECKING:
    from tests.e2e.support.pages import ThemeValue
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.session import PageOpener
    from tests.e2e.support.watch import WatchedPage

PLANES: Final = {"light": "rgb(249, 249, 247)", "dark": "rgb(13, 13, 13)"}


@pytest.fixture
def settings(page: WatchedPage, live_server: LiveServer) -> SettingsPage:
    return SettingsPage(page, live_server)


def expect_theme(settings: SettingsPage, theme: ThemeValue) -> None:
    """The page paints ``theme`` now, and the server holds it."""
    settings.expect_html_theme(theme)
    expect(settings.theme_button(theme)).to_have_attribute("aria-pressed", "true")
    wait_background(settings.page, PLANES[theme])
    wait_theme_saved(settings.page, theme)


# ------------------------------------------------------------------------------ the cards


def test_a_theme_card_applies_at_once_is_stored_and_survives_a_reload(
    settings: SettingsPage,
) -> None:
    settings.goto()
    for theme in ("dark", "light"):
        settings.choose_theme_card(theme)
        expect(settings.theme_status).to_have_text("Theme saved.")
        expect_theme(settings, theme)
        settings.page.reload()
        settings.expect_ready()
        expect_theme(settings, theme)  # rendered by the server from the stored setting
        expect(settings.page.locator("html")).to_have_attribute("data-theme-source", "server")


def test_the_header_switch_and_the_cards_stay_in_step_and_the_theme_is_server_wide(
    settings: SettingsPage, live_server: LiveServer, open_page: PageOpener
) -> None:
    settings.goto()
    settings.theme_button("dark").click()
    settings.expect_html_theme("dark")
    expect(settings.theme_card("dark")).to_be_checked()
    wait_theme_saved(settings.page, "dark")
    settings.choose_theme_card("light")
    expect(settings.theme_button("light")).to_have_attribute("aria-pressed", "true")
    expect(settings.theme_button("dark")).to_have_attribute("aria-pressed", "false")
    wait_theme_saved(settings.page, "light")
    settings.theme_button("dark").click()
    wait_theme_saved(settings.page, "dark")
    other = SettingsPage(
        open_page(live_server, color_scheme="light", viewport=DESKTOP), live_server
    )
    other.goto()  # a second browser, a light device: the server's choice wins
    other.expect_html_theme("dark")
    wait_background(other.page, PLANES["dark"])


# ------------------------------------------------------------------------------ system


@pytest.mark.parametrize("color_scheme", ["dark"])
def test_system_follows_the_device_live_and_a_chosen_theme_does_not(
    settings: SettingsPage,
) -> None:
    settings.goto()
    settings.expect_html_theme("system")
    wait_background(settings.page, PLANES["dark"])  # the device is dark
    system_card = settings.page.get_by_text("Follows your device (now dark).")
    expect(system_card).to_be_visible()
    settings.page.emulate_media(color_scheme="light")
    expect(settings.page.get_by_text("Follows your device (now light).")).to_be_visible()
    wait_background(settings.page, PLANES["light"])
    settings.choose_theme_card("dark")
    settings.page.emulate_media(color_scheme="light")
    settings.expect_html_theme("dark")
    wait_background(settings.page, PLANES["dark"])  # an explicit choice beats the device
    settings.choose_theme_card("system")
    settings.expect_html_theme("system")
    wait_theme_saved(settings.page, "system")
    wait_background(settings.page, PLANES["light"])
