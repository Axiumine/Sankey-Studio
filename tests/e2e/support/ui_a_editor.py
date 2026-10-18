# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Page objects of the graph editor for the UI-A suites (``/graphs/new`` and ``/graphs/<id>/edit``).

``EditorPage``   - the new-graph editor: name / tags / description, the pasted source, the chart,
                   stats, warnings, the save bar and the Style / Transform sections.
``EditGraphPage``- the same page for a saved graph (``open(graph_id)``).

All locators are ``data-testid`` ones (docs/ui/editor.md). Waits follow the DOM signals of
``support.uiwait``: ``wait_preview`` after an edit, never a sleep. The entries table lives in
``ui_a_entries.EntriesPanel``, the source tabs in ``ui_a_sources.SourcePanel``.

Dual mode (see ``ui_a_chrome`` and ``ui_a_wizard``): ``expect_ready`` finishes the new-graph wizard
when the page has one (``wizard_name`` is the name it used, ``None`` without a wizard); the name /
description / tags helpers (``set_details``, ``set_name``, ``expect_name``, ``expect_description``,
``expect_details``) go through the details dialog when the page has one and use the inline
fields otherwise; ``open_section("style")`` and ``open_export()`` open the chart settings popover
when the page has one. The plain locators ``name_field`` / ``tags_field`` / ``description_field``
are only on the page while those fields are (the dialog is open).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.ui_a_chrome import DetailsDialog, EditorChrome
from tests.e2e.support.ui_a_wizard import NewGraphWizard, finish_wizard
from tests.e2e.support.uiwait import (
    DONUT_CHART,
    wait_chart,
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

Section = Literal["source", "transform", "style"]
SAVED_URL: Final = re.compile(r"/graphs/([0-9a-f]{32})/edit$")
STAT_LABELS: Final = ("Nodes", "Links", "Total in", "Total out", "Columns")


def number(value: float) -> str:
    """``3800.0`` as ``3,800`` and ``12.5`` as ``12.5``, the way the app formats numbers."""
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,}"


class EditorPage(AppPage):
    """The editor of a new graph."""

    path = "/graphs/new"
    name = "new"

    def __init__(self, page: WatchedPage, server: LiveServer) -> None:
        super().__init__(page, server)
        self.chrome = EditorChrome(page)
        self.wizard_name: str | None = None

    def expect_ready(self) -> None:
        if self.name == "new":
            wait_shell(self.page)
            wait_page(self.page, self.name)
            self.wizard_name = finish_wizard(self.page)
            wait_idle(self.page)
        else:
            super().expect_ready()
        wait_editor(self.page)

    def goto_wizard(self) -> NewGraphWizard:
        """Open ``/graphs/new`` and stop at step 1 of the wizard (for the wizard's own tests)."""
        self.page.goto(self.url_for())
        wait_shell(self.page)
        wait_page(self.page, self.name)
        wizard = NewGraphWizard(self.page)
        wizard.expect_showing()
        return wizard

    # ------------------------------------------------------------------ fields

    @property
    def name_field(self) -> Locator:
        return self.tid("editor-name")

    @property
    def tags_field(self) -> Locator:
        return self.tid("editor-tags")

    @property
    def description_field(self) -> Locator:
        return self.tid("editor-description")

    @property
    def content(self) -> Locator:
        return self.tid("source-content")

    @property
    def save_button(self) -> Locator:
        return self.tid("save-button")

    @property
    def save_status(self) -> Locator:
        return self.tid("save-status")

    def add_tag(self, tag: str) -> None:
        self.tags_field.fill(tag)
        self.tags_field.press("Enter")

    # ------------------------------------------------------------------ details

    def open_details(self) -> DetailsDialog:
        return self.chrome.open_details()

    def set_details(
        self, *, name: str | None = None, description: str | None = None, tags: tuple[str, ...] = ()
    ) -> None:
        self.chrome.set_details(name=name, description=description, tags=tags)

    def set_name(self, name: str) -> None:
        self.chrome.set_details(name=name)

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

    # ------------------------------------------------------------------ data and chart

    def fill_source(self, text: str) -> None:
        """Replace the pasted text (one change, one preview after the debounce); no waiting."""
        self.content.fill(text)

    def paste(self, text: str) -> None:
        """Replace the pasted text and wait until the chart of the new text is drawn."""
        self.fill_source(text)
        self.wait_preview()

    def wait_preview(self) -> None:
        wait_preview(self.page)

    def wait_settled(self) -> None:
        """Preview finished (a failed one included): no pending or running request."""
        wait_idle(self.page)

    def open_donut(self) -> None:
        self.tid("chart-tab-donut").click()
        wait_chart(self.page, DONUT_CHART)

    def open_export(self) -> None:
        """Make the export buttons usable (the chart settings popover, when the page has one)."""
        self.chrome.open_export()

    def open_section(self, section: Section) -> None:
        """Expand a collapsible section (``transform`` / ``style``) when it is collapsed."""
        if section == "style":
            self.chrome.open_style()
            return
        head = self.tid(f"section-{section}")
        if not head.evaluate("el => el.parentElement.open"):
            head.click()
            expect(head.locator("..")).to_have_attribute("open", "")

    def expect_stats(self, *, categories: int | None = None, **expected: float) -> None:
        """The stats strip: ``nodes``, ``links``, ``total_in``, ``total_out``, ``columns``."""
        labels = list(STAT_LABELS) + (["Categories"] if categories is not None else [])
        values = [number(expected[key]) for key in self.stat_keys(expected)]
        if categories is not None:
            values.append(number(categories))
        expect(self.tid("stats").locator("dt")).to_have_text(labels)
        expect(self.tid("stats").locator("dd")).to_have_text(values)

    @staticmethod
    def stat_keys(expected: dict[str, float]) -> list[str]:
        order = ["nodes", "links", "total_in", "total_out", "columns"]
        assert sorted(expected) == sorted(order), f"expect_stats needs exactly {order}"
        return order

    # ------------------------------------------------------------------ saving

    def reopened(self) -> EditGraphPage:
        """The same browser page seen as the editor of a saved graph (after save or reload)."""
        return EditGraphPage(self.page, self.server)

    def save(self) -> str:
        """Click Save, wait until the graph exists and return its id."""
        self.save_button.click()
        self.page.wait_for_url(SAVED_URL)
        expect(self.save_status).to_contain_text("All changes saved")
        found = SAVED_URL.search(self.page.url)
        assert found, f"unexpected address after saving: {self.page.url}"
        return found.group(1)


class EditGraphPage(EditorPage):
    """The editor of a saved graph: ``open(graph_id)``."""

    path = "/graphs/"
    name = "edit"

    def open(self, graph_id: str) -> None:
        self.goto(f"{graph_id}/edit")
        wait_chart(self.page)
