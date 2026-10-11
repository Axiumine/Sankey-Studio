"""E2E.md B.8, MongoDB connections: add, mask, keep the stored secret, test, delete.

The password is the point of this module: it may be typed into a password field once, and it is
nowhere in the page, its storage, or any answer of the settings API afterwards. A fresh server per
test (settings are server-wide); the Mongo behind it is mongomock.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import FLOWS_DATABASE, MONGO_PASSWORD, MONGO_URI, seed_flows
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_b_settings import SettingsPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

NEW_SECRET = "n3w-s3cret"
NEW_URI = f"mongodb://tester:{NEW_SECRET}@mongo.invalid:27017/?appName=e2e"
MASKED = "Stored: mongodb://tester:***@mongo.invalid:27017/?appName=e2e."
TEST_ROUTE = "/api/v1/settings/mongo/main/test"


@pytest.fixture
def settings(page: WatchedPage, live_server: LiveServer) -> SettingsPage:
    seed_flows(live_server.mongo)
    return SettingsPage(page, live_server)


def store_connection(api: httpx.Client, name: str = "main") -> None:
    """Save one connection through the API, as an earlier visit to the page would have."""
    connection = {"name": name, "uri": MONGO_URI, "default_database": FLOWS_DATABASE}
    json_of(api.put("/api/v1/settings", json={"mongo_connections": [connection]}))


def page_leaks(settings: SettingsPage, secret: str) -> list[str]:
    """Everything in the page and its browser storage that contains ``secret``."""
    page = settings.page
    values = page.evaluate("[...document.querySelectorAll('input, textarea')].map((e) => e.value)")
    storage = page.evaluate(
        "JSON.stringify([localStorage, sessionStorage].map((s) => Object.entries(s)))"
    )
    found = [f"input value {v!r}" for v in values if secret in v]
    found += ["page html"] if secret in page.content() else []
    found += ["page text"] if secret in page.inner_text("body") else []
    found += ["browser storage"] if secret in storage else []
    return found


def stored_file(live_server: LiveServer) -> dict[str, Any]:
    return dict(json.loads(live_server.settings_file.read_text(encoding="utf-8")))


# ------------------------------------------------------------------------------ add and mask


def test_a_new_connection_is_typed_in_a_password_field_saved_and_never_shown_again(
    settings: SettingsPage, live_server: LiveServer
) -> None:
    settings.goto()
    expect(settings.connections).to_have_count(0)
    card = settings.add_connection("main", MONGO_URI, FLOWS_DATABASE)
    uri = card.get_by_test_id("connection-uri")
    expect(uri).to_have_attribute("type", "password")  # masked while typing
    settings.save()
    settings.expect_toast("Settings saved.", "success")
    expect(settings.save_status).to_have_text("All changes saved.")
    expect(uri).to_have_value("")  # emptied after the save
    expect(uri).to_have_attribute("placeholder", "(unchanged)")
    expect(card).to_contain_text(MASKED)
    assert page_leaks(settings, MONGO_PASSWORD) == []
    stored = settings.stored()["mongo_connections"]
    assert stored == [
        {
            "name": "main",
            "uri_masked": "mongodb://tester:***@mongo.invalid:27017/?appName=e2e",
            "has_secret": True,
            "default_database": FLOWS_DATABASE,
        }
    ]
    assert MONGO_PASSWORD in live_server.settings_file.read_text()  # kept, but only on the server
    settings.page.reload()  # and after a reload it is still nowhere in the page
    settings.expect_ready()
    expect(settings.connection_named("main")).to_contain_text(MASKED)
    expect(settings.connection_named("main").get_by_test_id("connection-uri")).to_have_value("")
    assert page_leaks(settings, MONGO_PASSWORD) == []
    assert page_leaks(settings, "hunter") == []


# ------------------------------------------------------------------------------ keep and replace


def test_other_changes_and_a_rename_keep_the_secret_a_pasted_string_replaces_it(
    settings: SettingsPage, live_server: LiveServer, api: httpx.Client
) -> None:
    store_connection(api)
    settings.goto()
    card = settings.connection_named("main")
    card.get_by_test_id("connection-default-db").fill("other_db")  # URI left empty on purpose
    settings.save()
    expect(settings.save_status).to_have_text("All changes saved.")
    assert settings.stored()["mongo_connections"][0]["default_database"] == "other_db"
    assert stored_file(live_server)["mongo_connections"][0]["uri"] == MONGO_URI
    card = settings.connection(0)  # found by position: its name is about to change
    card.get_by_test_id("connection-name").fill("primary")
    expect(card).to_contain_text("Renaming keeps the stored connection string.")
    settings.save()
    expect(settings.save_status).to_have_text("All changes saved.")
    renamed = settings.stored()["mongo_connections"][0]
    assert (renamed["name"], renamed["has_secret"]) == ("primary", True)
    assert stored_file(live_server)["mongo_connections"][0]["uri"] == MONGO_URI
    card.get_by_test_id("connection-uri").fill(NEW_URI)  # now replace it
    settings.save()
    expect(settings.save_status).to_have_text("All changes saved.")
    expect(card.get_by_test_id("connection-uri")).to_have_value("")
    file_text = live_server.settings_file.read_text()
    assert NEW_SECRET in file_text
    assert MONGO_PASSWORD not in file_text
    assert page_leaks(settings, NEW_SECRET) == []


# ------------------------------------------------------------------------------ test connection


def test_testing_a_connection_shows_latency_reports_an_outage_and_recovers(
    settings: SettingsPage, live_server: LiveServer, api: httpx.Client
) -> None:
    store_connection(api)
    settings.goto()
    card = settings.connection_named("main")
    status = card.get_by_test_id("connection-status")
    card.get_by_test_id("connection-test").click()
    expect(status).to_contain_text("Connected in")
    expect(card.get_by_test_id("connection-latency")).to_have_text(re.compile(r"^\d[\d.,]* ms$"))
    settings.expect_toast(re.compile(r'Connected to "main" in [\d.,]+ ms\.'), "success")
    live_server.mongo.unreachable = True
    settings.page.allow_http(503, TEST_ROUTE)  # the probe answers 503 storage_error
    card.get_by_test_id("connection-test").click()
    expect(status).to_contain_text("MongoDB connection 'main' is unreachable")
    settings.expect_toast("is unreachable", "error")
    expect(card.get_by_test_id("connection-latency")).to_have_count(0)
    assert settings.page.watch.matching(rf"^http 503: POST .*{TEST_ROUTE}")
    assert page_leaks(settings, MONGO_PASSWORD) == []  # not even in the error
    live_server.mongo.unreachable = False
    card.get_by_test_id("connection-test").click()
    expect(card.get_by_test_id("connection-latency")).to_be_visible()
    draft = settings.add_connection("draft", MONGO_URI, FLOWS_DATABASE)  # not saved yet
    draft.get_by_test_id("connection-test").click()
    expect(draft.get_by_test_id("connection-status")).to_contain_text(
        "Reachable with the values above. Save to keep them."
    )
    expect(settings.save_status).to_have_text("You have unsaved changes.")
    assert [c["name"] for c in settings.stored()["mongo_connections"]] == ["main"]  # nothing saved


# ------------------------------------------------------------------------------ delete


def test_deleting_a_connection_removes_it_at_once_and_keeps_it_until_saved(
    settings: SettingsPage, live_server: LiveServer, api: httpx.Client
) -> None:
    store_connection(api)
    settings.goto()
    settings.connection_named("main").get_by_test_id("connection-delete").click()
    expect(settings.connections).to_have_count(0)
    toast = settings.expect_toast('Connection "main" removed. It is deleted when you save.')
    assert len(settings.stored()["mongo_connections"]) == 1  # still stored
    toast.get_by_role("button", name="Undo").click()
    expect(settings.connections).to_have_count(1)
    expect(settings.connection_named("main")).to_contain_text(MASKED)  # the secret came back too
    settings.connection_named("main").get_by_test_id("connection-delete").click()
    settings.save()
    expect(settings.save_status).to_have_text("All changes saved.")
    assert settings.stored()["mongo_connections"] == []
    assert MONGO_PASSWORD not in live_server.settings_file.read_text()
    settings.page.reload()
    settings.expect_ready()
    expect(settings.connections).to_have_count(0)


# ------------------------------------------------------------------------------ validation

BAD_CONNECTIONS = [
    ("", MONGO_URI, "Give the connection a name."),
    ("bad name!", MONGO_URI, "Use 1 to 64 letters, digits, dots, dashes or underscores"),
    ("fine", "", "Enter the connection string."),
    ("fine", "http://example.test", "A connection string starts with mongodb://"),
]


def test_a_bad_connection_is_refused_in_the_browser_before_anything_is_sent(
    settings: SettingsPage, api: httpx.Client
) -> None:
    store_connection(api)
    settings.goto()
    for name, uri, message in BAD_CONNECTIONS:
        card = settings.add_connection(name, uri)
        settings.save()
        expect(settings.tid("settings-error")).to_contain_text("Settings were not saved")
        expect(card).to_contain_text(message)
        settings.tid("settings-discard").click()
        expect(settings.connections).to_have_count(1)
    settings.add_connection("main", MONGO_URI)  # a second connection with a taken name
    settings.save()
    expect(settings.connection(1)).to_contain_text("Another connection already has this name.")
    assert [c["name"] for c in settings.stored()["mongo_connections"]] == ["main"]
