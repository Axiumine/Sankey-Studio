"""``build_graph`` steps below the public surface: link order, pair selection, caches, columns.

These pin behaviour a mutation of the step functions would move without changing any of the
usual end-to-end topology tables (sort keys, sentinels, caches that exist for speed only).
"""

from __future__ import annotations

from array import array
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.graph import categories, intern
from sankey_studio.graph.categories import merge_entries
from sankey_studio.graph.layers import compute_layers
from sankey_studio.graph.pairs import (
    aggregate_pairs,
    apply_pair_selection,
    hide_nodes,
    surviving_pairs,
)
from sankey_studio.graph.state import BuildState
from sankey_studio.models import TransformSpec
from sankey_studio.sources.base import Diagnostics
from sankey_studio.util import category_key
from tests.graph_support import make_graph, rows

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.models import RawLink

INT = "i"
VALUE = "d"


def bare_state(columns: dict[str, Any], **transform: Any) -> BuildState:
    """A ``BuildState`` with hand-set columns (no ``build_graph`` run)."""
    state = BuildState(transform=TransformSpec.model_validate(transform), diag=Diagnostics())
    for name, column in columns.items():
        setattr(state, name, column)
    return state


def test_the_uncategorised_entry_of_a_pair_stays_inside_its_pair() -> None:
    graph = make_graph([("A", "B", 1.0, "x"), ("C", "D", 2.0, "x"), ("A", "B", 3.0, None)])
    assert rows(graph) == [
        ("A", "B", 1.0, "x"),
        ("A", "B", 3.0, None),
        ("C", "D", 2.0, "x"),
    ]


def test_categories_of_a_pair_come_in_slot_order_then_uncategorised() -> None:
    links: list[RawLink] = [
        ("A", "B", 1.0, None),
        ("A", "B", 2.0, "y"),
        ("A", "B", 3.0, "x"),
        ("C", "D", 4.0, "x"),
    ]
    assert rows(make_graph(links)) == [
        ("A", "B", 2.0, "y"),
        ("A", "B", 3.0, "x"),
        ("A", "B", 1.0, None),
        ("C", "D", 4.0, "x"),
    ]


def test_a_pair_dropped_by_min_link_value_stays_dropped_when_cycles_break() -> None:
    links: list[RawLink] = [
        ("B", "A", 5.0, None),
        ("A", "B", 10.0, None),
        ("X", "Y", 1.0, None),
        ("P", "Q", 3.0, None),
    ]
    graph = make_graph(links, min_link_value=2, on_cycle="break")
    assert rows(graph) == [("B", "A", 5.0, None), ("P", "Q", 3.0, None)]
    assert graph.node_names == ("B", "A", "P", "Q")


def test_apply_pair_selection_marks_dropped_entries_with_minus_one() -> None:
    state = bare_state(
        {
            "p_src": array(INT, [0, 1, 2]),
            "p_tgt": array(INT, [1, 2, 3]),
            "p_val": array(VALUE, [1.0, 2.0, 3.0]),
            "e_pair": array(INT, [0, 1, 2, -1, 1]),
        }
    )
    apply_pair_selection(state, [0, 2])
    assert list(state.e_pair) == [0, -1, 1, -1, -1]
    assert list(state.p_src) == [0, 2]
    assert list(state.p_tgt) == [1, 3]
    assert list(state.p_val) == [1.0, 3.0]


class Selection(NamedTuple):
    values: list[float]
    transform: dict[str, Any]
    expected: list[int] | None


SELECTIONS = [
    Selection([1.0, 2.0], {}, None),
    Selection([-1.0, 2.0], {}, None),
    Selection([1.0, 2.0, 3.0], {"min_link_value": 2.0}, [1, 2]),
    Selection([1.0, 2.0, 3.0], {"min_link_value": 0.5, "top_links": 2}, [1, 2]),
    Selection([1.0, 5.0, 3.0, 5.0], {"top_links": 2}, [1, 3]),
    Selection([5.0, 1.0, 5.0, 5.0], {"top_links": 2}, [0, 2]),
    Selection([1.0, 5.0, 3.0], {"top_links": 3}, [0, 1, 2]),
    Selection([1.0, 5.0, 3.0], {"top_links": 4}, [0, 1, 2]),
    Selection([1.0, 5.0, 3.0], {"top_links": 1}, [1]),
]


@pytest.mark.parametrize("case", SELECTIONS, ids=lambda c: str(c.transform))
def test_surviving_pairs_table(case: Selection) -> None:
    state = bare_state({"p_val": array(VALUE, case.values)}, **case.transform)
    assert surviving_pairs(state) == case.expected


