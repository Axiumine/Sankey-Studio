"""F7: add an entry from the Entries card ("Add entry" opens the "Add a flow" dialog).

The dialog collects source, target, value and an optional category, checks them like the server
does, and hands the entry to the edit engine: it is appended to the pasted text or the manual links,
and a file or a collection asks first. It stays open on every refusal (a cycle, a bad value), shows
a non-blocking "New node" hint, works on an empty graph and keeps hostile names inert.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_a_editor import EditGraphPage, EditorPage
from tests.e2e.support.ui_a_entries import EntriesPanel
from tests.e2e.support.ui_a_manual import ManualTable

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

GIFTS = ("Budget", "Gifts")
LINKS = [
    {"source": "Salary", "target": "Budget", "value": 3000},
    {"source": "Budget", "target": "Rent", "value": 1200},
]
CATEGORY = "Category (optional)"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def manual_draft() -> dict[str, Any]:
    draft = graph_draft()
    draft["source"] = {"type": "manual", "links": LINKS}
    return draft


def open_graph(
    page: WatchedPage, server: LiveServer, api: httpx.Client, draft: dict[str, Any] | None = None
) -> tuple[EditGraphPage, EntriesPanel, str]:
    graph_id = str(seed_graph(api, unique_name("Add entry"), draft or graph_draft())["id"])
    editor = EditGraphPage(page, server)
    editor.open(graph_id)
    return editor, EntriesPanel(page), graph_id


def stored(api: httpx.Client, graph_id: str) -> dict[str, Any]:
    return dict(json_of(api.get(f"/api/v1/graphs/{graph_id}")))


def expect_counts(editor: EditorPage, nodes: int, links: int) -> None:
    """The stats strip says ``nodes`` and ``links`` (the first two numbers)."""
    values = editor.tid("stats").locator("dd")
    expect(values.nth(0)).to_have_text(str(nodes))
    expect(values.nth(1)).to_have_text(str(links))


def test_an_entry_added_to_manual_links_becomes_a_link_and_the_chart_follows(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, graph_id = open_graph(page, live_server, api, manual_draft())
    expect_counts(editor, 3, 2)

    entries.add_entry(*GIFTS, "50", "Fun")

    entries.add_dialog.expect_gone()
    editor.expect_toast("Entry added.", "success")
    expect(entries.cell(*GIFTS)).to_have_value("Fun")
    table = ManualTable(page)
    expect(table.rows).to_have_count(3)
    expect(table.cell(CATEGORY, 3)).to_have_value("Fun")
    expect_counts(editor, 4, 3)
    expect(entries.add_button).to_be_focused()
    editor.save()
    assert stored(api, graph_id)["source"]["links"][-1] == {
        "source": "Budget",
        "target": "Gifts",
        "value": 50,
        "category": "Fun",
    }


def test_undo_takes_an_added_entry_back(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, _ = open_graph(page, live_server, api, manual_draft())
    entries.add_entry(*GIFTS, "50")
    toast = editor.expect_toast("Entry added.")

    toast.get_by_role("button", name="Undo").click()

    expect(entries.row(*GIFTS)).to_have_count(0)
    expect(ManualTable(page).rows).to_have_count(2)


def test_a_second_added_entry_keeps_one_undo_that_takes_back_only_that_entry(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, _ = open_graph(page, live_server, api, manual_draft())
    entries.add_entry(*GIFTS, "50")
    editor.expect_toast("Entry added.")
    entries.add_entry("Budget", "Fun", "20")

    toasts = editor.tid("toast").filter(has_text="Entry added.")
    expect(toasts).to_have_count(1)
    toasts.get_by_role("button", name="Undo").click()

    expect(entries.row("Budget", "Fun")).to_have_count(0)
    expect(entries.row(*GIFTS)).to_have_count(1)
    expect(ManualTable(page).rows).to_have_count(3)


def test_an_entry_added_to_pasted_text_is_a_new_line_of_the_text(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, _ = open_graph(page, live_server, api)

    entries.add_entry(*GIFTS, "50")

    entries.add_dialog.expect_gone()
    expect(entries.row(*GIFTS)).to_have_count(1)
    expect(editor.content).to_have_value(re.compile(r"^Budget,Gifts,50$", re.MULTILINE))
    expect_counts(editor, 11, 10)
    assert BUDGET.csv.splitlines()[1] in editor.content.input_value()


def test_an_empty_graph_gets_its_first_entry(page: WatchedPage, live_server: LiveServer) -> None:
    editor = EditorPage(page, live_server)
    editor.goto()
    entries = EntriesPanel(page)
    expect(entries.add_button).to_be_enabled()

    entries.add_entry("Salary", "Budget", "3000")

    entries.add_dialog.expect_gone()
    expect(entries.row("Salary", "Budget")).to_have_count(1)
    expect(editor.content).to_have_value(re.compile(r"Salary,Budget,3000"))
    editor.wait_preview()
    expect_counts(editor, 2, 1)


def test_a_cycle_is_refused_in_the_dialog_and_nothing_changes(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, _ = open_graph(page, live_server, api, manual_draft())
    page.allow_http(422, "/api/v1/edits/plan")  # the refusal is the point of this test

    entries.add_entry("Rent", "Salary", "5")

    dialog = entries.add_dialog
    dialog.expect_open()
    expect(dialog.error).to_be_visible()
    expect(dialog.error).to_contain_text("loop")
    expect(ManualTable(page).rows).to_have_count(2)
    expect(editor.tid("toast").filter(has_text="Entry added.")).to_have_count(0)
    dialog.field("source").fill("Rent")
    dialog.field("target").fill("Gifts")
    expect(dialog.error).to_be_hidden()
    dialog.submit.click()
    dialog.expect_gone()
    expect(entries.row("Rent", "Gifts")).to_have_count(1)


class Problem(NamedTuple):
    """Four typed fields, the field that is named, and a part of the message."""

    fields: tuple[str, str, str, str]
    field: str
    message: str


PROBLEMS = [
    Problem(("", "B", "5", ""), "source", "Enter the source"),
    Problem(("A", " ", "5", ""), "target", "Enter the target"),
    Problem(("A", "A", "5", ""), "target", "must be different"),
    Problem(("A", "B", "", ""), "value", "Enter a value above 0"),
    Problem(("A", "B", "0", ""), "value", "Enter a value above 0"),
    Problem(("A", "B", "-2", ""), "value", "Enter a value above 0"),
    Problem(("A", "B", "1,5", ""), "value", "Enter a value above 0"),
    Problem(("A", "B", "5", "Other"), "category", "reserved"),
]


@pytest.mark.parametrize("problem", PROBLEMS, ids=lambda problem: problem.message + problem.field)
def test_a_bad_field_is_named_and_focused_and_nothing_is_sent(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client, problem: Problem
) -> None:
    editor, entries, _ = open_graph(page, live_server, api, manual_draft())

    entries.add_entry(*problem.fields)

    dialog = entries.add_dialog
    expect(dialog.error).to_contain_text(problem.message)
    expect(dialog.field(problem.field)).to_be_focused()
    expect(dialog.field(problem.field)).to_have_attribute("aria-invalid", "true")
    expect(ManualTable(page).rows).to_have_count(2)
    expect(editor.tid("toast")).to_have_count(0)


def test_typing_clears_the_message_and_a_corrected_entry_is_added(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, entries, _ = open_graph(page, live_server, api, manual_draft())
    entries.add_entry("A", "B", "0")
    dialog = entries.add_dialog
    expect(dialog.error).to_be_visible()

    dialog.field("value").fill("7")

    expect(dialog.error).to_be_hidden()
    expect(dialog.field("value")).not_to_have_attribute("aria-invalid", "true")
    dialog.submit.click()
    dialog.expect_gone()
    expect(entries.row("A", "B")).to_have_count(1)


def test_a_new_node_is_announced_and_a_known_one_is_not(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, entries, _ = open_graph(page, live_server, api, manual_draft())
    entries.add_button.click()
    dialog = entries.add_dialog
    expect(dialog.hint("source")).to_be_empty()

    dialog.field("source").fill("Budget")
    dialog.field("target").fill("Gifts")

    expect(dialog.hint("source")).to_be_empty()
    expect(dialog.hint("target")).to_have_text("New node: Gifts will be created.")
    dialog.field("target").fill("Rent")
    expect(dialog.hint("target")).to_be_empty()
    dialog.field("source").fill("  Zed ")
    expect(dialog.hint("source")).to_have_text("New node: Zed will be created.")


def test_the_button_is_disabled_with_a_reason_until_a_file_is_chosen(
    page: WatchedPage, live_server: LiveServer
) -> None:
    editor = EditorPage(page, live_server)
    editor.goto()
    entries = EntriesPanel(page)
    editor.open_section("source")
    editor.tid("source-tab-text").click()

    expect(entries.add_button).to_be_disabled()
    expect(entries.add_button).to_have_attribute("title", "Choose a file first.")
    editor.tid("source-tab-paste").click()
    expect(entries.add_button).to_be_enabled()
    expect(entries.add_button).not_to_have_attribute("title", re.compile(".+"))


def test_the_keyboard_opens_fills_and_adds_and_escape_cancels(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, entries, _ = open_graph(page, live_server, api, manual_draft())
    dialog = entries.add_dialog
    entries.add_button.focus()

    page.keyboard.press("Enter")
    dialog.expect_open()
    expect(dialog.field("source")).to_be_focused()
    page.keyboard.press("Escape")
    dialog.expect_gone()
    expect(entries.add_button).to_be_focused()
    expect(ManualTable(page).rows).to_have_count(2)

    page.keyboard.press("Enter")
    for text in ("Budget", "Cards", "20"):
        page.keyboard.type(text)
        page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Enter")
    dialog.expect_gone()
    expect(entries.row("Budget", "Cards")).to_have_count(1)


def test_tab_and_shift_tab_cycle_inside_the_dialog(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    _, entries, _ = open_graph(page, live_server, api, manual_draft())
    entries.add_button.click()
    dialog = entries.add_dialog
    expect(dialog.field("source")).to_be_focused()

    page.keyboard.press("Shift+Tab")
    expect(dialog.submit).to_be_focused()
    page.keyboard.press("Tab")
    expect(dialog.field("source")).to_be_focused()
    dialog.cancel.click()
    dialog.expect_gone()
    expect(entries.add_button).to_be_focused()


HOSTILE_SOURCE = '<img src=x onerror="window.pwned = 1">'
HOSTILE_TARGET = '"><script>window.pwned = 2</script>'


def test_hostile_names_stay_text_everywhere(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, _ = open_graph(page, live_server, api, manual_draft())
    entries.add_button.click()
    dialog = entries.add_dialog

    dialog.fill(HOSTILE_SOURCE, HOSTILE_TARGET, "5", "<b>x</b>")

    expect(dialog.hint("source")).to_have_text(f"New node: {HOSTILE_SOURCE} will be created.")
    dialog.submit.click()
    dialog.expect_gone()
    editor.expect_toast("Entry added.", "success")
    expect(entries.row(HOSTILE_SOURCE, HOSTILE_TARGET)).to_have_count(1)
    expect(entries.cell(HOSTILE_SOURCE, HOSTILE_TARGET)).to_have_value("<b>x</b>")
    assert page.evaluate("window.pwned") is None
    injected = "img[src='x'], script:not([src]):not([type='application/json'])"
    assert page.locator(injected).evaluate_all("els => els.length") == 0
