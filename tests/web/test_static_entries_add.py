"""The pure parts of the Entries card additions, run with node on the shipped files.

Covered: the rules of the "Add a flow" dialog (``entries/add-form.js``: names, value, category,
the "New node" hint), the "category edits no longer match" notice (``stale-overrides.js``), the list
of graph-only edits and the removal of one item (``overlay-list.js``) and ``applyBulk`` of
``bulk.js`` (moved out of ``panel.js``). The pages are checked in a real browser by
``tests/e2e/ui/test_entries_add_ui.py`` and ``test_entries_overlays_ui.py``.
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
NODE: Final = shutil.which("node")
DRIVER: Final = Path(__file__).parent / "static_entries_add.mjs"
VALUE_MESSAGE: Final = "Enter a value above 0, for example 1200 or 12.5."


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(  # noqa: S603 - fixed argv: node on the repo's own driver and files
        [NODE, str(DRIVER), str(JS)], capture_output=True, text=True, check=False, timeout=60
    )
    assert (done.returncode, done.stderr) == (0, "")
    data: dict[str, Any] = json.loads(done.stdout)
    return data


def entry(category: str | None = None) -> dict[str, Any]:
    return {"source": "Budget", "target": "Gifts", "value": 50, "category": category}


def problem(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def test_a_valid_entry_is_trimmed_and_takes_the_category_spelling_in_use(
    result: dict[str, Any],
) -> None:
    checked = result["entry"]
    assert checked["plain"] == entry()
    assert checked["category"] == entry("fun")
    assert checked["spelling"] == entry("Housing")
    assert checked["max"] is True


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (
            "reserved",
            problem(
                "category",
                '"Other" is reserved for the chart (it labels the leftovers). Pick another name.',
            ),
        ),
        ("longCategory", problem("category", "Category names can have at most 100 characters.")),
        ("noSource", problem("source", "Enter the source: where the flow starts.")),
        ("noTarget", problem("target", "Enter the target: where the flow ends.")),
        ("same", problem("target", "The source and the target must be different nodes.")),
        ("over", problem("source", "Names can have at most 200 characters.")),
        ("control", problem("target", "The target name contains characters that cannot be used.")),
        ("lone", problem("target", "The target name contains characters that cannot be used.")),
    ],
)
def test_each_rule_names_the_field_and_says_what_to_do(
    result: dict[str, Any], case: str, expected: dict[str, str]
) -> None:
    assert result["entry"][case] == expected


@pytest.mark.parametrize(
    ("text", "value"),
    [("12.5", 12.5), (" 1 200 ", 1200), ("0.001", 0.001), ("+3", 3), ("1e3", 1000)],
)
def test_a_value_above_zero_is_taken(result: dict[str, Any], text: str, value: float) -> None:
    assert result["values"][text] == {**entry(), "value": value}


@pytest.mark.parametrize("text", ["", "0", "-1", "abc", "1,5", "1e999", "NaN", "missing"])
def test_anything_else_is_a_value_problem(result: dict[str, Any], text: str) -> None:
    assert result["values"][text] == problem("value", VALUE_MESSAGE)


def test_the_new_node_hint_speaks_only_for_a_name_the_graph_lacks(result: dict[str, Any]) -> None:
    hints = result["hints"]
    assert hints["names"] == ["Budget", "Rent"]
    assert (hints["empty"], hints["none"]) == (0, 0)
    assert hints["unknown"] == "New node: Gifts will be created."
    assert hints["caseMatters"] == "New node: budget will be created."
    assert hints["bidi"] == "New node: AB will be created."
    assert [hints[key] for key in ("known", "blank", "nothingKnown")] == ["", "", ""]
    assert result["limits"] == [200, 1000]


def test_the_unmatched_notice_sums_the_server_warnings(result: dict[str, Any]) -> None:
    unmatched = result["unmatched"]
    counts = [
        unmatched[key] for key in ("none", "notArray", "one", "sum", "loose", "undefinedList")
    ]
    assert counts == [0, 0, 1, 5, 0, 0]
    assert unmatched["textOne"] == (
        "1 of your category edits no longer matches an entry (the name changed). "
        "It is ignored and listed under Graph-only edits."
    )
    assert unmatched["textMany"] == (
        "3 of your category edits no longer match an entry (the names changed). "
        "They are ignored and listed under Graph-only edits."
    )


def test_every_graph_only_edit_is_one_item_and_a_node_order_is_one(
    result: dict[str, Any],
) -> None:
    items = result["items"]
    assert items["texts"] == [
        "A to B: no category",
        "A to B: category X",
        "A to B: 12, category Fun",
        "C to D: 5",
        "Custom node order (3 nodes)",
    ]
    assert items["kinds"][0] == "draft.transform.entry_categories"
    assert items["kinds"][2:] == ["draft.transform.extra_links"] * 2 + ["draft.style.node_order"]
    assert items["count"] == 5
    assert result["empty"] == {"items": 0, "count": 0, "one": "Custom node order (1 node)"}
    assert (result["many"], result["listedMax"]) == (300, 200)
    assert result["hostile"] == "<b>x</b> to y: 1"


def test_removing_an_item_changes_only_that_item(result: dict[str, Any]) -> None:
    removed = result["remove"]
    assert removed["category"] == [{"source": "A", "target": "B", "category": "X"}]
    assert removed["untouched"] is True
    assert removed["link"] == [{"source": "C", "target": "D", "value": 5, "category": None}]
    assert removed["order"] == []
    assert removed["original"] == 2
    assert removed["noSection"] == {"source": 1, "transform": {"extra_links": []}}


def test_apply_bulk_adds_one_rule_and_offers_undo(result: dict[str, Any]) -> None:
    bulk = result["bulk"]
    assert bulk["ok"] == [
        "busy:true",
        "rule:rent:Home",
        "busy:false",
        "clear",
        "name:Home",
        'toast:Rule added: names containing "rent" get "Home". You can edit it under Transform.',
        "Undo",
        "undo:Home",
    ]
    assert bulk["noToast"] == ["busy:true", "rule:rent:Home", "busy:false", "clear", "name:Home"]


def test_apply_bulk_refuses_a_second_press_a_useless_rule_and_a_failed_rule(
    result: dict[str, Any],
) -> None:
    bulk = result["bulk"]
    assert bulk["busy"] == []
    sentence = (
        'No source or target name contains "rent" (the search also looks at categories), '
        "so a rule would do nothing."
    )
    assert bulk["problem"] == [f"error:{sentence}"]
    assert bulk["failed"] == ["busy:true", "busy:false", "error:nope", "focus"]
