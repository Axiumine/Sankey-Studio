"""``EditorPage``: the part of the editor (``/graphs/<id>/edit``) that the UI-B suites drive.

Only what the library, resilience and security suites need: name, save, the save status line, the
conflict banner and the draft source box. The full editor is the business of the UI-A suites.

Dual mode, like ``ui_a_editor.EditorPage`` (see ``ui_a_chrome`` and ``ui_a_wizard``):
``expect_ready`` finishes the new-graph wizard when the page has one; ``rename``,
``expect_name``, ``expect_description``, ``description_value`` and ``set_details`` go through the
details dialog when the page has one and use the inline fields otherwise.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.ui_a_chrome import EditorChrome
from tests.e2e.support.ui_a_wizard import NewGraphWizard, finish_wizard
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
        self.chrome = EditorChrome(page)
        self.wizard_name: str | None = None

    def url_for(self, suffix: str = "") -> str:
        path = "/graphs/new" if self.graph_id is None else f"/graphs/{self.graph_id}/edit"
        return self.server.url_for(path) + suffix

    def expect_ready(self) -> None:
        wait_shell(self.page)
        wait_page(self.page, "new" if self.graph_id is None else "edit")
        if self.graph_id is None:
            self.wizard_name = finish_wizard(self.page)
        wait_idle(self.page)
        wait_editor(self.page)

    def goto_wizard(self) -> NewGraphWizard:
        """Open ``/graphs/new`` and stop at step 1 of the wizard (for the wizard's own tests)."""
        assert self.graph_id is None, "the wizard belongs to the new-graph page"
        self.page.goto(self.url_for())
        wait_shell(self.page)
        wait_page(self.page, "new")
        wizard = NewGraphWizard(self.page)
        wizard.expect_showing()
        return wizard

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
        self.chrome.set_details(name=name)
        expect(self.status).to_contain_text("Unsaved changes")

    def set_details(
        self, *, name: str | None = None, description: str | None = None, tags: tuple[str, ...] = ()
    ) -> None:
        self.chrome.set_details(name=name, description=description, tags=tags)

    def expect_name(self, name: str) -> None:
        self.chrome.expect_details(name=name)

    def expect_description(self, text: str) -> None:
        self.chrome.expect_details(description=text)

    def expect_details(
        self, *, name: str | None = None, description: str | None = None, tags: tuple[str, ...] = ()
    ) -> None:
        self.chrome.expect_details(name=name, description=description, tags=tags)

    def description_value(self) -> str:
        return self.chrome.description_value()

    def open_section(self, section: Literal["style"]) -> None:
        """Make the Style controls usable (the chart settings popover, or the section)."""
        assert section == "style", "only the Style section is driven from here"
        self.chrome.open_style()

    def open_export(self) -> None:
        """Make the export buttons usable (the chart settings popover, when the page has one)."""
        self.chrome.open_export()

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
