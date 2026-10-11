"""``EditorPage``: the part of the editor (``/graphs/<id>/edit``) that the UI-B suites drive.

Only what the library, resilience and security suites need: name, save, the save status line, the
conflict banner and the draft source box. The full editor is the business of the UI-A suites.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.uiwait import (
    wait_editor,
    wait_idle,
    wait_page,
    wait_preview,
    wait_shell,
)

if TYPE_CHECKING:
    from playwright.sync_api import Locator

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage


class EditorPage(AppPage):
    """A graph editor; ``graph_id=None`` is the new-graph page."""

    name = "edit"

    def __init__(self, page: WatchedPage, server: LiveServer, graph_id: str | None) -> None:
        super().__init__(page, server)
        self.graph_id = graph_id

    def url_for(self, suffix: str = "") -> str:
        path = "/graphs/new" if self.graph_id is None else f"/graphs/{self.graph_id}/edit"
        return self.server.url_for(path) + suffix

    def expect_ready(self) -> None:
        wait_shell(self.page)
        wait_page(self.page, "new" if self.graph_id is None else "edit")
        wait_idle(self.page)
        wait_editor(self.page)

    # ------------------------------------------------------------------ locators

    @property
    def name_field(self) -> Locator:
        return self.tid("editor-name")

    @property
    def status(self) -> Locator:
        return self.tid("save-status")

    @property
    def banner(self) -> Locator:
        return self.tid("conflict-banner")

    @property
    def source(self) -> Locator:
        return self.tid("source-content")

    # ------------------------------------------------------------------ actions

    def rename(self, name: str) -> None:
        self.name_field.fill(name)
        expect(self.status).to_contain_text("Unsaved changes")

    def expect_settled(self) -> None:
        """Nothing is in flight any more: the preview is drawn and the format detection answered.

        The harness stops the server before it closes the page, so a test that ends while the
        editor still has a request on its way would log a refused connection.
        """
        wait_preview(self.page)
        if self.tid("source-format").input_value() == "auto":  # only then the server is asked
            expect(self.page.get_by_text(re.compile(r"^Detected: "))).to_be_visible()

    def save(self) -> None:
        self.tid("save-button").click()

    def rename_and_save(self, name: str, revision: int) -> None:
        """Rename, save and wait until the server has stored ``revision``."""
        self.rename(name)
        self.save()
        expect(self.status).to_contain_text(f"Revision {revision}")
