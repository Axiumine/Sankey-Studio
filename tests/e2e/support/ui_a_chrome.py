"""Page objects of the editor chrome: graph menu, dialogs and the chart settings popover.

Dual mode. Today's editor has the name / description / tags fields and the Style and Export
sections inline. The editor with the chrome moves them: the fields into a dialog behind a gear
next to the title, Style and Export into a popover behind a gear in the chart header. Each helper
probes the DOM once with a ``locator.count()`` (call them after the editor is ready) and takes
the old path when the new element is absent, so a test written with them runs on both pages.

* ``GraphMenu``         - ``graph-settings-button`` / ``-menu`` / ``-details`` / ``-source``.
* ``DetailsDialog``     - ``details-dialog`` + ``details-done``; ``inline`` is true on the old page
                          (the fields are on the page; ``open``, ``done``, ``dismiss`` do nothing).
* ``ChangeSourceDialog``- ``change-source-dialog`` / ``-kind-<tab>`` / ``-keep`` / ``-apply``.
* ``ChartSettings``     - ``chart-settings-button`` / ``-panel`` / ``-tab-style`` / ``-tab-export``;
                          ``open`` does nothing on the old page (both panels are inline there).
* ``EditorChrome``      - what the two ``EditorPage`` classes delegate to: ``set_details``,
                          ``set_name``, ``expect_name``, ``expect_description``, ``expect_details``,
                          ``description_value``, ``open_style``, ``open_export``.

The chart settings popover is NOT modal and closes on a click or focus outside it: call
``open_export()`` / ``open_style()`` again before using its controls after touching the page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

    from tests.e2e.support.ui_a_sources import Tab

MenuItem = Literal["details", "source"]
SettingsTab = Literal["style", "export"]


class _Part:
    """The page and the ``data-testid`` lookup every chrome object needs."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def tid(self, testid: str) -> Locator:
        return self.page.get_by_test_id(testid)


class GraphMenu(_Part):
    """The gear next to the title with "Edit details" and "Change data source"."""

    @property
    def button(self) -> Locator:
        return self.tid("graph-settings-button")

    @property
    def panel(self) -> Locator:
        return self.tid("graph-settings-menu")

    def present(self) -> bool:
        """The page has the gear (false on the old page)."""
        return self.button.count() > 0

    def open(self) -> None:
        if self.button.get_attribute("aria-expanded") != "true":
            self.button.click()
        expect(self.button).to_have_attribute("aria-expanded", "true")
        expect(self.panel).to_be_visible()

    def choose(self, item: MenuItem) -> None:
        """Open the menu, pick the item and wait until the menu is closed again."""
        self.open()
        self.tid(f"graph-settings-{item}").click()
        expect(self.panel).to_be_hidden()


class DetailsDialog(_Part):
    """Name, description and tags: a dialog behind the gear, or the inline panel on the old page."""

    def __init__(self, page: Page) -> None:
        super().__init__(page)
        self.menu = GraphMenu(page)
        self.inline = not self.menu.present()

    @property
    def dialog(self) -> Locator:
        return self.tid("details-dialog")

    @property
    def name_field(self) -> Locator:
        return self.tid("editor-name")

    @property
    def description_field(self) -> Locator:
        return self.tid("editor-description")

    @property
    def tags_field(self) -> Locator:
        return self.tid("editor-tags")

    def open(self) -> DetailsDialog:
        if not self.inline:
            self.menu.choose("details")
            expect(self.dialog).to_be_visible()
        return self

    def fill(
        self, *, name: str | None = None, description: str | None = None, tags: tuple[str, ...] = ()
    ) -> None:
        if name is not None:
            self.name_field.fill(name)
        if description is not None:
            self.description_field.fill(description)
        for tag in tags:
            self.tags_field.fill(tag)
            self.tags_field.press("Enter")

    def expect_values(
        self, *, name: str | None = None, description: str | None = None, tags: tuple[str, ...] = ()
    ) -> None:
        if name is not None:
            expect(self.name_field).to_have_value(name)
        if description is not None:
            expect(self.description_field).to_have_value(description)
        for tag in tags:
            expect(self.page.get_by_text(tag, exact=True)).to_be_visible()

    def done(self) -> None:
        """Click Done (it validates the name) and wait until the dialog is gone."""
        if not self.inline:
            self.tid("details-done").click()
            expect(self.dialog).to_be_hidden()

    def dismiss(self) -> None:
        """Escape: closes without validating."""
        if not self.inline:
            self.page.keyboard.press("Escape")
            expect(self.dialog).to_be_hidden()


