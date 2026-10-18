# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Page object of the source tabs of the editor, except Manual and MongoDB (UI-A suites).

``SourcePanel(page)`` knows the tab strip (Text file, Paste, Upload, Manual, MongoDB), the upload
control and its status line, the files table, and the column mapping block (the four column
selects, the header checkbox and the "no category column" switch), and the Clear icon of the
Paste box with its "Cleared" toast (Undo).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from playwright.sync_api import expect

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.sync_api import Locator, Page

Tab = Literal["text", "paste", "upload", "manual", "mongo"]
Role = Literal["source", "target", "value", "category"]
#: What is visible on each tab and on no other (docs/ui/editor.md).
TAB_MARKERS: Final[dict[Tab, str]] = {
    "text": "source-file-select",
    "paste": "source-content",
    "upload": "source-upload-input",
    "manual": "manual-table",
    "mongo": "mongo-no-connections",
}


class SourcePanel:
    """The "Data source" section of the editor."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def tid(self, testid: str) -> Locator:
        return self.page.get_by_test_id(testid)

    # ------------------------------------------------------------------ tabs

    def open_tab(self, tab: Tab) -> None:
        button = self.tid(f"source-tab-{tab}")
        button.click()
        expect(button).to_have_attribute("aria-selected", "true")

    def expect_only_tab(self, tab: Tab) -> None:
        """``tab`` is the selected one: its marker shows and the markers of the others do not."""
        for other, marker in TAB_MARKERS.items():
            expect(self.tid(f"source-tab-{other}")).to_have_attribute(
                "aria-selected", "true" if other == tab else "false"
            )
            if other == tab:
                expect(self.tid(marker)).to_be_visible()
            else:
                expect(self.tid(marker)).to_be_hidden()
        if tab == "upload":
            panel = self.page.get_by_role("tabpanel", name="Upload")
            expect(panel.get_by_text("Choose a file", exact=True)).to_be_visible()

    # ------------------------------------------------------------------ paste box

    @property
    def clear_button(self) -> Locator:
        """The Clear icon inside the Paste box (visible only while the box holds text)."""
        return self.tid("source-clear")

    def clear(self) -> None:
        self.clear_button.click()

    @property
    def cleared_toast(self) -> Locator:
        """The "Cleared" toast that offers Undo."""
        return self.tid("toast").filter(has_text="Cleared")

    def undo_clear(self) -> None:
        self.cleared_toast.get_by_role("button", name="Undo").click()

    # ------------------------------------------------------------------ upload

    @property
    def upload_status(self) -> Locator:
        return self.page.locator("#main .ed-upload-status")

    @property
    def files_table(self) -> Locator:
        return self.page.get_by_role("table", name="Files in the sources folder")

    def upload(self, path: Path) -> None:
        """Hand a local file to the hidden file input of the Upload tab."""
        self.tid("source-upload-input").set_input_files(str(path))

    def expect_uploaded(self, name: str) -> None:
        expect(self.upload_status).to_have_text(f"{name} was uploaded and is now the source.")

    def file_row(self, name: str) -> Locator:
        return self.files_table.get_by_role("row").filter(has_text=name)

    # ------------------------------------------------------------------ mapping

    def column(self, role: Role) -> Locator:
        return self.tid(f"source-column-{role}")

    def pick_column(self, role: Role, value: str) -> None:
        self.column(role).select_option(value)

    def expect_columns(self, **expected: str) -> None:
        """Each role's select has this option VALUE (``""`` is "Automatic" / "Auto (...)")."""
        for role, value in expected.items():
            expect(self.tid(f"source-column-{role}")).to_have_value(value)

    def expect_options(self, role: Role, labels: list[str]) -> None:
        """The select of ``role`` offers exactly these option labels, in order (retries)."""
        expect(self.column(role).locator("option")).to_have_text(labels)
