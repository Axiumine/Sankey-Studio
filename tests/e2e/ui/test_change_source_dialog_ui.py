# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""F10 part 1, D3: "Change data source" behind the gear next to the title.

The dialog lists the five kinds, preselects the current one and, for a different kind, swaps the
draft's source through the switcher the inline tabs use (so a pasted table survives a round trip),
then lands the person on the inline tab of the new kind. The same kind only goes to that tab.
Graph-only edits (here a category edit stored in the graph) are dropped unless the person keeps
them. Every test has a server of its own (the overlay cases save).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_a_chrome import ChangeSourceDialog
from tests.e2e.support.ui_a_editor import EditGraphPage, EditorPage
from tests.e2e.support.ui_a_sources import SourcePanel

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

CATEGORISED = graph_draft(
    BUDGET.csv,
    transform={"entry_categories": [{"source": "Budget", "target": "Rent", "category": "Fun"}]},
)


@pytest.fixture
def open_dialog(page: WatchedPage, live_server: LiveServer) -> ChangeSourceDialog:
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(BUDGET.csv)
    return ChangeSourceDialog(page).open()


def open_saved(
    page: WatchedPage, server: LiveServer, api: httpx.Client
) -> tuple[EditGraphPage, str]:
    saved = seed_graph(api, unique_name("Overlay"), CATEGORISED)
    editor = EditGraphPage(page, server)
    editor.open(saved["id"])
    return editor, saved["id"]


def stored_categories(api: httpx.Client, graph_id: str) -> list[dict[str, object]]:
    found = json_of(api.get(f"/api/v1/graphs/{graph_id}"))["transform"]["entry_categories"]
    return list(found)


# ------------------------------------------------------------------------------ the dialog


def test_the_dialog_lists_the_five_kinds_and_preselects_the_current_one(
    open_dialog: ChangeSourceDialog,
) -> None:
    dialog = open_dialog

    expect(dialog.dialog.get_by_role("radio")).to_have_count(5)
    expect(dialog.tid("change-source-kind-paste")).to_be_checked()
    expect(dialog.tid("change-source-kind-paste")).to_be_focused()
    expect(dialog.dialog.get_by_text("Paste (current)")).to_be_visible()
    expect(dialog.tid("change-source-apply")).to_have_text("Edit source settings")
    expect(dialog.tid("change-source-keep")).to_be_hidden()
    expect(dialog.tid("change-source-kind-mongo")).to_be_disabled()
    expect(dialog.dialog.get_by_text("No MongoDB connection is configured")).to_be_visible()
    dialog.pick("manual")
    expect(dialog.tid("change-source-apply")).to_have_text("Change source")


def test_a_new_kind_is_applied_and_the_focus_lands_on_its_inline_tab(
    page: WatchedPage, open_dialog: ChangeSourceDialog
) -> None:
    source = SourcePanel(page)
    open_dialog.pick("manual")

    open_dialog.apply()

    source.expect_only_tab("manual")
    expect(open_dialog.tid("source-tab-manual")).to_be_focused()


def test_pasted_text_survives_a_round_trip_through_the_dialog(
    page: WatchedPage, open_dialog: ChangeSourceDialog
) -> None:
    open_dialog.pick("manual")
    open_dialog.apply()
    expect(open_dialog.tid("source-content")).to_be_hidden()

    again = ChangeSourceDialog(page).open()
    expect(again.tid("change-source-kind-manual")).to_be_checked()
    again.pick("paste")
    again.apply()

    expect(again.tid("source-content")).to_have_value(BUDGET.csv)
    expect(again.tid("source-tab-paste")).to_be_focused()


def test_the_inline_tabs_and_the_dialog_share_one_cache(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = EditorPage(page, live_server)
    editor.goto()
    editor.paste(BUDGET.csv)
    SourcePanel(page).open_tab("manual")
    expect(page.get_by_test_id("source-content")).to_be_hidden()

    dialog = ChangeSourceDialog(page).open()
    dialog.pick("paste")
    dialog.apply()

    expect(dialog.tid("source-content")).to_have_value(BUDGET.csv)


def test_the_current_kind_only_takes_the_person_to_the_inline_tab(
    page: WatchedPage, open_dialog: ChangeSourceDialog
) -> None:
    page.evaluate("document.querySelector('[data-section=source]').open = false")

    open_dialog.apply()

    expect(open_dialog.dialog).to_be_hidden()
    expect(open_dialog.tid("source-tab-paste")).to_be_focused()
    expect(open_dialog.tid("source-content")).to_have_value(BUDGET.csv)
    assert page.evaluate("document.querySelector('[data-section=source]').open") is True


def test_choosing_upload_while_the_kind_is_text_selects_the_upload_tab(
    page: WatchedPage, open_dialog: ChangeSourceDialog
) -> None:
    open_dialog.pick("text")
    open_dialog.apply()
    expect(open_dialog.tid("source-tab-text")).to_have_attribute("aria-selected", "true")

    again = ChangeSourceDialog(page).open()
    again.pick("upload")
    expect(again.tid("change-source-apply")).to_have_text("Edit source settings")
    again.apply()

    expect(again.tid("source-tab-upload")).to_have_attribute("aria-selected", "true")
    expect(again.tid("source-tab-upload")).to_be_focused()


def test_cancel_and_the_x_change_nothing(
    page: WatchedPage, open_dialog: ChangeSourceDialog
) -> None:
    open_dialog.pick("manual")

    open_dialog.dialog.get_by_role("button", name="Cancel").click()
    expect(open_dialog.dialog).to_be_hidden()
    expect(open_dialog.tid("source-tab-paste")).to_have_attribute("aria-selected", "true")

    again = ChangeSourceDialog(page).open()
    again.pick("manual")
    again.tid("dialog-close").click()
    expect(again.dialog).to_be_hidden()
    expect(again.tid("source-content")).to_have_value(BUDGET.csv)


# ------------------------------------------------------------------------------ graph-only edits


def test_graph_only_edits_are_dropped_unless_they_are_kept(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, graph_id = open_saved(page, live_server, api)
    dialog = ChangeSourceDialog(page).open()

    dialog.pick("manual")
    expect(dialog.tid("change-source-keep")).to_be_visible()
    expect(dialog.dialog.get_by_text("drops 1 category edit unless you keep them")).to_be_visible()
    expect(dialog.tid("change-source-keep")).not_to_be_checked()
    dialog.apply()
    back = ChangeSourceDialog(page).open()
    expect(back.tid("change-source-keep")).to_be_hidden()  # nothing left to keep
    back.pick("paste")
    back.apply()
    editor.save()

    assert stored_categories(api, graph_id) == []


def test_ticking_keep_leaves_the_category_edit_in_the_graph(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    page.allow_http(422, "/api/v1/preview")  # a kept edit matches no row of an empty manual table
    editor, graph_id = open_saved(page, live_server, api)
    dialog = ChangeSourceDialog(page).open()
    dialog.pick("manual")
    dialog.keep_edits()
    dialog.apply()

    back = ChangeSourceDialog(page).open()
    back.pick("paste")
    back.keep_edits()
    back.apply()
    expect(back.tid("source-content")).to_have_value(BUDGET.csv)
    editor.save()

    assert [item["category"] for item in stored_categories(api, graph_id)] == ["Fun"]
