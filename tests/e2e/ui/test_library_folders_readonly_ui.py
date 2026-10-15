"""E2E.md B.8, the library collections on a remote read-only server.

``remote_mode=True`` is ``--allow-remote`` without ``--allow-remote-writes``. The collections and
graphs are put in through the server's own services (what the owner did before sharing it). The
browser can browse the tree, open collections and graphs and export, but every control that
changes the library is locked, nothing non-GET is sent, and a request made around the buttons is
refused with 403.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest
from playwright.sync_api import expect

from sankey_studio.models import FolderCreate, GraphCreate
from tests.e2e.support.builders import graph_create, unique_name
from tests.e2e.support.clients import fetch_json
from tests.e2e.support.ui_b_dnd import DragLibrary
from tests.e2e.support.ui_b_folders import FolderLibrary

if TYPE_CHECKING:
    from playwright.sync_api import Request

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.watch import WatchedPage

NOT_AVAILABLE = "Not available: this server is read-only"


class Seeded(NamedTuple):
    top: str
    inner: str
    filed: str
    loose: str


@pytest.fixture
def live_server(make_server: ServerFactory) -> LiveServer:
    return make_server(remote_mode=True)


@pytest.fixture
def seeded(live_server: LiveServer) -> Seeded:
    """One collection with a graph and an empty collection below it, and one loose graph."""
    folders, graphs = live_server.services.folders(), live_server.services.graphs()
    top = folders.create_folder(FolderCreate(name=unique_name("Top")))
    inner = folders.create_folder(FolderCreate(name=unique_name("Inner"), parent_id=top.id))
    filed, loose = unique_name("Filed"), unique_name("Loose")
    graphs.create(GraphCreate.model_validate(graph_create(filed)), folder_id=top.id)
    graphs.create(GraphCreate.model_validate(graph_create(loose)))
    return Seeded(top.name, inner.name, filed, loose)


def record_writes(page: WatchedPage) -> list[str]:
    """The URL of every non-GET request the page makes from now on."""
    writes: list[str] = []

    def note(request: Request) -> None:
        if request.method != "GET":
            writes.append(request.url)

    page.on("request", note)
    return writes


def test_the_tree_can_be_browsed_but_every_control_that_changes_it_is_locked(
    page: WatchedPage, live_server: LiveServer, seeded: Seeded
) -> None:
    writes = record_writes(page)
    library = FolderLibrary(page, live_server)
    library.goto()
    expect(library.tid("read-only-banner")).to_contain_text("Read-only")
    expect(page.locator(".readonly-note")).to_contain_text("moving")
    new_folder = library.tid("folder-new")
    expect(new_folder).to_be_disabled()
    expect(new_folder).to_have_attribute("title", NOT_AVAILABLE)
    card = library.folder_card(seeded.top)
    for action in ("folder-rename", "folder-move", "folder-delete"):
        expect(card.get_by_test_id(action)).to_be_disabled()
        expect(card.get_by_test_id(action)).to_have_attribute("title", NOT_AVAILABLE)
    expect(library.card(seeded.loose).get_by_test_id("graph-move")).to_be_disabled()
    library.tick(seeded.loose).check()
    expect(library.tid("selection-move")).to_be_disabled()
    library.open_folder(seeded.top)
    expect(library.crumbs).to_have_text(["Library", seeded.top])
    library.expect_names([seeded.filed])
    expect(library.folder_names).to_have_text([seeded.inner])  # browsing goes on below
    new_graph = library.tid("folder-new-graph")
    expect(new_graph).to_have_attribute("aria-disabled", "true")
    assert new_graph.get_attribute("href") is None  # a locked link has no address at all
    library.open_folder(seeded.inner)
    assert writes == []  # nothing was sent to the server


def test_an_empty_collection_does_not_offer_to_create_anything_here(
    page: WatchedPage, live_server: LiveServer, seeded: Seeded
) -> None:
    library = FolderLibrary(page, live_server)
    library.goto()
    library.open_folder(seeded.top)
    library.open_folder(seeded.inner)
    empty = library.tid("library-folder-empty")
    expect(empty).to_contain_text("This server is read-only, so graphs cannot be created or moved")
    expect(empty.get_by_role("link")).to_have_count(0)
    expect(empty.get_by_role("button")).to_have_count(0)


def test_nothing_is_draggable_and_a_drag_started_by_hand_does_nothing(
    page: WatchedPage, live_server: LiveServer, seeded: Seeded
) -> None:
    library = DragLibrary(page, live_server)
    library.goto()
    writes = library.record_writes()
    folder, graph = library.folder_card(seeded.top), library.card(seeded.loose)
    for card in (folder, graph):
        assert card.get_attribute("draggable") is None
    transfer = library.begin(graph)
    assert not library.has_private_data(transfer)
    assert library.over(folder, transfer) is False
    expect(page.locator("[data-dragging], [data-drop]")).to_have_count(0)
    assert writes == []


def test_a_browser_that_bypasses_the_buttons_is_refused_by_the_server(
    page: WatchedPage, live_server: LiveServer, seeded: Seeded
) -> None:
    library = FolderLibrary(page, live_server)
    library.goto()
    page.allow_http(403, "/api/v1/")  # these writes are the point of the test
    folder_id = library.folder_id(seeded.top)
    attempts = {
        "create": ("POST", "/api/v1/folders", {"name": "sneaky", "parent_id": None}),
        "rename": ("PUT", f"/api/v1/folders/{folder_id}", {"name": "x", "parent_id": None}),
        "delete": ("DELETE", f"/api/v1/folders/{folder_id}", None),
        "move": ("POST", "/api/v1/graphs/move", {"ids": ["0" * 32], "folder_id": None}),
    }
    for method, path, body in attempts.values():
        answer = fetch_json(page, method, path, body)
        assert (answer.status, answer.json["error"]["code"]) == (403, "read_only_mode")
    page.reload()
    library.expect_ready()
    expect(library.folder_names).to_have_text([seeded.top])  # nothing changed