def test_top_links_keeps_the_largest_pairs_not_the_first_ones() -> None:
    links: list[RawLink] = [("A", "B", 1.0, None), ("A", "C", 2.0, None), ("A", "D", 9.0, None)]
    assert rows(make_graph(links, top_links=1)) == [("A", "D", 9.0, None)]


def test_category_key_runs_once_per_distinct_resolved_name(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = category_key

    def record(name: str) -> str:
        seen.append(name)
        return real(name)

    monkeypatch.setattr(categories, "category_key", record)
    links: list[RawLink] = [("A", f"B{i}", 1.0, None) for i in range(5)]
    graph = make_graph(
        links, category_rules=[{"pattern": "B*", "category": "Food", "match": "target"}]
    )
    assert graph.categories == ("Food",)
    assert graph.n_links == 5
    assert seen == ["Food"]


def test_names_are_interned_once_per_distinct_raw_name(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = intern.intern_node

    def record(state: BuildState, name: str, alias: Any) -> int:
        seen.append(name)
        return real(state, name, alias)

    monkeypatch.setattr(intern, "intern_node", record)
    links: list[RawLink] = [
        ("A", "B", 1.0, None),
        ("A", "B", 2.0, None),
        ("B", "C", 3.0, None),
        ("A", "C", 4.0, None),
    ]
    graph = make_graph(links)
    assert seen == ["A", "B", "C"]
    assert graph.node_names == ("A", "B", "C")


def test_the_spelling_found_in_the_data_beats_the_one_of_a_rule() -> None:
    links: list[RawLink] = [("A", "B", 1.0, None), ("C", "D", 2.0, "FOOD")]
    graph = make_graph(
        links, category_rules=[{"pattern": "A", "category": "food", "match": "source"}]
    )
    assert graph.categories == ("FOOD",)
    assert rows(graph) == [("A", "B", 1.0, "FOOD"), ("C", "D", 2.0, "FOOD")]


@pytest.mark.parametrize(
    ("source", "target"),
    [("A", "nowhere"), ("nowhere", "B"), ("nowhere", "nothing")],
)
def test_an_entry_choice_naming_an_unknown_node_matches_no_entry(source: str, target: str) -> None:
    choice = {"source": source, "target": target, "category": "x"}
    graph = make_graph([("A", "B", 1.0, None)], entry_categories=[choice])
    assert graph.categories == ()
    assert graph.warnings == ("1 entry_categories matched no entry",)


def test_a_rule_on_each_side_picks_the_earlier_rule() -> None:
    rules = [
        {"pattern": "T*", "category": "by-target", "match": "target"},
        {"pattern": "S*", "category": "by-source", "match": "source"},
    ]
    graph = make_graph([("S1", "T1", 1.0, None)], category_rules=rules)
    assert rows(graph) == [("S1", "T1", 1.0, "by-target")]
    graph = make_graph([("S1", "T1", 1.0, None)], category_rules=rules[::-1])
    assert rows(graph) == [("S1", "T1", 1.0, "by-source")]


def misaligned_hide() -> None:
    state = bare_state(
        {"names": ["a"], "e_src": array(INT, [0, 0]), "e_tgt": array(INT, [0])},
        hide_nodes=["a"],
    )
    hide_nodes(state)


def misaligned_pairs() -> None:
    aggregate_pairs(
        bare_state(
            {
                "names": ["a"],
                "e_src": array(INT, [0, 0]),
                "e_tgt": array(INT, [0, 0]),
                "e_val": array(VALUE, [1.0]),
            }
        )
    )


def misaligned_merge() -> None:
    merge_entries(
        bare_state(
            {
                "e_src": array(INT, [0, 0]),
                "e_tgt": array(INT, [0, 0]),
                "e_cat": array(INT, [0]),
                "e_val": array(VALUE, [1.0, 1.0]),
            }
        )
    )


def misaligned_layers() -> None:
    compute_layers(
        bare_state(
            {
                "names": ["a"],
                "p_src": array(INT, [0, 0]),
                "p_tgt": array(INT, [0]),
                "p_val": array(VALUE, [1.0, 1.0]),
            }
        )
    )


@pytest.mark.parametrize(
    "step", [misaligned_hide, misaligned_pairs, misaligned_merge, misaligned_layers]
)
def test_columns_of_different_lengths_are_refused_not_truncated(step: Callable[[], None]) -> None:
    with pytest.raises(ValueError, match="zip"):
        step()
