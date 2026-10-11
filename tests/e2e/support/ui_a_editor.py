"""Page objects of the graph editor for the UI-A suites (``/graphs/new`` and ``/graphs/<id>/edit``).

``EditorPage``   - the new-graph editor: name / tags / description, the pasted source, the chart,
                   stats, warnings, the save bar and the Style / Transform sections.
``EditGraphPage``- the same page for a saved graph (``open(graph_id)``).

All locators are ``data-testid`` ones (UI.md section 4.3). Waits follow the DOM signals of
``support.uiwait``: ``wait_preview`` after an edit, never a sleep. The entries table lives in
``ui_a_entries.EntriesPanel``, the source tabs in ``ui_a_sources.SourcePanel``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

from playwright.sync_api import expect

from tests.e2e.support.pages import AppPage
from tests.e2e.support.uiwait import DONUT_CHART, wait_chart, wait_editor, wait_idle, wait_preview

if TYPE_CHECKING:
    from playwright.sync_api import Locator

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

    def expect_ready(self) -> None:
        super().expect_ready()
        wait_editor(self.page)

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

    def open_section(self, section: Section) -> None:
        """Expand a collapsible section (``transform`` / ``style``) when it is collapsed."""
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
