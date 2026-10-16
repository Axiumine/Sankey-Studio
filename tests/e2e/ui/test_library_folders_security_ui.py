# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.12, hostile collection names on every place the library shows them.

A collection name may hold markup, script text, a direction override and a control character (the
API accepts them like it does for graph names). Nothing of it may become an element, run, open a
dialog or break the layout; the names show as plain characters, a name with nothing left to see is
"Untitled collection", and the direction override and the bell never reach the screen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support import ui_b_hostile as hostile
from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.ui_b_common import PHONE, overflows_horizontally
from tests.e2e.support.ui_b_folders import FolderLibrary, seed_filed_graph, seed_folder

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

MARKUP = f'{hostile.IMG} "><b>x</b>'
BIDI = f"RLO {hostile.RLO}evil"
BELL = f"Bell{hostile.BELL} out"
UNTITLED = f"{hostile.RLO}{hostile.BELL}"
SHOWN = {
    MARKUP: MARKUP,
    hostile.SCRIPT_CLOSE: hostile.SCRIPT_CLOSE,
    BIDI: "RLO evil",
    BELL: "Bell out",
    UNTITLED: "Untitled collection",
}


@pytest.fixture
def library(page: WatchedPage, live_server: LiveServer) -> FolderLibrary:
    return FolderLibrary(page, live_server)


@pytest.fixture
def inert(page: WatchedPage) -> hostile.Inert:
    return hostile.Inert.watch(page)


def no_stray_characters(page: WatchedPage) -> None:
    text = page.inner_text("body")
    for character in (hostile.RLO, hostile.BELL):
        assert character not in text, f"U+{ord(character):04X} is visible"


def test_the_cards_show_hostile_names_as_plain_text(
    library: FolderLibrary, api: httpx.Client, inert: hostile.Inert
) -> None:
    for name in SHOWN:
        seed_folder(api, name)
    library.goto()
    expect(library.folder_cards).to_have_count(len(SHOWN))
    shown = library.folder_names.all_inner_texts()
    assert sorted(shown) == sorted(SHOWN.values())
    for link in library.folder_names.all():
        assert (link.get_attribute("href") or "").startswith("/?folder=")
    no_stray_characters(library.page)
    inert.check()


def test_the_path_and_the_search_chip_show_hostile_names_as_plain_text(
    library: FolderLibrary, api: httpx.Client, inert: hostile.Inert
) -> None:
    outer = seed_folder(api, MARKUP)
    inner = seed_folder(api, hostile.SCRIPT_CLOSE, outer["id"])
    name = unique_name("Needle")
    seed_filed_graph(api, name, inner["id"])
    library.goto(f"?folder={inner['id']}")
    expect(library.crumbs).to_have_text(["Library", MARKUP, hostile.SCRIPT_CLOSE])
    library.search(name)
    library.expect_names([name])
    chip = library.card(name).get_by_test_id("graph-folder")
    expect(chip).to_have_text(f"{MARKUP} / {hostile.SCRIPT_CLOSE}")
    no_stray_characters(library.page)
    inert.check()


def test_the_dialogs_and_toasts_show_hostile_names_as_plain_text(
    library: FolderLibrary, api: httpx.Client, inert: hostile.Inert
) -> None:
    seed_folder(api, MARKUP)
    seed_folder(api, BIDI)
    seed_graph(api, unique_name("Anchor"))
    library.goto()
    card = library.folder_card(MARKUP)
    card.get_by_test_id("folder-rename").click()
    expect(library.name_dialog).to_contain_text(f"Rename “{MARKUP}”")
    expect(library.tid("folder-name-input")).to_have_value(MARKUP)  # the field keeps what it holds
    library.page.keyboard.press("Escape")
    card.get_by_test_id("folder-move").click()
    expect(library.move_option("RLO evil")).to_be_visible()
    expect(library.move_option(MARKUP)).to_contain_text("inside the collection being moved")
    library.page.keyboard.press("Escape")
    card.get_by_test_id("folder-delete").click()
    dialog = library.tid("folder-delete-dialog")
    expect(dialog).to_contain_text(f"Delete the collection “{MARKUP}”?")
    library.tid("folder-delete-confirm").click()
    library.expect_toast(f"Deleted the collection “{MARKUP}”. Its contents moved up.", "success")
    expect(library.folder_card(MARKUP)).to_have_count(0)
    no_stray_characters(library.page)
    inert.check()


@pytest.mark.parametrize("viewport", [PHONE])
def test_long_hostile_names_do_not_break_the_phone_layout(
    library: FolderLibrary, api: httpx.Client, inert: hostile.Inert
) -> None:
    long_name = (MARKUP + " ") * 3
    outer = seed_folder(api, long_name[:100].strip())
    inner = seed_folder(api, long_name[:100].strip(), outer["id"])
    library.goto(f"?folder={inner['id']}")
    expect(library.breadcrumb).to_be_visible()
    assert not overflows_horizontally(library.page)
    library.tid("folder-new").click()
    expect(library.name_dialog).to_be_visible()
    assert not overflows_horizontally(library.page)
    inert.check()
