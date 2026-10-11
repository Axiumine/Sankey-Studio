"""Colour slots follow the entity: filters, basis and top-N never repaint survivors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.graph_support import make_graph, rows, topology

if TYPE_CHECKING:
    from sankey_studio.models import RawLink

LINKS: list[RawLink] = [
    ("Salary", "Budget", 100.0, "Income"),
    ("Bonus", "Budget", 20.0, "Income"),
    ("Budget", "Rent", 40.0, "Fixed"),
    ("Budget", "Food", 30.0, "Variable"),
    ("Budget", "Fun", 5.0, "Variable"),
    ("Budget", "Tips", 1.0, "Rare"),
    ("Budget", "Misc", 24.0, None),
]

FILTERS: list[dict[str, Any]] = [
    {"hide_nodes": ["Salary"]},
    {"hide_nodes": ["Rent"]},
    {"min_link_value": 10.0},
    {"top_links": 3},
    {"top_links": 1, "min_link_value": 5.0},
    {"hide_nodes": ["Food", "Misc"], "top_links": 4},
]


def node_slots(graph: Any) -> dict[str, int]:
    return dict(zip(graph.node_names, graph.node_color_slot, strict=True))


def category_slots(graph: Any) -> dict[str, int]:
    return dict(zip(graph.categories, graph.category_color_slot, strict=True))


@pytest.mark.parametrize("filters", FILTERS)
def test_filters_never_repaint_survivors(filters: dict[str, Any]) -> None:
    full = make_graph(LINKS)
    filtered = make_graph(LINKS, **filters)
    assert node_slots(filtered).items() <= node_slots(full).items()
    assert category_slots(filtered).items() <= category_slots(full).items()
    assert filtered.n_links < full.n_links


def test_full_graph_slots_are_first_appearance_order() -> None:
    graph = make_graph(LINKS)
    assert node_slots(graph) == {
        "Salary": 0,
        "Budget": 1,
        "Bonus": 2,
        "Rent": 3,
        "Food": 4,
        "Fun": 5,
        "Tips": 6,
        "Misc": 7,
    }
    assert category_slots(graph) == {"Income": 0, "Fixed": 1, "Variable": 2, "Rare": 3}


def test_filtered_slots_keep_gaps_so_hues_stay_put() -> None:
    graph = make_graph(LINKS, hide_nodes=["Salary", "Rent"])
    assert graph.node_names == ("Budget", "Bonus", "Food", "Fun", "Tips", "Misc")
    assert graph.node_color_slot == (1, 2, 4, 5, 6, 7)
    assert graph.categories == ("Income", "Variable", "Rare")
    assert graph.category_color_slot == (0, 2, 3)


@pytest.mark.parametrize("filters", FILTERS)
def test_topology_of_filtered_graphs_ignores_categories(filters: dict[str, Any]) -> None:
    stripped_links: list[RawLink] = [(s, t, v, None) for s, t, v, _c in LINKS]
    assert topology(make_graph(LINKS, **filters)) == topology(make_graph(stripped_links, **filters))


def test_reordered_filters_give_the_same_surviving_rows() -> None:
    first = make_graph(LINKS, min_link_value=5.0, top_links=4)
    second = make_graph(LINKS, top_links=4, min_link_value=5.0)
    assert rows(first) == rows(second)
