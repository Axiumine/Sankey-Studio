# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``build_graph``: nodes, layers, pair totals and node sums."""

from __future__ import annotations

from array import array

import pytest

from sankey_studio.graph import build_graph
from sankey_studio.models import RawLink, TransformSpec
from sankey_studio.sources.base import Diagnostics
from tests.graph_support import BIG, make_graph, pair_totals, rows

CHAIN: list[RawLink] = [("A", "B", 10.0, None), ("B", "C", 4.0, None)]


def test_chain_has_one_layer_per_step() -> None:
    graph = make_graph(CHAIN)
    assert graph.node_names == ("A", "B", "C")
    assert graph.node_layers == (0, 1, 2)
    assert graph.node_in == (0.0, 10.0, 4.0)
    assert graph.node_out == (10.0, 4.0, 0.0)
    assert graph.warnings == ()
    assert graph.categories == ()


def test_layers_are_longest_paths() -> None:
    links: list[RawLink] = [
        ("A", "D", 1.0, None),
        ("A", "B", 1.0, None),
        ("B", "C", 1.0, None),
        ("C", "D", 1.0, None),
        ("X", "C", 1.0, None),
    ]
    graph = make_graph(links)
    layers = dict(zip(graph.node_names, graph.node_layers, strict=True))
    assert layers == {"A": 0, "D": 3, "B": 1, "C": 2, "X": 0}


def test_nodes_follow_first_appearance_source_before_target() -> None:
    graph = make_graph([("Z", "A", 1.0, None), ("M", "Z", 1.0, None), ("A", "Q", 1.0, None)])
    assert graph.node_names == ("Z", "A", "M", "Q")
    assert graph.node_color_slot == (0, 1, 2, 3)


def test_duplicate_rows_are_summed_per_pair() -> None:
    graph = make_graph([("A", "B", 0.5, None), ("A", "B", 0.25, None), ("B", "C", 1.0, None)])
    assert rows(graph) == [("A", "B", 0.75, None), ("B", "C", 1.0, None)]
    assert graph.node_out == (0.75, 1.0, 0.0)
    assert graph.node_in == (0.0, 0.75, 1.0)


def test_pairs_keep_first_appearance_order() -> None:
    graph = make_graph([("B", "C", 1.0, None), ("A", "B", 2.0, None), ("B", "C", 3.0, None)])
    assert list(pair_totals(graph)) == [("B", "C"), ("A", "B")]
    assert pair_totals(graph) == {("B", "C"): 4.0, ("A", "B"): 2.0}


def test_columns_use_the_contract_typecodes() -> None:
    graph = make_graph(CHAIN)
    assert isinstance(graph.link_source, array)
    assert graph.link_source.typecode == "i"
    assert graph.link_target.typecode == "i"
    assert graph.link_category.typecode == "i"
    assert graph.link_value.typecode == "d"
    assert list(graph.link_category) == [-1, -1]


def test_empty_input_is_an_empty_graph() -> None:
    graph = make_graph([])
    assert (graph.n_nodes, graph.n_links, graph.categories, graph.warnings) == (0, 0, (), ())


def test_imbalanced_nodes_are_not_a_warning() -> None:
    graph = make_graph([("A", "B", 10.0, None), ("B", "C", 1.0, None)])
    assert graph.warnings == ()


def test_diagnostics_come_first_then_the_graph_own_warnings() -> None:
    diag = Diagnostics()
    diag.warn("from the source")
    graph = build_graph(
        [("A", "A2", 1.0, None), ("A", "B", 1.0, None)],
        TransformSpec(merge_nodes={"A2": "A"}),
        max_raw_links=BIG,
        diag=diag,
    )
    assert graph.warnings == (
        "from the source",
        "Dropped 1 link(s) that became self-loops after merging",
    )


def test_diagnostics_overflow_line_is_kept() -> None:
    diag = Diagnostics()
    for i in range(52):
        diag.warn(f"w{i}")
    graph = build_graph(CHAIN, TransformSpec(), max_raw_links=BIG, diag=diag)
    assert len(graph.warnings) == 51
    assert graph.warnings[-1] == "... and 2 more warnings"


@pytest.mark.parametrize("count", [1, 7])
def test_graph_columns_have_one_entry_per_link(count: int) -> None:
    links: list[RawLink] = [(f"s{i}", f"t{i}", float(i + 1), None) for i in range(count)]
    graph = make_graph(links)
    assert graph.n_links == count
    assert graph.n_nodes == 2 * count
    assert sorted(graph.node_layers) == [0] * count + [1] * count
