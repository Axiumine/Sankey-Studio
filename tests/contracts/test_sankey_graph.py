# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests: ``SankeyGraph`` column validation and category rules."""

from __future__ import annotations

from array import array
from typing import Any

import pytest

from sankey_studio.models import SankeyGraph


def _graph(**over: Any) -> SankeyGraph:
    base: dict[str, Any] = {
        "node_names": ("a", "b", "c"),
        "node_layers": (0, 1, 2),
        "node_color_slot": (0, 1, 2),
        "node_in": (0.0, 5.0, 3.0),
        "node_out": (5.0, 3.0, 0.0),
        "link_source": array("i", [0, 1]),
        "link_target": array("i", [1, 2]),
        "link_value": array("d", [5.0, 3.0]),
        "link_category": array("i", [-1, -1]),
    }
    return SankeyGraph(**{**base, **over})


def test_graph_without_categories_uses_minus_one_only() -> None:
    graph = _graph()
    assert graph.categories == ()
    assert graph.category_color_slot == ()
    assert graph.has_categories is False
    assert (graph.n_nodes, graph.n_links) == (3, 2)
    assert list(graph.link_category) == [-1, -1]


def test_graph_with_categories_keeps_uncategorised_as_minus_one() -> None:
    graph = _graph(
        link_category=array("i", [0, -1]),
        categories=("Food",),
        category_color_slot=(3,),
    )
    assert graph.has_categories is True
    assert "Uncategorized" not in graph.categories  # a render-time label, never stored


@pytest.mark.parametrize(
    "bad",
    [
        {"link_category": array("i", [0, -1])},  # index without categories
        {"link_category": array("i", [-2, -1])},
        {"link_category": array("i", [1, -1]), "categories": ("a",), "category_color_slot": (0,)},
        {"categories": ("a",)},  # slot count mismatch
        {"node_in": (0.0, 5.0)},
        {"node_color_slot": (0, 1)},
        {"link_value": array("d", [5.0])},
        {"link_source": array("i", [0, 3])},
        {"link_target": array("i", [-1, 2])},
        {"link_source": array("I", [0, 1])},  # unsigned cannot hold -1: wrong typecode
        {"link_category": array("b", [-1, -1])},
        {"link_value": array("f", [5.0, 3.0])},
        {"link_value": [5.0, 3.0]},
    ],
)
def test_graph_rejects_inconsistent_columns(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"must|needs"):
        _graph(**bad)


@pytest.mark.parametrize(
    "names",
    [
        ("Uncategorized",),
        ("other",),
        ("Food", " OTHER "),
        ("Food", "food"),
        ("Cafe\u0301", "Caf\u00e9"),
        ("Food", "  FOOD "),
        ("",),
        ("a\0b",),
    ],
)
def test_graph_categories_must_be_real_and_unique(names: tuple[str, ...]) -> None:
    """``Uncategorized``/``Other`` are renderer labels; case/NFC twins would share one colour."""
    with pytest.raises(ValueError, match=r"categories|control"):
        _graph(
            link_category=array("i", [0, -1]),
            categories=names,
            category_color_slot=tuple(range(len(names))),
        )


def test_graph_accepts_distinct_real_categories() -> None:
    graph = _graph(
        link_category=array("i", [1, 0]),
        categories=("Food", "Others", "Other stuff"),
        category_color_slot=(0, 1, 9),
    )
    assert graph.categories == ("Food", "Others", "Other stuff")


def test_graph_is_hashable_by_identity_and_immutable() -> None:
    first, second = _graph(), _graph()
    assert hash(first) != hash(second)
    assert first != second
    assert {first: 1}[first] == 1
    with pytest.raises(AttributeError):
        first.warnings = ("x",)  # type: ignore[misc]


def test_empty_graph_is_valid() -> None:
    graph = SankeyGraph(
        node_names=(),
        node_layers=(),
        node_color_slot=(),
        node_in=(),
        node_out=(),
        link_source=array("i"),
        link_target=array("i"),
        link_value=array("d"),
        link_category=array("i"),
    )
    assert (graph.n_nodes, graph.n_links, graph.has_categories) == (0, 0, False)
