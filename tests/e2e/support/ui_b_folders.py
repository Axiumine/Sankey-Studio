"""``FolderLibrary``: the library page object with its collections ("folders" in code, UI.md 4.2).

The user-visible word is "collection"; test ids, URLs and code say ``folder``.

Locators: ``breadcrumb``, ``crumbs``, ``folder_cards``, ``folder_names``, ``folder_card(name)``,
``name_dialog``, ``move_dialog``, ``move_option(name)`` (``None`` = the library itself).
Actions (each waits for its own outcome through the DOM, never for a fixed time): ``new_folder``,
``open_folder``, ``rename_folder``, ``move_folder``, ``delete_folder``, ``move_graph``,
``move_picked``. Each one that opens a dialog takes the name of the target collection (``None`` =
the library's top level).

API helpers: ``seed_folder(api, name, parent_id=None)`` creates a collection (201) and returns its
record; ``seed_filed_graph(api, name, folder_id)`` saves a graph into it (``POST /graphs?folder=``).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from playwright.sync_api import expect

from tests.e2e.support.builders import graph_create
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_b_library import LibraryPage, exact
from tests.e2e.support.uiwait import wait_idle

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import Locator

FOLDER_URL = re.compile(r"[?&]folder=[0-9a-f]{32}")


def seed_folder(api: httpx.Client, name: str, parent_id: str | None = None) -> dict[str, Any]:
    """Create a collection through the API and return its ``FolderDefinition`` (asserts the 201)."""
    body = {"name": name, "parent_id": parent_id}
    return dict(json_of(api.post("/api/v1/folders", json=body), 201))


def seed_filed_graph(api: httpx.Client, name: str, folder_id: str) -> dict[str, Any]:
    """Save a graph named ``name`` inside the collection ``folder_id`` and return it."""
    response = api.post("/api/v1/graphs", params={"folder": folder_id}, json=graph_create(name))
    return dict(json_of(response, 201))


class FolderLibrary(LibraryPage):
    # ------------------------------------------------------------------ locators

    @property
    def breadcrumb(self) -> Locator:
        return self.tid("folder-breadcrumb")

    @property
    def crumbs(self) -> Locator:
        return self.tid("folder-crumb")

    @property
    def folder_cards(self) -> Locator:
        return self.tid("folder-card")

    @property
    def folder_names(self) -> Locator:
        """The name links of the collection cards of this level, in order."""
        return self.tid("folder-open")

    @property
    def name_dialog(self) -> Locator:
        return self.tid("folder-dialog")

    @property
    def move_dialog(self) -> Locator:
        return self.tid("move-dialog")

    def folder_card(self, name: str) -> Locator:
        """The collection card whose name is exactly ``name``."""
        return self.folder_cards.filter(has=self.folder_names.filter(has_text=exact(name)))

    def folder_id(self, name: str) -> str:
        """The id of the collection card named ``name``."""
        return str(self.folder_card(name).get_attribute("data-folder-id"))

    def move_option(self, name: str | None) -> Locator:
        """The radio row of ``name`` in the open move dialog (``None`` = the library itself)."""
        if name is None:
            return self.move_dialog.locator("[data-testid=move-option][data-folder-id=root]")
        label = self.page.locator(".move-name").filter(has_text=exact(name))
        return self.tid("move-option").filter(has=label)

    # ------------------------------------------------------------------ dialogs

    def fill_name(self, name: str) -> None:
        """Type ``name`` in the open name dialog and press its confirm button."""
        field = self.tid("folder-name-input")
        field.fill(name)
        self.tid("folder-name-confirm").click()

    def choose_target(self, target: str | None) -> None:
        """Pick ``target`` in the open move dialog and press "Move here"."""
        self.move_option(target).locator("input").check()
        self.tid("move-confirm").click()

    # ------------------------------------------------------------------ actions

    def new_folder(self, name: str) -> None:
        """ "New collection" at this level; waits until the card is there."""
        self.tid("folder-new").click()
        self.fill_name(name)
        expect(self.name_dialog).to_be_hidden()
        expect(self.folder_card(name)).to_be_visible()

    def open_folder(self, name: str) -> None:
        """Follow the card's link (a real page load) and wait for the page."""
        self.folder_card(name).get_by_test_id("folder-open").click()
        expect(self.page).to_have_url(FOLDER_URL)
        self.expect_ready()

    def rename_folder(self, name: str, new_name: str) -> None:
        self.folder_card(name).get_by_test_id("folder-rename").click()
        self.fill_name(new_name)
        expect(self.name_dialog).to_be_hidden()
        expect(self.folder_card(new_name)).to_be_visible()

    def move_folder(self, name: str, target: str | None) -> None:
        self.folder_card(name).get_by_test_id("folder-move").click()
        self.choose_target(target)
        expect(self.move_dialog).to_be_hidden()
        wait_idle(self.page)

    def delete_folder(self, name: str) -> None:
        self.folder_card(name).get_by_test_id("folder-delete").click()
        self.tid("folder-delete-confirm").click()
        expect(self.tid("folder-delete-dialog")).to_be_hidden()
        expect(self.folder_card(name)).to_have_count(0)

    def move_graph(self, graph: str, target: str | None) -> None:
        """ "Move" on the card of ``graph``."""
        self.card(graph).get_by_test_id("graph-move").click()
        self.choose_target(target)
        expect(self.move_dialog).to_be_hidden()
        expect(self.card(graph)).to_have_count(0)

    def move_picked(self, target: str | None) -> None:
        """ "Move to collection" in the selection bar."""
        self.tid("selection-move").click()
        self.choose_target(target)
        expect(self.move_dialog).to_be_hidden()
        expect(self.tid("selection-bar")).to_be_hidden()
