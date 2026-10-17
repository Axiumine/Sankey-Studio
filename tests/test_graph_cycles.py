# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``build_graph``: cycles on pairs (error with a named cycle, or break the back-edges)."""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import GraphBuildError
from sankey_studio.graph.cycles import cycle_message
from tests.graph_support import TIME_FACTOR, make_graph, pair_totals, rows

if TYPE_CHECKING:
    from sankey_studio.models import RawLink

TRIANGLE: list[RawLink] = [("A", "B", 3.0, None), ("B", "C", 2.0, None), ("C", "A", 1.0, None)]


def ring(size: int) -> list[RawLink]:
    return [(f"n{i}", f"n{(i + 1) % size}", 1.0, None) for i in range(size)]


@pytest.mark.parametrize(
    ("links", "text"),
    [
        ([("A", "B", 1.0, None), ("B", "A", 1.0, None)], "A -> B -> A"),
        (TRIANGLE, "A -> B -> C -> A"),
        ([("X", "A", 1.0, None), *TRIANGLE], "A -> B -> C -> A"),
        (ring(8), " -> ".join([*(f"n{i}" for i in range(8)), "n0"])),
        (ring(9), " -> ".join(f"n{i}" for i in range(8)) + " -> ... (9 nodes)"),
        (ring(20), " -> ".join(f"n{i}" for i in range(8)) + " -> ... (20 nodes)"),
        ([("A", "A", 1.0, None)], "A -> A"),
    ],
)
def test_error_mode_names_one_cycle(links: list[RawLink], text: str) -> None:
    with pytest.raises(GraphBuildError) as caught:
        make_graph(links)
    assert caught.value.message == (
        f"The links form a cycle: {text}. Set on_cycle to 'break' to drop the links that close it"
    )
    assert caught.value.status_code == 422


def test_cycle_message_formats_short_and_long_cycles() -> None:
    assert cycle_message(["a", "b", "c"], [2, 0]) == (
        "The links form a cycle: c -> a -> c. "
        "Set on_cycle to 'break' to drop the links that close it"
    )
    names = [f"n{i}" for i in range(10)]
    assert "-> ... (10 nodes)." in cycle_message(names, list(range(10)))


def test_break_mode_removes_the_back_edge_and_warns_with_the_count() -> None:
    graph = make_graph(TRIANGLE, on_cycle="break")
    assert rows(graph) == [("A", "B", 3.0, None), ("B", "C", 2.0, None)]
    assert graph.node_layers == (0, 1, 2)
    assert graph.warnings == ("Removed 1 link(s) that closed a cycle",)


def test_break_mode_counts_every_back_edge() -> None:
    links: list[RawLink] = [
        ("A", "B", 1.0, None),
        ("B", "A", 1.0, None),
        ("B", "C", 1.0, None),
        ("C", "B", 1.0, None),
        ("C", "C", 1.0, None),
    ]
    graph = make_graph(links, on_cycle="break")
    assert list(pair_totals(graph)) == [("A", "B"), ("B", "C")]
    assert graph.warnings == ("Removed 3 link(s) that closed a cycle",)


def test_break_mode_removes_every_category_of_the_back_pair() -> None:
    links: list[RawLink] = [("A", "B", 1.0, "x"), ("B", "A", 1.0, "x"), ("B", "A", 2.0, "y")]
    graph = make_graph(links, on_cycle="break")
    assert rows(graph) == [("A", "B", 1.0, "x")]
    assert graph.categories == ("x",)


def test_break_mode_drops_nodes_that_only_had_removed_links() -> None:
    graph = make_graph([("A", "A", 1.0, None)], on_cycle="break")
    assert graph.n_nodes == 0
    assert graph.warnings == ("Removed 1 link(s) that closed a cycle",)


def test_an_acyclic_graph_is_untouched_in_either_mode() -> None:
    links: list[RawLink] = [("A", "B", 1.0, None), ("A", "C", 1.0, None), ("B", "C", 1.0, None)]
    for mode in ("error", "break"):
        graph = make_graph(links, on_cycle=mode)
        assert graph.warnings == ()
        assert graph.n_links == 3


def test_break_mode_always_leaves_an_acyclic_graph() -> None:
    rnd = random.Random(11)
    links: list[RawLink] = [
        (f"n{rnd.randrange(40)}", f"n{rnd.randrange(40)}", 1.0, None) for _ in range(300)
    ]
    graph = make_graph(links, on_cycle="break")
    assert all(
        graph.node_layers[graph.link_source[i]] < graph.node_layers[graph.link_target[i]]
        for i in range(graph.n_links)
    )


def hundred_thousand_node_chain(close: bool) -> list[RawLink]:
    size = 100_000
    links: list[RawLink] = [(f"n{i}", f"n{i + 1}", 1.0, None) for i in range(size - 1)]
    if close:
        links.append((f"n{size - 1}", "n0", 1.0, None))
    return links


def test_cycle_detection_does_not_recurse_at_100k_nodes() -> None:
    started = time.process_time()
    with pytest.raises(GraphBuildError) as caught:
        make_graph(hundred_thousand_node_chain(close=True))
    assert "(100000 nodes)" in caught.value.message
    graph = make_graph(hundred_thousand_node_chain(close=True), on_cycle="break")
    assert graph.n_nodes == 100_000
    assert max(graph.node_layers) == 99_999
    assert graph.warnings == ("Removed 1 link(s) that closed a cycle",)
    assert time.process_time() - started < 10.0 * TIME_FACTOR


def test_layers_at_100k_nodes_are_iterative_too() -> None:
    graph = make_graph(hundred_thousand_node_chain(close=False))
    assert graph.node_layers[-1] == 99_999
