# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""D1: the consent dialog and the per-graph preference for a managed FILE source.

A category typed for an entry of a graph that reads a file of the sources folder asks first
("Change your data too?"). Accepting writes the file and saves the SERVER's key with the graph;
"Keep in this graph" is remembered for the page session only; "don't ask again" is saved;
Cancel changes nothing; another file asks again; three quick commits raise one dialog; and the
status line of the Source panel can ask again. Every test has its own server (files change).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import json_of
from tests.e2e.support.ui_a_editor import EditGraphPage
from tests.e2e.support.ui_a_edits import (
    ConsentDialog,
    WriteBackStatus,
    commit_three_at_once,
    file_graph,
    write_file,
)
from tests.e2e.support.ui_a_entries import EntriesPanel

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

RENT = ("Budget", "Rent")
UTILITIES = ("Budget", "Utilities")
FOOD = ("Budget", "Food")
KEY = "file:budget.csv"


class Setup:
    """An editor on a graph that reads ``budget.csv``."""

    def __init__(self, page: WatchedPage, server: LiveServer, graph_id: str) -> None:
        self.server = server
        self.graph_id = graph_id
        self.editor = EditGraphPage(page, server)
        self.entries = EntriesPanel(page)
        self.consent = ConsentDialog(page)
        self.status = WriteBackStatus(page)
        self.editor.open(graph_id)

    def reload(self) -> None:
        self.editor.page.reload()
        self.editor.expect_ready()

    def file(self, name: str = "budget.csv") -> str:
        return (self.server.sources_dir / name).read_text()


@pytest.fixture
def setup(live_server: LiveServer, page: WatchedPage, api: httpx.Client) -> Setup:
    return Setup(page, live_server, file_graph(live_server, api, unique_name("Budget file")))


def stored_pref(api: httpx.Client, graph_id: str) -> object:
    return json_of(api.get(f"/api/v1/graphs/{graph_id}"))["source"].get("write_back")


def test_accepting_writes_the_file_and_saves_the_servers_key(
    setup: Setup, api: httpx.Client
) -> None:
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.expect_open()
    expect(setup.consent.dialog).to_contain_text("budget.csv")
    expect(setup.consent.dialog).to_contain_text("Row order in the file follows your drags.")

    setup.consent.accept()

    setup.consent.expect_gone()
    setup.editor.expect_toast("Updated 1 row in budget.csv.", "success")
    assert "Budget,Rent,1200,Housing" in setup.file().splitlines()
    expect(setup.entries.cell(*RENT)).to_have_value("Housing")
    setup.entries.set_category(*UTILITIES, "Housing")  # the saved answer: no second dialog
    setup.consent.expect_gone()
    expect(setup.editor.tid("category-row")).to_have_count(2)
    setup.editor.save()
    assert stored_pref(api, setup.graph_id) == {"mode": "source", "target": KEY}
    assert "Budget,Utilities,260,Housing" in setup.file().splitlines()


def test_keeping_the_edit_in_the_graph_is_remembered_for_this_page_only(setup: Setup) -> None:
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.expect_open()
    setup.consent.decline()

    setup.consent.expect_gone()
    expect(setup.entries.cell(*RENT)).to_have_value("Housing")
    assert "Housing" not in setup.file()
    setup.entries.set_category(*UTILITIES, "Housing")
    expect(setup.editor.tid("category-row")).to_have_count(2)
    setup.consent.expect_gone()

    setup.reload()
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.expect_open()
    setup.consent.cancel()


def test_never_is_saved_with_the_graph_and_the_file_stays_as_it_is(
    setup: Setup, api: httpx.Client
) -> None:
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.never()

    expect(setup.entries.cell(*RENT)).to_have_value("Housing")
    setup.editor.save()
    assert stored_pref(api, setup.graph_id) == {"mode": "graph", "target": KEY}
    setup.reload()
    setup.entries.set_category(*UTILITIES, "Housing")
    expect(setup.entries.cell(*UTILITIES)).to_have_value("Housing")
    expect(setup.editor.tid("category-row")).to_have_count(2)
    setup.consent.expect_gone()
    assert "Housing" not in setup.file()
    setup.status.expect_status("kept in this graph")


def test_cancel_and_escape_change_nothing_and_say_nothing(setup: Setup) -> None:
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.expect_open()
    setup.consent.cancel()

    expect(setup.entries.cell(*RENT)).to_have_value("")
    expect(setup.entries.error).to_have_count(0)
    assert "Housing" not in setup.file()
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.expect_open()
    setup.editor.page.keyboard.press("Escape")
    setup.consent.expect_gone()
    expect(setup.entries.cell(*RENT)).to_have_value("")
    expect(setup.editor.tid("category-row")).to_have_count(0)


def test_another_file_asks_again(setup: Setup) -> None:
    write_file(setup.server, "second.csv")
    setup.reload()  # the file list is read when the page opens
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.accept()
    setup.editor.expect_toast("Updated 1 row in budget.csv.", "success")

    setup.editor.page.get_by_test_id("source-file-select").select_option("second.csv")
    setup.editor.wait_preview()
    setup.status.expect_status("ask me each time")
    setup.entries.set_category(*FOOD, "Living")

    setup.consent.expect_open()
    expect(setup.consent.dialog).to_contain_text("second.csv")
    setup.consent.cancel()


def test_three_quick_commits_raise_one_dialog(setup: Setup) -> None:
    commit_three_at_once(setup.editor.page, ["Income", "Pay", "Housing"])

    setup.consent.expect_open()
    expect(setup.consent.dialog).to_have_count(1)
    setup.consent.accept()

    setup.consent.expect_gone()
    expect(setup.editor.tid("category-row")).to_have_count(4)  # three new + Uncategorized
    lines = setup.file().splitlines()
    assert lines[0] == "source,target,value,category"
    assert sorted(line.split(",")[3] for line in lines[1:] if line.count(",") == 3) == [
        "Housing",
        "Income",
        "Pay",
    ]


def test_the_status_line_can_ask_again(setup: Setup) -> None:
    setup.status.expect_status("ask me each time")
    expect(setup.status.reset).to_be_disabled()
    setup.entries.set_category(*RENT, "Housing")
    setup.consent.accept()
    setup.editor.expect_toast("Updated 1 row in budget.csv.", "success")
    setup.status.expect_status("written to the source")

    setup.status.reset.click()

    setup.status.expect_status("ask me each time")
    setup.entries.set_category(*UTILITIES, "Housing")
    setup.consent.expect_open()
    setup.consent.cancel()
