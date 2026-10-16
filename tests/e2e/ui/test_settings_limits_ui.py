# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.8, the limits: validated, saved, discarded, guarded and checked for conflicts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from playwright.sync_api import expect

from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_b_settings import SettingsPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

#: key -> (smallest allowed, largest allowed, the message under the field, the default)
RANGES: Final = {
    "max_links": (100, 5_000_000, "Enter a whole number from 100 to 5,000,000.", 200_000),
    "max_drawn_links": (50, 20_000, "Enter a whole number from 50 to 20,000.", 3_000),
    "max_upload_mb": (1, 100, "Enter a whole number from 1 to 100.", 25),
    "mongo_timeout_ms": (500, 300_000, "Enter a whole number from 500 to 300,000.", 15_000),
}


@pytest.fixture
def settings(page: WatchedPage, live_server: LiveServer) -> SettingsPage:
    return SettingsPage(page, live_server)


def limits_of(settings: SettingsPage) -> dict[str, int]:
    stored = settings.stored()
    return {key: int(stored[key]) for key in RANGES}


def defaults() -> dict[str, int]:
    return {key: spec[3] for key, spec in RANGES.items()}


# ------------------------------------------------------------------------------ validation


def test_out_of_range_values_are_refused_inline_and_nothing_is_stored(
    settings: SettingsPage,
) -> None:
    section = settings.page.locator("#settings-limits")
    settings.goto()
    for key, (low, high, message, _default) in RANGES.items():
        for bad in ("", "12.5", "-5", str(low - 1), str(high + 1)):
            settings.set_limit(key, bad)
            expect(section).to_contain_text(message)
            expect(settings.save_status).to_have_text("You have unsaved changes.")
        settings.save()  # the last bad value is still in the field
        expect(settings.tid("settings-error")).to_contain_text("Settings were not saved")
        settings.expect_toast("Settings were not saved.", "error")
        assert limits_of(settings) == defaults(), f"a bad {key} reached the server"
        for good in (str(low), str(high)):  # the boundaries themselves are fine
            settings.set_limit(key, good)
            expect(section).not_to_contain_text(message)
        settings.set_limit(key, str(RANGES[key][3]))  # back to the default for the next field


def test_valid_limits_are_saved_applied_to_the_next_upload_and_shown_after_a_reload(
    settings: SettingsPage, api: httpx.Client
) -> None:
    settings.goto()
    wanted = {"max_links": 150_000, "max_drawn_links": 2_500, "mongo_timeout_ms": 500}
    for key, value in wanted.items():
        settings.set_limit(key, str(value))
    settings.set_limit("max_upload_mb", "1")
    expect(settings.save_status).to_have_text("You have unsaved changes.")
    settings.save()
    settings.expect_toast("Settings saved.", "success")
    expect(settings.save_status).to_have_text("All changes saved.")
    expect(settings.tid("settings-error")).to_be_hidden()
    assert limits_of(settings) == {**defaults(), **wanted, "max_upload_mb": 1}
    settings.page.reload()
    settings.expect_ready()
    for key, value in {**wanted, "max_upload_mb": 1}.items():
        expect(settings.limit(key)).to_have_value(str(value))
    big = ("big.csv", b"a,b,1\n" * 400_000, "text/csv")  # about 2.4 MB: over the new 1 MB cap
    too_big = api.post("/api/v1/sources/files", files={"file": big})
    assert json_of(too_big, 413)["error"]["code"] == "payload_too_large"


# ------------------------------------------------------------------------------ discard and guard


def test_discard_restores_the_stored_values_and_leaving_unsaved_changes_asks_first(
    settings: SettingsPage,
) -> None:
    settings.goto()
    expect(settings.tid("settings-discard")).to_be_hidden()  # nothing to discard yet
    settings.set_limit("max_links", "4321")
    settings.tid("settings-discard").click()
    expect(settings.limit("max_links")).to_have_value("200000")
    expect(settings.save_status).to_have_text("All changes saved.")
    expect(settings.tid("settings-discard")).to_be_hidden()
    settings.set_limit("max_links", "4321")
    settings.nav("library").click()
    dialog = settings.page.get_by_role("dialog", name="Discard unsaved changes?")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Keep editing").click()
    expect(dialog).to_be_hidden()
    assert settings.page.url.endswith("/settings")
    expect(settings.limit("max_links")).to_have_value("4321")
    settings.nav("library").click()
    settings.page.get_by_role("button", name="Discard and leave").click()
    settings.page.wait_for_url(settings.server.url_for("/"))
    assert limits_of(settings) == defaults()
    settings.page.go_back()  # a saved page is left without asking
    settings.expect_ready()
    settings.set_limit("max_links", "4321")
    settings.save()
    expect(settings.save_status).to_have_text("All changes saved.")
    settings.nav("library").click()
    settings.page.wait_for_url(settings.server.url_for("/"))


# ------------------------------------------------------------------------------ changed elsewhere


def test_settings_saved_elsewhere_ask_before_being_overwritten_or_can_be_shown(
    settings: SettingsPage, api: httpx.Client
) -> None:
    settings.goto()
    settings.set_limit("max_links", "4321")
    json_of(api.put("/api/v1/settings", json={"max_drawn_links": 777}))  # another window saved
    settings.save()
    dialog = settings.page.get_by_role("dialog", name="Settings were changed elsewhere")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    settings.expect_toast("Nothing was saved.", "info")
    assert limits_of(settings)["max_links"] == 200_000
    settings.save()
    settings.tid("settings-conflict-overwrite").click()
    expect(settings.save_status).to_have_text("All changes saved.")
    stored = limits_of(settings)
    assert stored["max_links"] == 4321
    assert stored["max_drawn_links"] == 3000  # "replaces their changes with yours": mine wins
    settings.set_limit("max_links", "5555")  # and once more, this time looking at theirs
    json_of(api.put("/api/v1/settings", json={"max_drawn_links": 888}))
    settings.save()
    settings.tid("conflict-reload").click()
    settings.expect_toast("Showing the settings as they are now. Your edits were dropped.", "info")
    expect(settings.limit("max_links")).to_have_value("200000")  # theirs: a PUT resets the rest
    expect(settings.limit("max_drawn_links")).to_have_value("888")
    expect(settings.save_status).to_have_text("All changes saved.")
