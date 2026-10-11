"""E2E.md B.8, the storage backend: files <-> MongoDB, with and without copying the graphs.

The Mongo behind the server is mongomock; ``server.mongo`` shows what really landed in it. A fresh
server per test, with one stored connection ``main``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import mongo_settings, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_b_settings import SettingsPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.watch import WatchedPage

DATABASE = "e2e_graphs"
COLLECTION = "sankey_studio_graphs"
REACHABLE = "Storage is reachable and writable."


@pytest.fixture
def live_server(make_server: ServerFactory) -> LiveServer:
    return make_server(settings=mongo_settings("main", "flows"))


@pytest.fixture
def settings(page: WatchedPage, live_server: LiveServer) -> SettingsPage:
    return SettingsPage(page, live_server)


def seed_three(api: httpx.Client) -> dict[str, str]:
    """Three graphs in the current store; returns ``{id: name}``."""
    prefix = unique_name("Stored")
    found = [seed_graph(api, f"{prefix} {n}") for n in (1, 2, 3)]
    return {graph["id"]: graph["name"] for graph in found}


def listed(api: httpx.Client) -> dict[str, str]:
    items = json_of(api.get("/api/v1/graphs"))["items"]
    return {item["id"]: item["name"] for item in items}


def mongo_count(live_server: LiveServer) -> int:
    return int(live_server.mongo[DATABASE][COLLECTION].count_documents({}))


# ------------------------------------------------------------------------------ the form


def test_the_mongo_fields_appear_only_for_mongo_and_a_bad_target_is_refused_inline(
    settings: SettingsPage, live_server: LiveServer
) -> None:
    settings.goto()
    sources = settings.tid("settings-sources-dir")  # "This server": set at start-up, display only
    expect(sources).to_have_text(str(live_server.sources_dir))
    assert sources.evaluate("element => element.tagName") == "CODE"
    expect(settings.page.locator("#settings-server input, #settings-server select")).to_have_count(
        0
    )
    expect(settings.tid("settings-remote-mode")).to_have_text("Local only: this computer")
    expect(settings.tid("settings-writes-allowed")).to_have_text("Allowed")
    connection = settings.tid("settings-storage-connection")
    expect(settings.tid("settings-storage-backend")).to_have_value("file")
    expect(connection).to_be_hidden()
    expect(settings.tid("settings-storage-database")).to_be_hidden()
    settings.tid("settings-test-storage").click()  # the file store: reachable, nothing changes
    expect(settings.tid("settings-storage-status")).to_have_text(REACHABLE)
    settings.expect_toast(REACHABLE, "success")
    settings.tid("settings-storage-backend").select_option("mongo")
    settings.tid("settings-storage-database").fill("bad name")
    settings.save()  # no connection chosen, and a database name with a space
    expect(settings.tid("settings-error")).to_be_visible()
    storage = settings.page.locator("#settings-storage")
    expect(storage).to_contain_text("Choose the connection that holds the graphs.")
    expect(storage).to_contain_text("A database name cannot contain spaces")
    settings.choose_mongo_storage("main", DATABASE)
    badge = settings.connection_named("main").get_by_text("Holds your graphs")
    expect(badge).to_be_visible()
    settings.tid("settings-test-storage").click()
    expect(settings.tid("settings-storage-status")).to_have_text(REACHABLE)
    settings.choose_file_storage()
    expect(connection).to_be_hidden()
    expect(badge).to_be_hidden()
    assert settings.stored()["storage_backend"] == "file"  # nothing was saved


# ------------------------------------------------------------------------------ switching


def test_switching_to_mongo_with_copying_moves_the_graphs_and_keeps_the_originals(
    settings: SettingsPage, live_server: LiveServer, api: httpx.Client
) -> None:
    graphs = seed_three(api)
    settings.goto()
    migrate = settings.tid("settings-migrate")
    expect(migrate).to_be_checked()
    expect(
        settings.page.get_by_text("Copy my 3 existing graphs to the new location")
    ).to_be_visible()
    settings.choose_mongo_storage("main", DATABASE)
    expect(settings.page.get_by_text("Copying never deletes anything")).to_be_visible()
    settings.save()
    settings.expect_toast("Settings saved. 3 graphs copied to the new location.", "success")
    report = settings.tid("settings-copy-report")
    expect(report).to_have_attribute("data-copied", "3")
    expect(report).to_have_attribute("data-skipped", "0")
    expect(report).to_have_attribute("data-unreadable", "0")
    expect(report).to_contain_text("Your graphs were copied to the new location.")
    assert settings.stored()["storage_backend"] == "mongo"
    assert mongo_count(live_server) == 3
    assert listed(api) == graphs  # the same ids, now read from MongoDB
    assert len(list(live_server.graphs_dir.glob("*.json"))) == 3  # nothing was deleted
    settings.page.goto("/")
    expect(settings.tid("graph-card")).to_have_count(3)


def test_switching_without_copying_leaves_the_graphs_behind_until_you_switch_back(
    settings: SettingsPage, live_server: LiveServer, api: httpx.Client
) -> None:
    graphs = seed_three(api)
    settings.goto()
    settings.choose_mongo_storage("main", DATABASE)
    settings.tid("settings-migrate").uncheck()
    expect(
        settings.page.get_by_text("Without copying, the graphs you have now stay")
    ).to_be_visible()
    settings.save()
    settings.expect_toast("Settings saved. Your existing graphs were not copied.", "success")
    expect(settings.tid("settings-copy-report")).to_have_count(0)
    assert mongo_count(live_server) == 0
    assert listed(api) == {}  # the library of the new store is empty
    settings.choose_file_storage()
    settings.tid("settings-migrate").uncheck()
    settings.save()
    expect(settings.save_status).to_have_text("All changes saved.")
    assert listed(api) == graphs  # the old files are back in use


def test_an_unreachable_target_keeps_the_old_storage_and_the_graphs(
    settings: SettingsPage, live_server: LiveServer, api: httpx.Client
) -> None:
    graphs = seed_three(api)
    settings.goto()
    live_server.mongo.unreachable = True
    settings.page.allow_http(503, "/api/v1/settings")  # the save is refused with a 503
    settings.choose_mongo_storage("main", DATABASE)
    settings.save()
    expect(settings.tid("settings-error")).to_contain_text("Settings were not saved")
    settings.expect_toast("Settings were not saved.", "error")
    assert settings.stored()["storage_backend"] == "file"
    assert listed(api) == graphs
    live_server.mongo.unreachable = False  # the server is back: the same form now saves
    settings.save()
    settings.expect_toast("Settings saved. 3 graphs copied to the new location.", "success")
    assert settings.stored()["storage_backend"] == "mongo"
    assert mongo_count(live_server) == 3
