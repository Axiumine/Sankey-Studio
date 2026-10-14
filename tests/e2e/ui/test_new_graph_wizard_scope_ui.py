"""F10 and F5 around the wizard: collections, the default style, a read-only server, the tab strip.

* ``/graphs/new?folder=<id>``: Cancel returns to that collection and the graph is saved inside it
  (a collection that vanished meanwhile makes the graph land at the top level, with a notice).
* The first preview of a new graph never carries ``style.node_order`` from the default style.
* A read-only remote server: the wizard works, it makes no non-GET request, Save stays disabled.
* The inline tab strip asks about graph-only edits before it replaces the source.
Each test has a server of its own (they save, or need other options).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_a_editor import EditGraphPage, EditorPage
from tests.e2e.support.ui_a_wizard import NewGraphWizard, WizardInput
from tests.e2e.support.uiwait import wait_editor

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import Request

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.watch import WatchedPage

READ_ONLY_POSTS = ("/api/v1/preview", "/api/v1/entries", "/api/v1/sources/detect")
CATEGORISED = graph_draft(
    BUDGET.csv,
    transform={"entry_categories": [{"source": "Budget", "target": "Rent", "category": "Fun"}]},
)


def make_folder(api: httpx.Client, name: str) -> str:
    return str(json_of(api.post("/api/v1/folders", json={"name": name}), 201)["id"])


def open_in_folder(page: WatchedPage, server: LiveServer, folder_id: str) -> NewGraphWizard:
    editor = EditorPage(page, server)
    page.goto(editor.url_for(f"?folder={folder_id}"))
    wizard = NewGraphWizard(page)
    wizard.expect_showing()
    return wizard


# ------------------------------------------------------------------------------ collections


def test_cancel_returns_to_the_collection_the_wizard_was_opened_in(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    folder = make_folder(api, unique_name("Where I came from"))

    wizard = open_in_folder(page, live_server, folder)

    expect(wizard.tid("wizard-cancel")).to_have_attribute("href", f"/?folder={folder}")
    wizard.tid("wizard-cancel").click()
    page.wait_for_url(re.compile(rf"/\?folder={folder}$"))


def test_a_graph_started_in_a_collection_is_saved_inside_it(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    folder = make_folder(api, unique_name("Filing"))
    name = unique_name("Filed by the wizard")
    wizard = open_in_folder(page, live_server, folder)
    wizard.complete(WizardInput(name=name))
    wait_editor(page)

    graph_id = EditorPage(page, live_server).save()

    assert json_of(api.get(f"/api/v1/graphs/{graph_id}"))["folder_id"] == folder
    listed = json_of(api.get("/api/v1/graphs", params={"folder": folder}))["items"]
    assert [item["name"] for item in listed] == [name]
    assert json_of(api.get("/api/v1/graphs", params={"folder": "root"}))["total"] == 0


def test_a_collection_that_vanished_before_saving_makes_the_graph_land_at_the_top_level(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    folder = make_folder(api, unique_name("Short lived"))
    wizard = open_in_folder(page, live_server, folder)
    wizard.complete(WizardInput(name=unique_name("Orphan")))
    wait_editor(page)
    assert api.delete(f"/api/v1/folders/{folder}").status_code == 204
    page.allow_http(404, "/api/v1/graphs")

    editor = EditorPage(page, live_server)
    graph_id = editor.save()

    expect(page.get_by_text("That collection no longer exists")).to_be_visible()
    stored = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    assert stored["folder_id"] is None


# ------------------------------------------------------------------------------ default style


def test_the_first_preview_of_a_new_graph_has_no_node_order_from_the_default_style(
    page: WatchedPage, make_server: ServerFactory
) -> None:
    server = make_server(
        settings={"default_style": {"node_order": ["Salary", "Budget"], "node_pad": 24}}
    )
    bodies: list[dict[str, Any]] = []

    def note(request: Request) -> None:
        if request.method == "POST" and "/api/v1/preview" in request.url:
            bodies.append(dict(request.post_data_json or {}))

    page.on("request", note)
    editor = EditorPage(page, server)
    page.goto(editor.url_for())
    wizard = NewGraphWizard(page)
    wizard.complete(WizardInput(name=unique_name("Default style"), text=BUDGET.csv))
    wait_editor(page)
    editor.wait_preview()

    assert bodies, "the preview was never requested"
    assert "node_order" not in bodies[0]["style"]
    assert bodies[0]["style"]["node_pad"] == 24


# ------------------------------------------------------------------------------ read-only server


def test_a_read_only_server_lets_the_wizard_run_but_never_writes(
    page: WatchedPage, make_server: ServerFactory
) -> None:
    server = make_server(remote_mode=True)
    writes: list[str] = []
    page.on("request", lambda r: writes.append(r.url) if r.method != "GET" else None)
    editor = EditorPage(page, server)
    page.goto(editor.url_for())
    wizard = NewGraphWizard(page)
    wizard.expect_showing()
    wizard.fill_details(unique_name("Read only"))
    wizard.next()
    expect(wizard.root).to_contain_text("This server is read-only: you can draw, not save.")
    wizard.choose_kind("upload")
    expect(wizard.tid("source-upload-input")).to_be_disabled()
    wizard.choose_kind("paste")
    wizard.tid("source-content").fill(BUDGET.csv)
    wizard.create()
    wizard.expect_gone()
    wait_editor(page)
    editor.wait_preview()

    expect(editor.save_button).to_be_disabled()
    expect(editor.save_status).to_contain_text("Read-only server")
    stored = [url for url in writes if not url.split("?")[0].endswith(READ_ONLY_POSTS)]
    assert stored == []  # the POSTs that remain only compute (preview, entries, detect)


# ------------------------------------------------------------------------------ tab strip


def open_saved(
    page: WatchedPage, server: LiveServer, api: httpx.Client
) -> tuple[EditGraphPage, str]:
    saved = seed_graph(api, unique_name("Strip"), CATEGORISED)
    editor = EditGraphPage(page, server)
    editor.open(saved["id"])
    return editor, str(saved["id"])


def stored_categories(api: httpx.Client, graph_id: str) -> list[object]:
    return list(json_of(api.get(f"/api/v1/graphs/{graph_id}"))["transform"]["entry_categories"])


def test_the_tab_strip_asks_before_it_drops_graph_only_edits_and_cancel_changes_nothing(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, graph_id = open_saved(page, live_server, api)
    question = page.get_by_role("dialog", name="Keep your edits to this graph?")

    editor.tid("source-tab-manual").click()

    expect(question).to_be_visible()
    expect(question).to_contain_text("1 category edit")
    question.get_by_role("button", name="Cancel").click()
    expect(question).to_be_hidden()
    expect(editor.tid("source-tab-paste")).to_have_attribute("aria-selected", "true")
    expect(editor.content).to_have_value(BUDGET.csv)
    expect(editor.save_status).to_contain_text("All changes saved")

    editor.tid("source-tab-manual").click()
    question.get_by_role("button", name="Drop them").click()
    expect(editor.tid("source-tab-manual")).to_have_attribute("aria-selected", "true")
    editor.save()
    assert stored_categories(api, graph_id) == []


def test_keeping_the_edits_switches_the_source_and_text_to_upload_asks_nothing(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, graph_id = open_saved(page, live_server, api)
    question = page.get_by_role("dialog", name="Keep your edits to this graph?")

    editor.tid("source-tab-manual").click()
    question.get_by_role("button", name="Keep them").click()
    expect(editor.tid("source-tab-manual")).to_have_attribute("aria-selected", "true")
    editor.tid("source-tab-text").click()
    expect(question).to_be_visible()
    question.get_by_role("button", name="Keep them").click()
    editor.tid("source-tab-upload").click()

    expect(editor.tid("source-tab-upload")).to_have_attribute("aria-selected", "true")
    expect(question).to_be_hidden()
    assert stored_categories(api, graph_id) != []
