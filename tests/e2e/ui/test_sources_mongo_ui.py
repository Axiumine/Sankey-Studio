# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""B5, part 4: the MongoDB tab against the mongomock connection of the test server.

The server has one connection (``main``, default database ``flows``) and the collection
``flows.transfers`` (``from``, ``to``, ``amount``, ``kind``). Covered: the pickers and their
suggestions, the sample documents with "Use the suggested fields", saving and reloading a Mongo
graph, counting instead of summing, the server's messages for a dangerous or malformed pipeline,
and a MongoDB that is switched off. No real MongoDB is involved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import (
    FLOWS_COLLECTION,
    FLOWS_DATABASE,
    mongo_settings,
    seed_flows,
    unique_name,
)
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_a_editor import EditGraphPage, EditorPage
from tests.e2e.support.ui_a_mongo import MongoTab
from tests.e2e.support.ui_a_viewer import ViewerPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.watch import WatchedPage

GROUP_BY_PAIR = (
    '[{"$group": {"_id": {"source": "$from", "target": "$to"}, "value": {"$sum": "$amount"}}},'
    ' {"$project": {"source": "$_id.source", "target": "$_id.target", "value": 1, "_id": 0}}]'
)
OUT_STAGE = '[{"$out": "stolen"}]'
STATS = {"nodes": 6, "links": 5, "total_in": 3000, "total_out": 3000, "columns": 3}


@pytest.fixture(scope="module")
def mongo_server(module_make_server: ServerFactory) -> LiveServer:
    return module_make_server(
        settings=mongo_settings("main", FLOWS_DATABASE), seed_mongo=seed_flows
    )


@pytest.fixture
def live_server(mongo_server: LiveServer) -> LiveServer:
    return mongo_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    return editor


@pytest.fixture
def mongo(editor: EditorPage) -> MongoTab:
    tab = MongoTab(editor.page)
    tab.open()
    return tab


# ------------------------------------------------------------------------------ pickers


def step_pickers_suggest_names_and_the_sample_fills_the_fields(
    editor: EditorPage, mongo: MongoTab
) -> None:
    expect(mongo.tid("mongo-connection")).to_have_value("main")
    expect(mongo.tid("mongo-database")).to_have_attribute("placeholder", FLOWS_DATABASE)
    hint = "Leave empty to use the connection's default database."
    expect(editor.page.get_by_text(hint)).to_be_visible()
    expect(mongo.tid("mongo-no-connections")).to_have_count(0)
    mongo.expect_suggestions("mongo-database", [FLOWS_DATABASE])
    mongo.expect_suggestions("mongo-collection", [FLOWS_COLLECTION])

    mongo.tid("mongo-collection").fill(FLOWS_COLLECTION)
    mongo.show_sample()
    sample = mongo.tid("mongo-sample")
    expect(sample).to_contain_text("Document 1: 5 fields")
    expect(sample).to_contain_text("Document 5: 5 fields")
    expect(mongo.tid("mongo-suggest")).to_be_visible()
    mongo.expect_fields(source="", target="", value="", category="")

    mongo.tid("mongo-suggest").click()

    mongo.expect_fields(source="from", target="to", value="amount", category="kind")
    editor.wait_preview()
    editor.expect_stats(**STATS, categories=5)
    expect(editor.tid("chart-tab-donut")).to_be_visible()
    expect(editor.tid("section-source")).to_contain_text("main / transfers, 5 links, 6 nodes")


def step_counting_documents_replaces_the_value_field(editor: EditorPage, mongo: MongoTab) -> None:
    mongo.counting_switch.check()
    editor.wait_preview()
    expect(mongo.field("value")).to_be_disabled()
    editor.expect_stats(nodes=6, links=5, total_in=1, total_out=4, columns=3, categories=5)

    mongo.counting_switch.uncheck()
    editor.wait_preview()
    expect(mongo.field("value")).to_be_enabled()
    editor.expect_stats(**STATS, categories=5)


def step_the_graph_is_saved_with_its_fields_and_comes_back(
    editor: EditorPage, mongo: MongoTab, api: httpx.Client
) -> None:
    editor.set_name(unique_name("From Mongo"))
    graph_id = editor.save()

    stored = json_of(api.get(f"/api/v1/graphs/{graph_id}"))["source"]
    assert (stored["type"], stored["connection"], stored["collection"]) == (
        "mongo",
        "main",
        "transfers",
    )
    assert (stored["source_field"], stored["target_field"], stored["value_field"]) == (
        "from",
        "to",
        "amount",
    )
    assert stored["category_field"] == "kind"

    editor.page.reload()
    reopened = EditGraphPage(editor.page, editor.server)
    reopened.expect_ready()
    expect(mongo.tid("source-tab-mongo")).to_have_attribute("aria-selected", "true")
    expect(mongo.tid("mongo-collection")).to_have_value(FLOWS_COLLECTION)
    mongo.expect_fields(source="from", target="to", value="amount", category="kind")
    reopened.wait_preview()
    reopened.expect_stats(**STATS, categories=5)

    viewer = ViewerPage(editor.page, editor.server)
    viewer.open(graph_id)
    expect(viewer.tid("stats")).to_contain_text("3,000")


def test_the_mongo_tab_suggests_fields_counts_documents_and_saves_a_graph_that_comes_back(
    editor: EditorPage, mongo: MongoTab, api: httpx.Client
) -> None:
    step_pickers_suggest_names_and_the_sample_fills_the_fields(editor, mongo)
    step_counting_documents_replaces_the_value_field(editor, mongo)
    step_the_graph_is_saved_with_its_fields_and_comes_back(editor, mongo, api)


# ------------------------------------------------------------------------------ errors


def test_dangerous_pipelines_and_filters_show_the_servers_message_and_write_nothing(
    page: WatchedPage, editor: EditorPage, mongo: MongoTab, mongo_server: LiveServer
) -> None:
    page.allow_http(422, "/api/v1/preview")
    page.allow_http(422, "/api/v1/entries")
    mongo.tid("mongo-collection").fill(FLOWS_COLLECTION)
    mongo.set_mode("aggregate")

    mongo.tid("mongo-pipeline").fill('[{"$group": ')
    expect(page.locator("#main .field-error:visible")).to_contain_text("not valid JSON yet")

    mongo.tid("mongo-pipeline").fill(OUT_STAGE)
    editor.wait_settled()

    mongo.expect_field_errors(["MongoDB operator $out is not allowed (read-only)"])
    expect(editor.tid("section-source")).to_contain_text("1 problem")
    expect(editor.tid("state-error").first).to_be_visible()
    assert "stolen" not in mongo_server.mongo[FLOWS_DATABASE].list_collection_names()

    mongo.tid("mongo-pipeline").fill(GROUP_BY_PAIR)
    editor.wait_preview()

    mongo.expect_field_errors([])
    editor.expect_stats(**STATS)
    expect(editor.tid("section-source")).not_to_contain_text("1 problem")

    # Find mode: a code operator in the filter is refused the same way, a plain filter works.
    mongo.set_mode("find")
    mongo.fill_fields(source="from", target="to", value="amount")
    mongo.tid("mongo-filter").fill('{"$where": "this.amount > 0"}')
    editor.wait_settled()
    mongo.expect_field_errors(["MongoDB operator $where is not allowed (read-only)"])
    mongo.tid("mongo-filter").fill('{"kind": "Food"}')
    editor.wait_preview()
    mongo.expect_field_errors([])
    editor.expect_stats(nodes=2, links=1, total_in=640, total_out=640, columns=2)
