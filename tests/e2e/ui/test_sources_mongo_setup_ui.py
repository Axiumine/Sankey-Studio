# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""B5, part 5: the MongoDB tab before and without a working connection.

No connection yet (a pointer to Settings, "Check again" finds one added meanwhile) and a MongoDB
that is switched off (the failures are said in words, the names can still be typed, and the
chart comes back by itself once the server answers). Each test builds its own server: the
preview cache keeps Mongo results for a while, so a shared server would hide an outage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from tests.e2e.support.builders import (
    FLOWS_COLLECTION,
    FLOWS_DATABASE,
    MONGO_URI,
    mongo_settings,
    seed_flows,
)
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_mongo import MongoTab

if TYPE_CHECKING:
    from playwright.sync_api import ViewportSize

    from tests.e2e.support.browser import ColorScheme
    from tests.e2e.support.server import ServerFactory
    from tests.e2e.support.session import PageOpener

UNREACHABLE = "MongoDB connection 'main' is unreachable"


def test_without_a_connection_the_tab_points_to_settings_and_check_again_finds_a_new_one(
    make_server: ServerFactory,
    open_page: PageOpener,
    color_scheme: ColorScheme,
    viewport: ViewportSize,
) -> None:
    server = make_server()
    page = open_page(server, color_scheme=color_scheme, viewport=viewport)
    editor = EditorPage(page, server)
    editor.goto()
    mongo = MongoTab(page)
    mongo.open()
    notice = mongo.tid("mongo-no-connections")
    expect(notice).to_contain_text("No MongoDB connections yet")
    expect(notice.get_by_role("link", name="Open Settings")).to_have_attribute("href", "/settings")
    expect(mongo.tid("mongo-connection")).to_have_count(0)

    body = {"mongo_connections": [{"name": "late", "uri": MONGO_URI, "default_database": "flows"}]}
    with make_client(server) as api:
        json_of(api.put("/api/v1/settings", json=body))
    notice.get_by_role("button", name="Check again").click()

    connection = mongo.tid("mongo-connection")
    expect(connection).to_contain_text("late")
    expect(notice).to_have_count(0)
    expect(connection).to_have_value("late")
    expect(mongo.tid("mongo-database")).to_have_attribute("placeholder", "flows")
    expect(mongo.tid("source-tab-mongo")).to_have_attribute("aria-selected", "true")


def test_a_mongodb_that_is_switched_off_is_explained_and_the_chart_returns_when_it_is_back(
    make_server: ServerFactory,
    open_page: PageOpener,
    color_scheme: ColorScheme,
    viewport: ViewportSize,
) -> None:
    server = make_server(settings=mongo_settings("main", FLOWS_DATABASE), seed_mongo=seed_flows)
    server.mongo.unreachable = True
    page = open_page(server, color_scheme=color_scheme, viewport=viewport)
    # The refusals of a MongoDB that is off: the two pickers, then the preview and the entries.
    for path in (
        "/mongo/main/databases",
        "/mongo/main/collections",
        "/api/v1/preview",
        "/api/v1/entries",
    ):
        page.allow_http(422, path)
    editor = EditorPage(page, server)
    editor.goto()
    mongo = MongoTab(page)
    mongo.open()

    expect(
        page.get_by_text(f"Could not list databases ({UNREACHABLE}). You can still type a name.")
    ).to_be_visible()
    mongo.tid("mongo-collection").fill(FLOWS_COLLECTION)
    mongo.fill_fields(source="from", target="to", value="amount")

    expect(editor.tid("state-error").first).to_contain_text(UNREACHABLE)
    expect(editor.tid("section-source")).to_contain_text("1 problem")
    expect(editor.tid("sankey-chart")).to_be_hidden()

    server.mongo.unreachable = False
    mongo.fill_fields(value="amount ")
    mongo.fill_fields(value="amount")
    editor.wait_preview()

    editor.expect_stats(nodes=6, links=5, total_in=3000, total_out=3000, columns=3)
    expect(editor.tid("state-error")).to_have_count(0)
    expect(editor.tid("section-source")).not_to_contain_text("1 problem")
