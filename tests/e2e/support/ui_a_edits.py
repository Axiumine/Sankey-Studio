# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Page objects and builders of the write-back flows (UI-A suites).

``ConsentDialog(page)`` - the "Change your data too?" dialog and its four answers.
``WriteBackStatus(page)`` - the status line of the Source panel (``source-write-back``) and its
"Ask me again" button.
``file_graph`` / ``mongo_graph`` - save a graph on a managed file or a mongomock collection and
return its id (the file is written into the server's sources folder).
``write_file`` - put a file into the sources folder of a server; ``commit_three_at_once`` - commit
three category cells in one tick (the "Enter, Enter, Enter" of a quick typist).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, graph_draft
from tests.e2e.support.clients import seed_graph

if TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from playwright.sync_api import Locator, Page

    from tests.e2e.support.server import LiveServer

MONGO_SOURCE: Final[dict[str, Any]] = {
    "type": "mongo",
    "connection": "main",
    "database": "flows",
    "collection": "transfers",
    "mode": "find",
    "source_field": "from",
    "target_field": "to",
    "value_field": "amount",
    "category_field": "kind",
}
_THREE_AT_ONCE = """(texts) => {
    const cells = Array.from(document.querySelectorAll('[data-testid=category-cell]'));
    texts.forEach((text, index) => {
        cells[index].value = text;
        cells[index].dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    });
}"""


class ConsentDialog:
    """The consent dialog of a write to a file or a collection."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def dialog(self) -> Locator:
        return self.page.get_by_test_id("write-back-dialog")

    def button(self, answer: str) -> Locator:
        return self.page.get_by_test_id(f"write-back-{answer}")

    def expect_open(self) -> None:
        expect(self.dialog).to_be_visible()
        expect(self.button("decline")).to_be_focused()

    def expect_gone(self) -> None:
        expect(self.dialog).to_have_count(0)

    def accept(self) -> None:
        self.button("accept").click()

    def decline(self) -> None:
        self.button("decline").click()

    def never(self) -> None:
        self.button("never").click()

    def cancel(self) -> None:
        self.button("cancel").click()


class WriteBackStatus:
    """The ``source-write-back`` line of the Source panel."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def line(self) -> Locator:
        return self.page.get_by_test_id("source-write-back")

    @property
    def reset(self) -> Locator:
        return self.line.get_by_role("button", name="Ask me again")

    def expect_status(self, text: str) -> None:
        expect(self.line).to_contain_text(f"Edits to the data: {text}")


def write_file(server: LiveServer, name: str, text: str = BUDGET.csv) -> Path:
    """Put ``text`` into the server's sources folder as ``name``."""
    path = server.sources_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def file_graph(
    server: LiveServer, api: httpx.Client, name: str, *, file: str = "budget.csv"
) -> str:
    """Save a graph that reads ``file`` (created with the budget csv) and return its id."""
    write_file(server, file)
    source = {"origin": "file", "path": file, "content": None}
    return str(seed_graph(api, name, graph_draft(source=source))["id"])


def mongo_graph(api: httpx.Client, name: str, **source: Any) -> str:
    """Save a graph on ``flows.transfers`` (mongomock) and return its id."""
    draft = graph_draft()
    draft["source"] = {**MONGO_SOURCE, **source}
    return str(seed_graph(api, name, draft)["id"])


def commit_three_at_once(page: Page, categories: list[str]) -> None:
    """Type ``categories`` into the first rows and press Enter in each, all in one tick."""
    page.evaluate(_THREE_AT_ONCE, categories)
