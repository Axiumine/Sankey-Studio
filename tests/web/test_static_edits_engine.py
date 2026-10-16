# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The edit engine (``editor/edits/engine.js``) run with node on the shipped files.

The engine talks to the real editor store; the API is a scripted fake and the toast a recorder, so
every branch of "where does this edit go" is a table row: pasted text and manual links (the server
rewrites the source), a file or collection (plan, consent, write), the graph-only fallback, the
refusals that must not fall back, Undo, the stored node order, the queue and the one-time hint.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.web.test_static_edits_local import ENGINE, run_driver

STALE = "The data changed while saving your edit. Nothing was changed. Try again."
ORDER_SAVED = (
    "Node order saved with this graph. Editing the data rows does not move the bars until "
    "you press Reset order."
)


NO_UNDO = "Undo is no longer possible: the graph changed after this edit."


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run_driver(tmp_path_factory.mktemp("edits-engine"), ENGINE)


def test_pasted_text_takes_the_new_source_and_drops_the_stale_override(
    result: dict[str, Any],
) -> None:
    flow = result["draftPath"]
    assert flow["result"] == {"ok": True, "where": "draft"}
    assert (flow["content"], flow["categories"], flow["dirty"]) == ("NEW", [], True)
    assert (flow["toasts"], flow["asked"]) == ([], [])
    assert flow["body"] == {"op": "set_category", "source": "a", "target": "b", "category": "Fun"}


def test_an_edit_whose_source_moved_meanwhile_changes_nothing(result: dict[str, Any]) -> None:
    flow = result["stale"]
    assert flow["result"] == {"ok": False, "stale": True, "message": STALE}
    assert flow["toasts"] == [["warning", STALE, None]]
    assert flow["source"] == {"type": "manual", "links": []}


def test_what_the_data_cannot_hold_stays_in_the_graph_and_the_notice_comes_once(
    result: dict[str, Any],
) -> None:
    flow = result["overlay"]
    assert (flow["ok"], flow["where"], flow["notice"]) == ([True, True], "graph", "Stays here.")
    assert flow["toasts"] == [["info", "Stays here.", None]]
    assert [item["category"] for item in flow["categories"]] == ["K", "L"]
    assert flow["paths"] == ["/edits/plan", "/entries", "/edits/plan", "/entries"]
    assert flow["validate"] == {"query": {"limit": 1}, "quiet": True}


def test_a_candidate_the_server_refuses_is_not_kept(result: dict[str, Any]) -> None:
    assert result["overlayRefused"] == {
        "result": {"ok": False, "message": "Cycle."},
        "categories": [],
        "toasts": [],
    }


def test_a_source_without_a_target_is_blocked_before_any_request(result: dict[str, Any]) -> None:
    assert result["blocked"] == [{"ok": False, "message": "Choose a file first."}, 0]


def test_accepting_stores_the_servers_key_and_writes(result: dict[str, Any]) -> None:
    flow = result["accept"]
    assert flow["result"] == {"ok": True, "where": "file", "written": True}
    assert flow["paths"] == ["/edits/plan", "/edits/write"]
    key = {"mode": "source", "target": "file:x.csv"}
    assert (flow["pref"], flow["sent"]) == (key, key)
    assert flow["asked"] == [["file:x.csv", "set_category", "x.csv"]]
    assert flow["toasts"] == [["success", "Updated 1 row in x.csv.", None]]
    assert flow["events"] == [["sankey:source-written", {"path": "x.csv"}]]
    assert result["acceptPins"]["category_column"] == 3


@pytest.mark.parametrize(
    ("name", "pref", "categories"),
    [
        ("decline", None, 1),
        ("never", {"mode": "graph", "target": "file:x.csv"}, 1),
        ("cancel", None, 0),
    ],
)
def test_the_other_answers_never_write(
    result: dict[str, Any], name: str, pref: object, categories: int
) -> None:
    flow = result[name]
    assert flow["sent"] == "no write"
    assert flow.get("pref") == pref
    assert len(flow["categories"]) == categories
    assert flow["toasts"] == []
    assert flow["result"] == (
        {"ok": False, "cancelled": True} if name == "cancel" else {"ok": True, "where": "graph"}
    )


def test_a_granted_target_writes_without_asking(result: dict[str, Any]) -> None:
    flow = result["granted"]
    assert (flow["asked"], flow["paths"]) == ([], ["/edits/plan", "/edits/write"])
    assert flow["toasts"] == [["success", "Updated 2 rows in x.csv.", None]]
    assert result["mongoWrite"] == [["success", "Added 1 document in main / db.t.", None]]


