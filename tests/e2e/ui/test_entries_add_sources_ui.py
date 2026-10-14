"""F7 on data the server may write: a text file, a MongoDB collection, a read-only server.

"Add entry" on a graph that reads a file or a collection (mongomock) raises the consent dialog
ABOVE the Add dialog (the focus traps nest: Esc closes only the newest). Accepting writes the
line or the document, "Keep in this graph" adds a graph-only entry that the "Graph-only edits"
chip lists and removes, a read-only server keeps the entry in the graph and says so once.
"""

from __future__ import annotations

import uuid
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
from tests.e2e.support.clients import make_client
from tests.e2e.support.ui_a_editor import EditGraphPage
from tests.e2e.support.ui_a_edits import ConsentDialog, file_graph, mongo_graph, write_file
from tests.e2e.support.ui_a_entries import EntriesPanel

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import Page

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.session import PageOpener
    from tests.e2e.support.watch import WatchedPage

GIFTS = ("Budget", "Gifts")
READ_ONLY = "This server is read-only here: your change stays in this graph"
IN_DIALOG = "document.activeElement.closest('[data-testid=write-back-dialog]') !== null"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


class Open:
    """An editor on a graph that reads its own copy of the budget file."""

    def __init__(self, page: WatchedPage, server: LiveServer, api: httpx.Client) -> None:
        self.file = f"add-{uuid.uuid4().hex[:8]}.csv"
        self.server = server
        self.editor = EditGraphPage(page, server)
        self.entries = EntriesPanel(page)
        self.consent = ConsentDialog(page)
        self.editor.open(file_graph(server, api, unique_name("Add to file"), file=self.file))

    def text(self) -> str:
        return (self.server.sources_dir / self.file).read_text()


@pytest.fixture
def opened(page: WatchedPage, live_server: LiveServer, api: httpx.Client) -> Open:
    return Open(page, live_server, api)


def counts(editor: EditGraphPage) -> tuple[str, str]:
    values = editor.tid("stats").locator("dd")
    return values.nth(0).inner_text(), values.nth(1).inner_text()


def test_accepting_writes_the_line_into_the_file_and_closes_both_dialogs(opened: Open) -> None:
    opened.entries.add_entry(*GIFTS, "50")

    opened.consent.expect_open()
    expect(opened.entries.add_dialog.dialog).to_be_visible()
    expect(opened.consent.dialog).to_contain_text(opened.file)
    expect(opened.consent.dialog).to_contain_text("New entry: Budget to Gifts, value 50.")
    opened.consent.accept()

    opened.consent.expect_gone()
    opened.entries.add_dialog.expect_gone()
    opened.editor.expect_toast(f"Added 1 row in {opened.file}.", "success")
    assert "Budget,Gifts,50" in opened.text().splitlines()
    expect(opened.entries.row(*GIFTS)).to_have_count(1)
    expect(opened.entries.overlays_chip).to_be_hidden()


def test_the_consent_dialog_traps_the_keys_and_escape_closes_only_the_newest(
    opened: Open, page: Page
) -> None:
    opened.entries.add_entry(*GIFTS, "50")
    opened.consent.expect_open()

    for _ in range(6):
        page.keyboard.press("Tab")
        assert page.evaluate(IN_DIALOG)
    page.keyboard.press("Escape")

    opened.consent.expect_gone()
    opened.entries.add_dialog.expect_open()
    expect(opened.entries.add_dialog.submit).to_be_enabled()
    expect(opened.entries.add_dialog.error).to_be_hidden()
    assert "Gifts" not in opened.text()
    page.keyboard.press("Escape")
    opened.entries.add_dialog.expect_gone()
    expect(opened.entries.add_button).to_be_focused()
    expect(opened.entries.row(*GIFTS)).to_have_count(0)


def test_cancelling_the_question_leaves_the_dialog_open_for_another_try(opened: Open) -> None:
    opened.entries.add_entry(*GIFTS, "50")
    opened.consent.cancel()

    opened.consent.expect_gone()
    dialog = opened.entries.add_dialog
    dialog.expect_open()
    expect(dialog.field("value")).to_have_value("50")
    dialog.submit.click()
    opened.consent.expect_open()
    opened.consent.accept()
    dialog.expect_gone()
    assert "Budget,Gifts,50" in opened.text().splitlines()


