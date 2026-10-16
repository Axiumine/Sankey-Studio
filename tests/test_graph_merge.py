# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``merge_nodes``: alias chains, merged names and self-loops through merging."""

from __future__ import annotations

import pytest

from sankey_studio.errors import GraphBuildError
from sankey_studio.graph.intern import resolve_aliases
from tests.graph_support import make_graph, rows


@pytest.mark.parametrize(
    ("merge", "expected"),
    [
        ({}, {}),
        ({"a": "b"}, {"a": "b"}),
        ({"a": "b", "b": "c"}, {"a": "c", "b": "c"}),
        ({"b": "c", "a": "b"}, {"a": "c", "b": "c"}),
        ({"a": "b", "x": "b"}, {"a": "b", "x": "b"}),
        ({"a": "a"}, {}),
        ({"a": "b", "b": "b"}, {"a": "b"}),
        ({"a": "b", "b": "b", "c": "a"}, {"a": "b", "c": "b"}),
    ],
)
def test_alias_chains_resolve_to_their_end(merge: dict[str, str], expected: dict[str, str]) -> None:
    assert resolve_aliases(merge) == expected


def test_a_chain_of_five_thousand_aliases_resolves() -> None:
    merge = {f"n{i}": f"n{i + 1}" for i in range(5000)}
    resolved = resolve_aliases(merge)
    assert len(resolved) == 5000
    assert set(resolved.values()) == {"n5000"}


@pytest.mark.parametrize(
    ("merge", "text"),
    [
        ({"a": "b", "b": "a"}, "a -> b -> a"),
        ({"b": "a", "a": "b"}, "b -> a -> b"),
        ({"x": "a", "a": "b", "b": "a"}, "a -> b -> a"),
        ({"a": "b", "b": "c", "c": "a"}, "a -> b -> c -> a"),
    ],
)
def test_a_cyclic_alias_map_is_a_build_error(merge: dict[str, str], text: str) -> None:
    with pytest.raises(GraphBuildError) as caught:
        resolve_aliases(merge)
    assert caught.value.message == f"merge_nodes is cyclic: {text}"


def test_a_long_alias_cycle_names_at_most_eight_nodes() -> None:
    merge = {f"n{i}": f"n{(i + 1) % 12}" for i in range(12)}
    with pytest.raises(GraphBuildError) as caught:
        resolve_aliases(merge)
    shown = caught.value.message.removeprefix("merge_nodes is cyclic: ").split(" -> ")
    assert shown == [f"n{i}" for i in range(8)] + ["n0"]


def test_build_graph_rejects_a_cyclic_alias_map() -> None:
    with pytest.raises(GraphBuildError, match="merge_nodes is cyclic"):
        make_graph([("a", "b", 1.0, None)], merge_nodes={"a": "b", "b": "a"})


def test_merged_names_are_summed_and_interned_post_merge() -> None:
    graph = make_graph(
        [("Rent", "Home", 5.0, None), ("Mortgage", "Home", 7.0, None), ("Rent", "Out", 1.0, None)],
        merge_nodes={"Mortgage": "Rent"},
    )
    assert graph.node_names == ("Rent", "Home", "Out")
    assert rows(graph) == [("Rent", "Home", 12.0, None), ("Rent", "Out", 1.0, None)]


def test_an_alias_takes_the_position_of_its_first_appearance() -> None:
    graph = make_graph(
        [("X", "Y", 1.0, None), ("Old", "Y", 1.0, None), ("New", "Z", 1.0, None)],
        merge_nodes={"Old": "New"},
    )
    assert graph.node_names == ("X", "Y", "New", "Z")


def test_alias_chains_apply_in_build_graph() -> None:
    graph = make_graph([("a", "t", 1.0, None)], merge_nodes={"a": "b", "b": "c"})
    assert graph.node_names == ("c", "t")


@pytest.mark.parametrize("on_cycle", ["error", "break"])
def test_a_link_that_becomes_a_self_loop_is_dropped_with_one_warning(on_cycle: str) -> None:
    graph = make_graph(
        [("A", "A2", 1.0, None), ("A2", "A", 2.0, None), ("A", "B", 3.0, None)],
        merge_nodes={"A2": "A"},
        on_cycle=on_cycle,
    )
    assert rows(graph) == [("A", "B", 3.0, None)]
    assert graph.warnings == ("Dropped 2 link(s) that became self-loops after merging",)


def test_a_raw_self_loop_is_a_cycle_not_a_merge_casualty() -> None:
    with pytest.raises(GraphBuildError, match=r"A -> A"):
        make_graph([("A", "A", 1.0, None), ("A", "B", 1.0, None)])


def test_a_raw_self_loop_is_removed_when_breaking_cycles() -> None:
    graph = make_graph([("A", "A", 1.0, None), ("A", "B", 1.0, None)], on_cycle="break")
    assert rows(graph) == [("A", "B", 1.0, None)]
    assert graph.warnings == ("Removed 1 link(s) that closed a cycle",)