def test_a_refused_write_keeps_the_edit_and_a_failed_one_keeps_nothing(
    result: dict[str, Any],
) -> None:
    refused = result["writeRefused"]
    assert refused["result"] == {"ok": True, "where": "graph", "notice": "No row matches."}
    assert refused["toasts"] == [["info", "No row matches.", None]]
    assert [item["category"] for item in refused["categories"]] == ["Fun"]
    assert result["writeFails"] == {
        "result": {"ok": False, "message": "Could not write."},
        "categories": [],
        "toasts": [],
    }


def test_an_added_entry_in_manual_links_can_be_undone(result: dict[str, Any]) -> None:
    flow = result["addDraft"]
    assert (flow["ok"], flow["after"], flow["undone"], flow["action"]) == (True, 2, True, True)
    assert flow["toasts"] == [["success", "Entry added.", "Undo"]]
    assert flow["body"]["category"] is None


def test_an_added_entry_the_data_cannot_hold_becomes_an_extra_link(result: dict[str, Any]) -> None:
    flow = result["addOverlay"]
    assert flow["links"] == [{"source": "x", "target": "y", "value": 4, "category": "K"}]
    assert flow["undone"] is None
    assert flow["toasts"] == [["info", "Stays."], ["success", "Entry added."]]
    assert result["addCap"]["ok"] is False
    assert "2,000 added entries" in result["addCap"]["message"]


def test_an_undo_takes_back_only_its_own_edit_and_the_older_toast_goes_away(
    result: dict[str, Any],
) -> None:
    own = result["undoOwn"]
    # the Undo of the first entry refuses (the second one was added after it) and wipes nothing
    assert own["kept"] == ["x", "p"]
    assert own["left"] == 1
    assert own["dismissed"] == ["Entry added."]
    assert own["toasts"] == [
        ["success", "Entry added."],
        ["success", "Entry added."],
        ["info", NO_UNDO],
    ]
    # a category set in between is another part of the draft: it stays when the entry goes
    assert result["undoOther"] == {"links": None, "categories": ["Fun"]}


def test_two_drags_in_a_row_keep_one_undo_that_takes_back_the_second(
    result: dict[str, Any],
) -> None:
    drags = result["undoDrags"]
    assert drags["refused"] == ["a", "c", "b"]
    assert drags["restored"] == ["c", "b", "a"]
    assert (drags["dismissed"], drags["undos"]) == (1, 2)


def test_the_node_order_is_always_stored_and_rows_follow_when_they_can(
    result: dict[str, Any],
) -> None:
    assert result["reorderDraft"]["toasts"] == [["success", ORDER_SAVED, "Undo"]]
    assert result["reorderDraft"]["order"] == ["b", "a"]
    assert result["reorderUndo"] == {"links": 1}
    assert result["reorderMongo"] == {"order": ["b", "a"], "calls": 0}
    assert result["reorderFile"]["paths"] == ["/edits/plan", "/edits/write"]
    assert result["reorderFile"]["toasts"] == [ORDER_SAVED]
    assert result["reorderKept"] == ["Order kept in this graph only."]
    assert result["reorderDown"] == {
        "order": ["b", "a"],
        "toasts": ["Order kept in this graph only."],
    }
    assert result["reorderDownDraft"] == {"order": ["q"], "toasts": [ORDER_SAVED]}


def test_a_reorder_pins_the_colours_with_the_new_rows_and_undo_takes_both_back(
    result: dict[str, Any],
) -> None:
    flow = result["reorderPins"]
    assert flow["applied"] == {
        "colors": {"a": "#111111", "b": "#999999"},  # the colour the person set wins
        "categories": {"Red": "#222222"},
        "links": 1,
    }
    assert flow["toasts"] == [
        ["success", ORDER_SAVED],
        ["info", "3 colours were pinned so the chart keeps its colours."],
    ]
    assert flow["undone"] == {"colors": {"b": "#999999"}, "categories": None, "order": None}
    file_flow = result["reorderFilePins"]
    assert file_flow["colors"] == {"a": "#111111"}
    assert file_flow["source"] == "x.csv"
    assert file_flow["toasts"] == [
        ORDER_SAVED,
        "1 colour was pinned so the chart keeps its colours.",
    ]
    none = result["reorderNoPins"]
    assert (none["style"], none["toasts"]) == ({"node_order": ["b", "a"]}, ["success"])


def test_a_refused_row_reorder_says_why_once_and_reset_clears_the_order(
    result: dict[str, Any],
) -> None:
    assert result["reorderRecolour"] == {"order": ["a", "b"], "toasts": 1}
    assert result["reset"] == {"ok": True, "order": []}


def test_edits_run_one_after_another_and_the_hint_comes_once(result: dict[str, Any]) -> None:
    assert result["queue"] == ["start 1", "end 1", "start 2", "end 2"]
    assert result["hinted"] == ["1 other entry has no category."]