def test_keeping_the_entry_in_the_graph_lists_it_and_the_list_removes_it(opened: Open) -> None:
    entries = opened.entries
    start = counts(opened.editor)

    entries.add_entry(*GIFTS, "50", "Fun")
    opened.consent.decline()

    entries.add_dialog.expect_gone()
    opened.editor.expect_toast("Entry added.", "success")
    expect(entries.row(*GIFTS)).to_have_count(1)
    expect(entries.overlays_chip).to_have_text("Graph-only edits (1)")
    assert "Gifts" not in opened.text()
    entries.overlays_chip.click()
    expect(entries.overlays.dialog).to_contain_text("These edits are stored in this graph")
    expect(entries.overlays.rows).to_have_text(["Budget to Gifts: 50, category FunRemove"])

    entries.overlays.remove("Budget to Gifts")

    expect(entries.overlays.dialog).to_contain_text("No graph-only edits are left.")
    entries.overlays.dialog.get_by_role("button", name="Done").click()
    expect(entries.row(*GIFTS)).to_have_count(0)
    expect(entries.overlays_chip).to_be_hidden()
    expect(entries.add_button).to_be_focused()
    expect(opened.editor.tid("stats").locator("dd").nth(1)).to_have_text(start[1])


def own_page(server: LiveServer, open_page: PageOpener) -> WatchedPage:
    return open_page(server, color_scheme="light", viewport={"width": 1280, "height": 900})


def test_a_collection_asks_and_accepting_inserts_one_document(
    make_server: ServerFactory, open_page: PageOpener
) -> None:
    server = make_server(settings=mongo_settings("main", FLOWS_DATABASE), seed_mongo=seed_flows)
    with make_client(server) as api:
        graph_id = mongo_graph(api, unique_name("Add to flows"))
    page = own_page(server, open_page)
    editor = EditGraphPage(page, server)
    editor.open(graph_id)
    entries, consent = EntriesPanel(page), ConsentDialog(page)

    entries.add_entry("Account", "Gifts", "50", "Fun")

    consent.expect_open()
    expect(consent.dialog).to_contain_text("main / flows.transfers")
    expect(consent.dialog).to_contain_text("1 document will be added.")
    consent.accept()
    editor.expect_toast("Added 1 document in main / flows.transfers.", "success")
    entries.add_dialog.expect_gone()
    document: dict[str, Any] = (
        server.mongo[FLOWS_DATABASE][FLOWS_COLLECTION].find_one({"to": "Gifts"}) or {}
    )
    assert (document["from"], document["amount"], document["kind"]) == ("Account", 50, "Fun")
    expect(entries.row("Account", "Gifts")).to_have_count(1)


def test_a_read_only_server_keeps_the_entry_in_the_graph_and_says_so_once(
    make_server: ServerFactory, open_page: PageOpener
) -> None:
    server = make_server(remote_mode=True)
    write_file(server, "budget.csv")
    source = {"origin": "file", "path": "budget.csv", "content": None}
    body = graph_create(unique_name("Read only add"), graph_draft(source=source))
    stored = server.services.graphs().create(GraphCreate.model_validate(body))
    page = own_page(server, open_page)
    editor = EditGraphPage(page, server)
    editor.open(stored.id)
    entries = EntriesPanel(page)

    entries.add_entry(*GIFTS, "50")
    editor.expect_toast(READ_ONLY, "info")
    entries.add_entry("Budget", "Cards", "20")

    entries.add_dialog.expect_gone()
    expect(entries.row("Budget", "Cards")).to_have_count(1)
    expect(editor.toasts().filter(has_text=READ_ONLY)).to_have_count(1)
    expect(ConsentDialog(page).dialog).to_have_count(0)
    expect(entries.overlays_chip).to_have_text("Graph-only edits (2)")
    assert "Gifts" not in (server.sources_dir / "budget.csv").read_text()