class ChangeSourceDialog(_Part):
    """The Change data source dialog: pick a kind, keep graph-only edits or not, apply."""

    @property
    def dialog(self) -> Locator:
        return self.tid("change-source-dialog")

    def open(self) -> ChangeSourceDialog:
        GraphMenu(self.page).choose("source")
        expect(self.dialog).to_be_visible()
        return self

    def pick(self, tab: Tab) -> None:
        self.tid(f"change-source-kind-{tab}").click()

    def keep_edits(self) -> None:
        self.tid("change-source-keep").check()

    def apply(self) -> None:
        self.tid("change-source-apply").click()
        expect(self.dialog).to_be_hidden()


class ChartSettings(_Part):
    """The gear in the chart header and its popover with the Style and Export tabs."""

    @property
    def button(self) -> Locator:
        return self.tid("chart-settings-button")

    @property
    def panel(self) -> Locator:
        return self.tid("chart-settings-panel")

    def present(self) -> bool:
        """The page has the gear (false on the old page, where Style and Export are inline)."""
        return self.button.count() > 0

    def open(self, tab: SettingsTab = "style") -> None:
        """Open the popover on ``tab``; a no-op on the old page."""
        if not self.present():
            return
        if self.button.get_attribute("aria-expanded") != "true":
            self.button.click()
        expect(self.panel).to_be_visible()
        selected = self.tid(f"chart-settings-tab-{tab}")
        if selected.get_attribute("aria-selected") != "true":
            selected.click()
        expect(selected).to_have_attribute("aria-selected", "true")

    def close(self) -> None:
        """Escape closes the popover and puts the focus back on the gear."""
        self.page.keyboard.press("Escape")
        expect(self.panel).to_be_hidden()
        expect(self.button).to_be_focused()


class EditorChrome(_Part):
    """The chrome helpers both ``EditorPage`` classes share (they delegate here)."""

    @property
    def settings(self) -> ChartSettings:
        return ChartSettings(self.page)

    def open_details(self) -> DetailsDialog:
        """Show the name / description / tags fields (the dialog when the page has one)."""
        return DetailsDialog(self.page).open()

    def set_details(
        self, *, name: str | None = None, description: str | None = None, tags: tuple[str, ...] = ()
    ) -> None:
        dialog = self.open_details()
        dialog.fill(name=name, description=description, tags=tags)
        if name is None:
            dialog.dismiss()  # Done refuses an empty name; the edits are already in the draft
        else:
            dialog.done()

    def expect_details(
        self, *, name: str | None = None, description: str | None = None, tags: tuple[str, ...] = ()
    ) -> None:
        dialog = self.open_details()
        dialog.expect_values(name=name, description=description, tags=tags)
        dialog.dismiss()

    def description_value(self) -> str:
        dialog = self.open_details()
        value = dialog.description_field.input_value()
        dialog.dismiss()
        return value

    def open_style(self) -> None:
        """Make the Style controls usable: the popover tab, or the collapsed section."""
        if self.settings.present():
            self.settings.open("style")
            return
        head = self.tid("section-style")
        if not head.evaluate("el => el.parentElement.open"):
            head.click()
            expect(head.locator("..")).to_have_attribute("open", "")

    def open_export(self) -> None:
        """Make the export buttons usable: the popover tab (nothing to do on the old page)."""
        self.settings.open("export")
