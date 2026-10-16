# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""B3, part 3: the entries table pages through every link (100 rows a page, server paged).

250 links are three pages (100, 100 and 50: a count that is not a multiple of the page size, so a
pager that rounds the wrong way loses the last page). The buttons, the "Page N of M" and "Rows
a-b of n" lines, the rows of each page, the focus that follows the click and the way a search
brings the table back to page one are what a person sees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import many_links
from tests.e2e.support.ui_a_editor import EditorPage
from tests.e2e.support.ui_a_entries import EntriesPanel

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

LINKS: Final = 250
PAGE_ROWS: Final = ((1, 100, LINKS), (101, 200, LINKS), (201, 250, LINKS))


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def editor(page: WatchedPage, live_server: LiveServer) -> EditorPage:
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(many_links(LINKS).csv)
    return editor


@pytest.fixture
def entries(editor: EditorPage) -> EntriesPanel:
    return EntriesPanel(editor.page)


def test_next_and_previous_walk_through_all_the_pages_and_stop_at_both_ends(
    editor: EditorPage, entries: EntriesPanel
) -> None:
    expect(editor.tid("entries-total")).to_have_text("250 entries")
    entries.expect_page(1, 3, PAGE_ROWS[0])
    expect(entries.previous_page).to_be_disabled()
    expect(entries.next_page).to_be_enabled()
    pages = [entries.pairs()]

    entries.next_page.click()
    entries.expect_page(2, 3, PAGE_ROWS[1])
    expect(entries.previous_page).to_be_enabled()
    expect(entries.next_page).to_be_enabled()
    expect(entries.next_page).to_be_focused()
    pages.append(entries.pairs())

    entries.next_page.click()
    entries.expect_page(3, 3, PAGE_ROWS[2])
    expect(entries.next_page).to_be_disabled()
    expect(entries.previous_page).to_be_focused()  # the button that was used is gone: the other
    pages.append(entries.pairs())

    seen = [pair for page in pages for pair in page]
    assert len(seen) == LINKS
    assert len(set(seen)) == LINKS  # every link on exactly one page

    entries.previous_page.click()
    entries.expect_page(2, 3, PAGE_ROWS[1])
    assert entries.pairs() == pages[1]
    entries.previous_page.click()
    entries.expect_page(1, 3, PAGE_ROWS[0])
    expect(entries.previous_page).to_be_disabled()
    expect(entries.next_page).to_be_focused()
    assert entries.pairs() == pages[0]


def test_a_search_returns_to_page_one_and_clearing_it_brings_all_the_pages_back(
    editor: EditorPage, entries: EntriesPanel
) -> None:
    entries.next_page.click()
    entries.next_page.click()
    entries.expect_page(3, 3, PAGE_ROWS[2])

    entries.search("S001")  # one source with 15 targets: a single page
    entries.expect_page(1, 1, (1, 15, 15))
    expect(entries.previous_page).to_be_disabled()
    expect(entries.next_page).to_be_disabled()
    assert set(entries.pairs()) == {f"S001>T{number:03d}" for number in range(15)}

    entries.search("")
    entries.expect_page(1, 3, PAGE_ROWS[0])
    expect(editor.tid("entries-total")).to_have_text("250 entries")
