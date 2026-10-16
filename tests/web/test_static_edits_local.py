# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The pure parts of the edit engine, run with node on the shipped files (``editor/edits/``).

Covered here: the draft rewrites of ``local.js`` (override drop/set, added entries, snapshot and
restore), ``classify.js``, the page-session memory and the shared in-flight question of
``choices.js``, ``remote.js problemText``, the "N other entries have no category" hint, the store
helpers of ``touch.js``, and the engine itself (``test_static_edits_engine.py``) against the real
store with a scripted ``api``. The pages are checked in a real browser by the e2e suites.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from sankey_studio.web.app import STATIC_DIR

JS: Final = STATIC_DIR / "js"
HERE: Final = Path(__file__).parent
NODE: Final = shutil.which("node")
PRELUDE: Final = HERE / "static_edits_prelude.mjs"
PURE: Final = HERE / "static_edits_pure.mjs"
ENGINE: Final = HERE / "static_edits_engine.mjs"


def run_driver(path: Path, *chunks: Path) -> dict[str, Any]:
    """Run the prelude plus ``chunks`` (``.mjs`` files) with node; return the ``out`` they fill."""
    if NODE is None:
        pytest.skip("node is not installed")
    script = path / "run.mjs"
    body = "\n".join(chunk.read_text() for chunk in (PRELUDE, *chunks))
    script.write_text(body + "\nprocess.stdout.write(JSON.stringify(out));\n")
    done = subprocess.run(  # noqa: S603 - fixed argv: node on a temp script and the shipped files
        [NODE, str(script), str(JS)], capture_output=True, text=True, check=False, timeout=60
    )
    assert (done.returncode, done.stderr) == (0, "")
    data: dict[str, Any] = json.loads(done.stdout)
    return data


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run_driver(tmp_path_factory.mktemp("edits-pure"), PURE)


def test_classify_names_where_an_edit_goes(result: dict[str, Any]) -> None:
    kinds = [item["where"] for item in result["classify"]]
    assert kinds == ["draft", "draft", "draft", "blocked", "file", "blocked", "mongo", "blocked"]
    assert result["classify"][3]["message"] == "Choose a file first."
    assert result["classify"][5]["message"] == "Choose a collection first."


def test_an_override_is_dropped_set_or_left_alone(result: dict[str, Any]) -> None:
    override = result["override"]
    assert override["drop"] == [{"source": "c", "target": "d", "category": None}]
    assert override["dropMissing"] is True
    assert override["set"][0] == {"source": "a", "target": "b", "category": "Y"}
    assert override["setNew"] == {"source": "n", "target": "m", "category": None}
    assert override["none"] is True
    assert override["noList"] is True


def test_an_added_entry_is_appended_and_the_cap_is_a_sentence(result: dict[str, Any]) -> None:
    add = result["add"]
    assert add["links"] == [{"source": "x", "target": "y", "value": 4, "category": None}]
    assert (add["more"], add["problem"]) == (2, None)
    assert add["atCap"] == "This graph already holds 2,000 added entries, which is the limit."


def test_a_snapshot_puts_back_only_what_an_edit_touches(result: dict[str, Any]) -> None:
    snapshot = result["snapshot"]
    assert snapshot["snap"]["entry_categories"] == [1]
    assert snapshot["restored"] == {
        "source": {"s": 1},
        "transform": {"keep": 3, "entry_categories": [1], "extra_links": [2]},
        "style": {"other": 4, "node_order": ["a"]},
    }
    assert snapshot["bare"] == {"source": 0, "transform": {"x": 1}, "style": {}}
    assert snapshot["order"] == {"a": 1, "node_order": ["z"]}
    assert snapshot["pref"] == {"a": 1, "write_back": {"mode": "graph", "target": "k"}}


def test_pins_are_merged_without_overriding_a_colour_the_person_set(
    result: dict[str, Any],
) -> None:
    pins = result["pins"]
    assert pins["pinned"] == {
        "node_colors": {"a": "#111111", "b": "#999999"},
        "keep": 1,
        "category_colors": {"R": "#333333"},
    }
    assert pins["justCats"] == {"node_colors": {"b": 1}, "category_colors": {"R": "#333333"}}
    assert pins["noStyle"] == {"node_colors": {"a": "#111111"}}
    assert pins["none"] == [True, True, {}]
    assert pins["snap"] == [{"a": 1}, {"R": 2}]
    assert pins["restored"] == {"node_colors": {"a": 1}, "category_colors": {"R": 2}}
    assert pins["cleared"] == {}


def test_one_question_is_shared_per_key_and_the_answer_is_remembered(
    result: dict[str, Any],
) -> None:
    choices = result["choices"]
    assert (choices["same"], choices["started"]) == (True, 2)  # the third call starts a new one
    assert (choices["results"], choices["third"]) == (["accept", "accept"], "accept")
    assert (choices["before"], choices["after"], choices["other"]) == (True, False, False)


def test_a_failure_reads_as_one_sentence(result: dict[str, Any]) -> None:
    assert result["problem"] == [
        "The server did not accept that: must be greater than 0",
        "Nope",
        "Raw",
        "The change could not be checked.",
    ]


def test_the_hint_counts_the_other_entries_of_data_without_categories(
    result: dict[str, Any],
) -> None:
    assert result["hint"] == {"fresh": 2, "clear": 0, "has": 0, "partial": 0, "none": 0, "empty": 0}
    assert result["offer"] == [False, True, True]
    assert result["offerText"] == [
        ["1 other entry has no category.", "Show them"],
        ["3 other entries have no category.", "Show them"],
    ]


def test_touching_the_source_is_clean_and_the_written_event_names_the_file(
    result: dict[str, Any],
) -> None:
    assert result["touch"] == {"sameContent": True, "newObject": True, "dirty": False}
    assert result["events"] == [
        ["sankey:source-written", {"path": "a/b.csv"}],
        ["sankey:source-written", {"path": None}],
    ]
