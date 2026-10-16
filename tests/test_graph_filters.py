# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``build_graph``: hide_nodes, min_link_value and top_links (category-agnostic pair totals)."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from tests.graph_support import make_graph, pair_totals, rows

if TYPE_CHECKING:
    from sankey_studio.models import RawLink

BASE: list[RawLink] = [
    ("A", "B", 10.0, None),
    ("B", "C", 6.0, None),
    ("B", "D", 4.0, None),
    ("A", "E", 1.0, None),
]


def test_hidden_nodes_take_their_links_and_orphans_with_them() -> None:
    graph = make_graph(BASE, hide_nodes=["C"])
    assert graph.node_names == ("A", "B", "D", "E")
    assert pair_totals(graph) == {("A", "B"): 10.0, ("B", "D"): 4.0, ("A", "E"): 1.0}
    assert graph.node_out[graph.node_names.index("B")] == 4.0


def test_hiding_a_middle_node_drops_nodes_that_lose_every_link() -> None:
    graph = make_graph(BASE, hide_nodes=["B"])
    assert graph.node_names == ("A", "E")
    assert graph.node_color_slot == (0, 4)


@pytest.mark.parametrize("hide", [[], ["nobody"], ["b"], ["Old"]])
def test_unknown_or_differently_spelled_hide_names_change_nothing(hide: list[str]) -> None:
    graph = make_graph(
        [*BASE, ("Old", "A", 1.0, None)], hide_nodes=hide, merge_nodes={"Old": "New"}
    )
    assert pair_totals(graph) == {
        ("A", "B"): 10.0,
        ("B", "C"): 6.0,
        ("B", "D"): 4.0,
        ("A", "E"): 1.0,
        ("New", "A"): 1.0,
    }


def test_hide_nodes_names_are_post_merge_names() -> None:
    graph = make_graph(
        [("Old", "B", 1.0, None), ("X", "B", 2.0, None)],
        hide_nodes=["New"],
        merge_nodes={"Old": "New"},
    )
    assert graph.node_names == ("B", "X")
    assert graph.node_color_slot == (1, 2)


class Threshold(NamedTuple):
    minimum: float
    kept: list[tuple[str, str]]


THRESHOLDS = [
    Threshold(0.0, [("A", "B"), ("B", "C"), ("B", "D"), ("A", "E")]),
    Threshold(1.0, [("A", "B"), ("B", "C"), ("B", "D"), ("A", "E")]),
    Threshold(1.0000001, [("A", "B"), ("B", "C"), ("B", "D")]),
    Threshold(4.0, [("A", "B"), ("B", "C"), ("B", "D")]),
    Threshold(4.5, [("A", "B"), ("B", "C")]),
    Threshold(10.0, [("A", "B")]),
    Threshold(10.5, []),
]


@pytest.mark.parametrize("case", THRESHOLDS)
def test_min_link_value_keeps_pairs_at_or_above_it(case: Threshold) -> None:
    graph = make_graph(BASE, min_link_value=case.minimum)
    assert list(pair_totals(graph)) == case.kept


@pytest.mark.parametrize(
    ("minimum", "kept"),
    [(0.1, 3), (0.25, 3), (0.2500001, 2), (0.5, 2), (0.75, 1), (1.0, 1), (1.5, 0)],
)
def test_min_link_value_works_below_one(minimum: float, kept: int) -> None:
    links: list[RawLink] = [("A", "B", 0.25, None), ("A", "C", 0.5, None), ("A", "D", 1.0, None)]
    assert len(pair_totals(make_graph(links, min_link_value=minimum))) == kept


def test_min_link_value_compares_the_pair_total_not_each_category() -> None:
    links: list[RawLink] = [("A", "B", 3.0, "x"), ("A", "B", 3.0, "y"), ("A", "C", 4.9, "x")]
    graph = make_graph(links, min_link_value=5.0)
    assert rows(graph) == [("A", "B", 3.0, "x"), ("A", "B", 3.0, "y")]


class Top(NamedTuple):
    top: int
    kept: list[tuple[str, str]]


TOPS = [
    Top(1, [("A", "B")]),
    Top(2, [("A", "B"), ("B", "C")]),
    Top(3, [("A", "B"), ("B", "C"), ("B", "D")]),
    Top(4, [("A", "B"), ("B", "C"), ("B", "D"), ("A", "E")]),
    Top(5, [("A", "B"), ("B", "C"), ("B", "D"), ("A", "E")]),
]


@pytest.mark.parametrize("case", TOPS)
def test_top_links_keeps_the_largest_pairs_in_first_appearance_order(case: Top) -> None:
    graph = make_graph(BASE, top_links=case.top)
    assert list(pair_totals(graph)) == case.kept


def test_top_links_ties_go_to_the_first_appearance() -> None:
    links: list[RawLink] = [("A", "B", 2.0, None), ("A", "C", 2.0, None), ("A", "D", 2.0, None)]
    assert list(pair_totals(make_graph(links, top_links=2))) == [("A", "B"), ("A", "C")]


def test_top_links_ranks_pair_totals_not_single_categorised_links() -> None:
    links: list[RawLink] = [
        ("A", "B", 3.0, "x"),
        ("A", "B", 3.0, "y"),
        ("A", "C", 5.0, "x"),
    ]
    graph = make_graph(links, top_links=1)
    assert rows(graph) == [("A", "B", 3.0, "x"), ("A", "B", 3.0, "y")]


def test_min_link_value_applies_before_top_links() -> None:
    graph = make_graph(BASE, min_link_value=4.5, top_links=3)
    assert list(pair_totals(graph)) == [("A", "B"), ("B", "C")]


def test_hide_applies_before_the_pair_filters() -> None:
    graph = make_graph(BASE, hide_nodes=["A"], top_links=1)
    assert list(pair_totals(graph)) == [("B", "C")]


def test_filters_drop_nodes_left_without_a_pair_and_keep_slots() -> None:
    graph = make_graph(BASE, min_link_value=5.0)
    assert graph.node_names == ("A", "B", "C")
    assert graph.node_color_slot == (0, 1, 2)
    graph = make_graph(BASE, top_links=1, hide_nodes=["A"])
    assert graph.node_names == ("B", "C")
    assert graph.node_color_slot == (1, 2)
    assert graph.node_layers == (0, 1)
