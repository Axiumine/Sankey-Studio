"""The library page boots the scope ``?folder=`` names (the folder UI itself comes later).

The server embeds the graphs directly in the folder (or at the top level) and the page paints them
at once: ``/`` shows only the graphs outside every folder, ``/?folder=<id>`` the ones inside it, an
unknown or malformed id the top level, and none of them shows an error. A hostile collection name
is inert. ``/graphs/new?folder=`` opens the editor as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import graph_create, unique_name
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.ui_b_hostile import Inert
from tests.e2e.support.ui_b_library import LibraryPage

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

HOSTILE = "<img src=x onerror=alert(1)>"


class Library:
    """A folder with one graph in it and two graphs at the top level, on a server of its own."""

    def __init__(self, server: LiveServer) -> None:
        self.folder_name = unique_name("Folder")
        self.filed = unique_name("Filed")
        self.loose = [unique_name("Loose"), unique_name("Loose")]
        with make_client(server) as api:
            folder = json_of(api.post("/api/v1/folders", json={"name": self.folder_name}), 201)
            self.folder_id = str(folder["id"])
            body = graph_create(self.filed)
            json_of(api.post("/api/v1/graphs", params={"folder": self.folder_id}, json=body), 201)
            for name in self.loose:
                json_of(api.post("/api/v1/graphs", json=graph_create(name)), 201)


@pytest.fixture
def seeded(live_server: LiveServer) -> Library:
    return Library(live_server)


def test_the_top_level_shows_only_the_graphs_outside_every_folder(
    page: WatchedPage, live_server: LiveServer, seeded: Library
) -> None:
    library = LibraryPage(page, live_server)
    library.goto()
    shown = library.names.all_inner_texts()
    assert seeded.filed not in shown
    assert set(seeded.loose) <= set(shown)
    expect(library.tid("state-error")).to_have_count(0)


def test_a_folder_shows_the_graphs_inside_it(
    page: WatchedPage, live_server: LiveServer, seeded: Library
) -> None:
    library = LibraryPage(page, live_server)
    library.goto(f"?folder={seeded.folder_id}")
    expect(library.names).to_have_text([seeded.filed])
    expect(library.tid("state-error")).to_have_count(0)


@pytest.mark.parametrize("value", ["../etc/passwd", "root", "%00", ""])
def test_an_unknown_or_malformed_folder_opens_the_top_level_without_an_error(
    page: WatchedPage, live_server: LiveServer, seeded: Library, value: str
) -> None:
    library = LibraryPage(page, live_server)
    response = library.goto(f"?folder={value}")
    assert response is not None
    assert response.status == 200
    shown = library.names.all_inner_texts()
    assert seeded.filed not in shown
    assert set(seeded.loose) <= set(shown)
    expect(library.tid("state-error")).to_have_count(0)


def test_a_hostile_collection_name_is_inert_on_the_page(
    page: WatchedPage, live_server: LiveServer
) -> None:
    with make_client(live_server) as api:
        folder = json_of(api.post("/api/v1/folders", json={"name": HOSTILE}), 201)
        name = unique_name("Inside")
        body = graph_create(name)
        json_of(api.post("/api/v1/graphs", params={"folder": folder["id"]}, json=body), 201)
    inert = Inert.watch(page)
    library = LibraryPage(page, live_server)
    library.goto(f"?folder={folder['id']}")
    expect(library.names).to_have_text([name])
    assert inert.dialogs == []
    assert inert.injected() == {}


def test_the_new_graph_page_opens_with_a_folder_in_the_address(
    page: WatchedPage, live_server: LiveServer, seeded: Library
) -> None:
    page.goto(live_server.url_for("/graphs/new") + f"?folder={seeded.folder_id}")
    expect(page.locator("main[data-page=new]")).to_be_visible()
    expect(page.get_by_test_id("state-error")).to_have_count(0)
