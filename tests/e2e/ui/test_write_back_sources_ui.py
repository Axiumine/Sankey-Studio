"""D1: the write-back dialog for a MongoDB collection (mongomock), an aggregate source and a
read-only remote server.

``flows.transfers`` (``from``, ``to``, ``amount``, ``kind``) is read through the ``main``
connection. Accepting changes the ``kind`` field of the documents of the pair; a database user
without write rights keeps the edit in the graph with the server's sentence; an aggregation is
never written and never asks; a read-only remote server never asks and says so once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from sankey_studio.models import GraphCreate
from tests.e2e.support.builders import (
    FLOWS_COLLECTION,
    FLOWS_DATABASE,
    graph_create,
    graph_draft,
    mongo_settings,
    seed_flows,
    unique_name,
)
from tests.e2e.support.ui_a_editor import EditGraphPage
from tests.e2e.support.ui_a_edits import ConsentDialog, WriteBackStatus, mongo_graph, write_file
from tests.e2e.support.ui_a_entries import EntriesPanel

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.session import PageOpener
    from tests.e2e.support.watch import WatchedPage

RENT = ("Account", "Rent")
FOOD = ("Account", "Food")
GROUP_BY_PAIR = [
    {"$group": {"_id": {"source": "$from", "target": "$to"}, "value": {"$sum": "$amount"}}},
    {"$project": {"source": "$_id.source", "target": "$_id.target", "value": 1, "_id": 0}},
]
DENIED = "The database user may not write there, so your change stays in this graph."
AGGREGATE = "This collection is read through an aggregation, so your change stays in this graph."
READ_ONLY = "This server is read-only here: your change stays in this graph"


@pytest.fixture
def live_server(make_server: ServerFactory) -> LiveServer:
    return make_server(settings=mongo_settings("main", FLOWS_DATABASE), seed_mongo=seed_flows)


def kind_of(server: LiveServer, source: str, target: str) -> str:
    collection = server.mongo[FLOWS_DATABASE][FLOWS_COLLECTION]
    document: dict[str, Any] = collection.find_one({"from": source, "to": target}) or {}
    return str(document["kind"])


def open_editor(page: WatchedPage, server: LiveServer, graph_id: str) -> EditGraphPage:
    editor = EditGraphPage(page, server)
    editor.open(graph_id)
    return editor


def test_accepting_changes_the_documents_of_the_pair(
    live_server: LiveServer, page: WatchedPage, api: httpx.Client
) -> None:
    editor = open_editor(page, live_server, mongo_graph(api, unique_name("Flows")))
    consent, entries = ConsentDialog(page), EntriesPanel(page)

    entries.set_category(*RENT, "Home")

    consent.expect_open()
    expect(consent.dialog).to_contain_text("main / flows.transfers")
    expect(consent.dialog).to_contain_text("1 document will be changed.")
    expect(consent.dialog).to_contain_text("needs write permission")
    consent.accept()
    editor.expect_toast("Updated 1 document in main / flows.transfers.", "success")
    assert kind_of(live_server, *RENT) == "Home"
    expect(entries.cell(*RENT)).to_have_value("Home")
    WriteBackStatus(page).expect_status("written to the source")


def test_a_database_user_without_write_rights_keeps_the_edit_in_the_graph(
    live_server: LiveServer, page: WatchedPage, api: httpx.Client
) -> None:
    editor = open_editor(page, live_server, mongo_graph(api, unique_name("Flows")))
    consent, entries = ConsentDialog(page), EntriesPanel(page)
    live_server.mongo.read_only = True
    before = kind_of(live_server, *RENT)

    entries.set_category(*RENT, "Home")
    consent.accept()

    editor.expect_toast(DENIED, "info")
    assert kind_of(live_server, *RENT) == before
    expect(entries.cell(*RENT)).to_have_value("Home")
    expect(entries.error).to_have_count(0)


def test_an_aggregation_is_never_written_and_never_asks(
    live_server: LiveServer, page: WatchedPage, api: httpx.Client
) -> None:
    graph_id = mongo_graph(
        api,
        unique_name("Aggregated"),
        mode="aggregate",
        pipeline=GROUP_BY_PAIR,
        source_field="source",
        target_field="target",
        value_field="value",
        category_field=None,
    )
    editor = open_editor(page, live_server, graph_id)
    entries = EntriesPanel(page)

    entries.set_category(*RENT, "Home")

    editor.expect_toast(AGGREGATE, "info")
    expect(ConsentDialog(page).dialog).to_have_count(0)
    expect(entries.cell(*RENT)).to_have_value("Home")
    assert kind_of(live_server, *RENT) == "Housing"


def test_a_read_only_remote_server_keeps_the_edit_and_says_so_once(
    make_server: ServerFactory, open_page: PageOpener
) -> None:
    server = make_server(remote_mode=True)
    write_file(server, "budget.csv")
    source = {"origin": "file", "path": "budget.csv", "content": None}
    body = graph_create(unique_name("Read only"), graph_draft(source=source))
    stored = server.services.graphs().create(GraphCreate.model_validate(body))
    page = open_page(server, color_scheme="light", viewport={"width": 1280, "height": 900})
    editor = open_editor(page, server, stored.id)
    entries = EntriesPanel(page)

    entries.set_category("Budget", "Rent", "Housing")
    editor.expect_toast(READ_ONLY, "info")
    entries.set_category("Budget", "Food", "Living")

    expect(entries.cell("Budget", "Food")).to_have_value("Living")
    expect(editor.toasts().filter(has_text=READ_ONLY)).to_have_count(1)
    expect(ConsentDialog(page).dialog).to_have_count(0)
    assert "Housing" not in (server.sources_dir / "budget.csv").read_text()
