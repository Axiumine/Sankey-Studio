"""``plan_edit`` for the data that lives in the draft: pasted text and manual links.

No consent, no operator gate: ``plan`` rewrites the data and answers the whole new source.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.edits import plan_edit
from sankey_studio.edits.reasons import NOTICES, REFORMATTED_NOTICE
from sankey_studio.errors import GraphBuildError, SourceEditRefused
from sankey_studio.models import EditOutcome, Link, ManualSource, StylePins, TextSource
from sankey_studio.models.base import MAX_COLOR_OVERRIDES
from tests.test_edits_support import (
    ADD,
    CATEGORISE,
    CSV,
    REORDER,
    EditEnv,
    inline,
    make_edit_env,
    manual,
    request,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

LAYERS = {"style": {"color_mode": "layer"}}
#: Rent and Food swap the third and fourth hue when the dragged order puts Food first.
PINNED = {"Rent": "#1baf7a", "Food": "#eda100"}
MANUAL_PINS = {"b": "#2a78d6", "y": "#eb6834", "a": "#1baf7a", "x": "#eda100"}


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[EditEnv]:
    with make_edit_env(tmp_path, mongo_client) as made:
        yield made


def plan(env: EditEnv, source: Any, edit: dict[str, Any], **transform: Any) -> EditOutcome:
    return plan_edit(env.services, request(source, edit, **transform), env.cache)


def content_of(outcome: EditOutcome) -> str:
    assert isinstance(outcome.source, TextSource)
    return outcome.source.content or ""


def test_an_entry_is_appended_to_pasted_csv(env: EditEnv) -> None:
    outcome = plan(env, inline(), ADD)
    assert (outcome.where, outcome.changed, outcome.written) == ("draft", 1, False)
    assert (outcome.consent, outcome.reason, outcome.notice) == ("none", None, None)
    assert (outcome.target, outcome.target_key, outcome.override) == (None, None, None)
    assert content_of(outcome) == CSV + "Budget,Gifts,50,Fun\n"
    assert env.cache.puts, "the candidate graph was built (the cache is warm for /preview)"


def test_an_entry_that_closes_a_cycle_is_a_422_and_nothing_is_answered(env: EditEnv) -> None:
    cycle = {"op": "add_entry", "source": "Rent", "target": "Salary", "value": 5}
    with pytest.raises(GraphBuildError):
        plan(env, inline(), cycle)
    with pytest.raises(GraphBuildError):
        plan(env, manual(("a", "b", 1, None)), {**cycle, "source": "b", "target": "a"})


def test_a_category_is_written_into_the_cell(env: EditEnv) -> None:
    outcome = plan(env, inline(), CATEGORISE)
    assert (outcome.where, outcome.changed) == ("draft", 1)
    assert "Budget,Food,640,Fun\n" in content_of(outcome)
    assert outcome.override == "drop"


def test_a_category_can_be_cleared(env: EditEnv) -> None:
    clear = {**CATEGORISE, "target": "Rent", "category": None}
    outcome = plan(env, inline(), clear)
    assert "Budget,Rent,1200,\n" in content_of(outcome)
    assert outcome.override == "drop"


@pytest.mark.parametrize(
    ("edit", "transform", "expected"),
    [
        ({"category": "Fun"}, {}, "drop"),
        ({"category": "Fun"}, {"rules_override": True}, "set"),
        ({"category": None}, {}, "drop"),
        ({"category": None}, {"category_rules": [{"pattern": "Food", "category": "F"}]}, "set"),
        (
            {"category": "Fun"},
            {"extra_links": [{"source": "Budget", "target": "Rent", "value": 1}]},
            "set",
        ),
        (
            {"category": None},
            {"extra_links": [{"source": "Budget", "target": "Rent", "value": 1}]},
            "set",
        ),
        (
            {"category": "Fun"},
            {"extra_links": [{"source": "Budget", "target": "Gifts", "value": 1}]},
            "drop",
        ),
    ],
)
def test_the_override_directive_after_a_category(
    env: EditEnv, edit: dict[str, Any], transform: dict[str, Any], expected: str
) -> None:
    chosen = {**CATEGORISE, "target": "Rent", **edit}
    outcome = plan(env, inline(), chosen, **transform)
    assert outcome.override == expected


def test_the_override_directive_follows_merged_names(env: EditEnv) -> None:
    extra = [{"source": "Spend", "target": "Food", "value": 1}]
    merged = {"merge_nodes": {"Spend": "Budget"}, "extra_links": extra}
    assert plan(env, inline(), CATEGORISE, **merged).override == "set"


def test_a_category_for_an_unknown_pair_stays_in_the_graph(env: EditEnv) -> None:
    outcome = plan(env, inline(), {**CATEGORISE, "target": "Nothing"})
    assert outcome == EditOutcome(where="graph", reason="no_match", notice=NOTICES["no_match"])


def test_an_unreadable_text_stays_in_the_graph(env: EditEnv) -> None:
    outcome = plan(env, inline("this is not data\n"), CATEGORISE)
    assert (outcome.where, outcome.reason) == ("graph", "unreadable")
    assert outcome.notice == NOTICES["unreadable"]


def test_the_rows_follow_a_reorder_when_the_colours_survive(env: EditEnv) -> None:
    outcome = plan(env, inline(), REORDER, **LAYERS)
    assert (outcome.where, outcome.changed, outcome.override) == ("draft", 2, None)
    assert content_of(outcome).splitlines()[1:] == [
        "Salary,Budget,3000,Income",
        "Budget,Food,640,",
        "Budget,Rent,1200,Housing",
    ]


def test_a_reorder_that_would_repaint_the_chart_pins_the_colours_and_keeps_the_rows(
    env: EditEnv,
) -> None:
    outcome = plan(env, inline(), REORDER)
    assert (outcome.where, outcome.changed, outcome.reason) == ("draft", 2, None)
    assert outcome.pins == StylePins(node_colors=PINNED)
    assert content_of(outcome).splitlines()[2:] == [
        "Budget,Food,640,",
        "Budget,Rent,1200,Housing",
    ]


def test_a_reorder_that_keeps_every_colour_has_no_pins(env: EditEnv) -> None:
    assert plan(env, inline(), REORDER, **LAYERS).pins is None


def test_a_colour_already_pinned_is_not_pinned_again(env: EditEnv) -> None:
    style = {"node_colors": {"Rent": "#112233"}}
    outcome = plan(env, inline(), REORDER, style=style)
    assert outcome.pins == StylePins(node_colors={"Food": "#eda100"})


def test_a_style_without_room_for_the_pins_keeps_the_rows(env: EditEnv) -> None:
    full = {f"n{i}": "#112233" for i in range(MAX_COLOR_OVERRIDES)}
    outcome = plan(env, inline(), REORDER, style={"node_colors": full})
    assert outcome == EditOutcome(
        where="graph", reason="would_recolour", notice=NOTICES["would_recolour"]
    )


def test_a_reorder_that_changes_nothing_stays_silent(env: EditEnv) -> None:
    done = {"op": "reorder", "order": ["Salary", "Budget", "Rent", "Food"]}
    outcome = plan(env, inline(), done, **LAYERS)
    assert outcome == EditOutcome(where="graph", reason="order_in_graph")


def test_the_first_edit_of_pasted_json_says_it_was_reformatted(env: EditEnv) -> None:
    text = '[{"source":"a","target":"b","value":1}]'
    outcome = plan(env, inline(text), {**ADD, "source": "b", "target": "c"})
    assert (outcome.where, outcome.reason, outcome.notice) == ("draft", None, REFORMATTED_NOTICE)
    assert '"target": "c"' in content_of(outcome)


def test_pins_the_rewriter_needed_travel_with_the_source(env: EditEnv) -> None:
    outcome = plan(env, inline(""), {**ADD, "category": None})
    assert content_of(outcome) == "source,target,value\nBudget,Gifts,50\n"
    assert isinstance(outcome.source, TextSource)
    assert outcome.source.format == "csv"


def test_a_new_manual_link_is_appended(env: EditEnv) -> None:
    source = manual(("a", "b", 2, None))
    outcome = plan(env, source, {**ADD, "source": "b", "target": "c"})
    assert (outcome.where, outcome.changed) == ("draft", 1)
    assert isinstance(outcome.source, ManualSource)
    assert [(item.source, item.target) for item in outcome.source.links] == [("a", "b"), ("b", "c")]


def test_manual_categories_go_by_the_merged_pair(env: EditEnv) -> None:
    source = manual(("a", "b", 2, None), ("A", "b", 3, "Old"), ("c", "d", 1, None))
    edit = {"op": "set_category", "source": "a", "target": "b", "category": "New"}
    outcome = plan(env, source, edit, merge_nodes={"A": "a"})
    assert outcome.changed == 2
    assert isinstance(outcome.source, ManualSource)
    assert [item.category for item in outcome.source.links] == ["New", "New", None]
    assert outcome.override == "drop"


def test_a_manual_category_for_an_unknown_pair_stays_in_the_graph(env: EditEnv) -> None:
    outcome = plan(env, manual(("a", "b", 2, None)), {**CATEGORISE, "source": "x", "target": "y"})
    assert (outcome.where, outcome.reason) == ("graph", "no_match")


def test_manual_links_follow_a_reorder(env: EditEnv) -> None:
    source = manual(("b", "y", 1, None), ("a", "x", 1, None))
    outcome = plan(env, source, {"op": "reorder", "order": ["a", "b", "x", "y"]}, **LAYERS)
    assert outcome.where == "draft"
    assert isinstance(outcome.source, ManualSource)
    assert [item.source for item in outcome.source.links] == ["a", "b"]
    swapped = plan(env, source, {"op": "reorder", "order": ["a", "b", "x", "y"]})
    assert (swapped.where, swapped.reason, swapped.changed) == ("draft", None, 2)
    assert swapped.pins == StylePins(node_colors=MANUAL_PINS)


def test_a_full_manual_table_is_an_error_not_an_overlay(env: EditEnv) -> None:
    full = ManualSource(links=[Link(source=f"s{i}", target=f"t{i}", value=1) for i in range(5000)])
    with pytest.raises(SourceEditRefused) as refused:
        plan(env, full, ADD)
    assert refused.value.reason == "too_many"


def test_a_cyclic_merge_map_is_a_graph_error(env: EditEnv) -> None:
    with pytest.raises(GraphBuildError):
        plan(env, inline(), ADD, merge_nodes={"a": "b", "b": "a"})
