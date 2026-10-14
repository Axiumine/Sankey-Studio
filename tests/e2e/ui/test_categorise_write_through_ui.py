"""F6: a category edit is written into the data of pasted text and manual links (write-through).

The Paste box and the Manual table hold the category afterwards, a stale per-entry override of the
graph is dropped (or kept when it still matters), a cleared category leaves the data, JSON text
says once that it was re-formatted, and a manual pair whose nodes were merged is found through the
merge (the old browser rule matched raw names and updated nothing).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_a_editor import EditGraphPage
from tests.e2e.support.ui_a_entries import EntriesPanel
from tests.e2e.support.ui_a_manual import ManualTable

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

RENT = ("Budget", "Rent")
OLD = {"source": "Budget", "target": "Rent", "category": "Old"}
JSON_TEXT = json.dumps(
    [{"source": "a", "target": "b", "value": 5}, {"source": "b", "target": "c", "value": 2}]
)
CATEGORY_COLUMN = "Category (optional)"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def open_graph(
    page: WatchedPage, server: LiveServer, api: httpx.Client, draft: dict[str, object]
) -> tuple[EditGraphPage, EntriesPanel, str]:
    graph_id = str(seed_graph(api, unique_name("Write through"), draft)["id"])
    editor = EditGraphPage(page, server)
    editor.open(graph_id)
    return editor, EntriesPanel(page), graph_id


def stored(api: httpx.Client, graph_id: str) -> dict[str, Any]:
    return dict(json_of(api.get(f"/api/v1/graphs/{graph_id}")))


def test_a_stale_override_of_the_pair_is_dropped_once_the_data_holds_the_name(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(BUDGET.csv, transform={"entry_categories": [OLD]})
    editor, entries, graph_id = open_graph(page, live_server, api, draft)
    expect(entries.cell(*RENT)).to_have_value("Old")

    entries.set_category(*RENT, "New")

    expect(entries.cell(*RENT)).to_have_value("New")
    expect(editor.content).to_have_value(re.compile(r"^Budget,Rent,1200,New$", re.MULTILINE))
    editor.save()
    transform = stored(api, graph_id)["transform"]
    assert transform["entry_categories"] == []


def test_the_override_stays_when_rules_outrank_the_data(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    rule = {"match": "either", "pattern": "*Rent*", "category": "Rule"}
    draft = graph_draft(BUDGET.csv, transform={"category_rules": [rule], "rules_override": True})
    editor, entries, graph_id = open_graph(page, live_server, api, draft)
    expect(entries.cell(*RENT)).to_have_value("Rule")

    entries.set_category(*RENT, "New")

    expect(entries.cell(*RENT)).to_have_value("New")
    editor.save()
    kept = stored(api, graph_id)["transform"]["entry_categories"]
    assert [(item["source"], item["target"], item["category"]) for item in kept] == [
        ("Budget", "Rent", "New")
    ]


def test_clearing_a_category_removes_it_from_the_data(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    editor, entries, graph_id = open_graph(
        page, live_server, api, graph_draft(BUDGET_CATEGORISED.csv)
    )
    expect(entries.cell(*RENT)).to_have_value("Housing")

    entries.clear_category(*RENT)

    expect(entries.cell(*RENT)).to_have_value("")
    expect(editor.content).not_to_have_value(re.compile("Budget,Rent,1200,Housing"))
    editor.save()
    content = str(stored(api, graph_id)["source"]["content"])
    assert "Budget,Rent,1200," in content.splitlines()
    assert stored(api, graph_id)["transform"]["entry_categories"] == []


def test_json_text_is_reformatted_and_says_so_once(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    draft = graph_draft(JSON_TEXT, source={"format": "json"})
    editor, entries, _ = open_graph(page, live_server, api, draft)

    entries.set_category("a", "b", "Fun")
    editor.expect_toast("Your JSON text was re-formatted.", "info")
    entries.set_category("b", "c", "Fun")

    expect(entries.cell("a", "b")).to_have_value("Fun")
    expect(entries.cell("b", "c")).to_have_value("Fun")
    expect(editor.toasts().filter(has_text="re-formatted")).to_have_count(1)
    assert json.loads(editor.content.input_value())[0]["category"] == "Fun"


def test_a_manual_pair_with_merged_nodes_is_found_through_the_merge(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    links = [
        {"source": "A1", "target": "b", "value": 1},
        {"source": "A2", "target": "b", "value": 2},
        {"source": "x", "target": "b", "value": 3},
    ]
    draft = graph_draft(transform={"merge_nodes": {"A1": "A", "A2": "A"}})
    draft["source"] = {"type": "manual", "links": links}
    editor, entries, _ = open_graph(page, live_server, api, draft)

    entries.set_category("A", "b", "Fun")

    expect(entries.cell("A", "b")).to_have_value("Fun")
    table = ManualTable(page)
    expect(table.cell(CATEGORY_COLUMN, 1)).to_have_value("Fun")
    expect(table.cell(CATEGORY_COLUMN, 2)).to_have_value("Fun")
    expect(table.cell(CATEGORY_COLUMN, 3)).to_have_value("")
    editor.wait_preview()
    expect(editor.tid("category-row").locator("th")).to_have_text(["Fun", "Uncategorized"])
