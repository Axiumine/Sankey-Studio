# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Graphs and styles for the render tests."""

from __future__ import annotations

from array import array
from typing import TYPE_CHECKING, Any, NamedTuple

from sankey_studio.models import RawLink, SankeyGraph, StyleSpec
from tests.graph_support import make_graph

if TYPE_CHECKING:
    from collections.abc import Iterator

BUDGET: list[RawLink] = [
    ("Salary", "Budget", 5000.0, "Income"),
    ("Bonus", "Budget", 800.0, "Income"),
    ("Budget", "Housing", 2000.0, "Fixed"),
    ("Budget", "Food", 900.0, "Variable"),
    ("Budget", "Transport", 400.0, "Variable"),
    ("Budget", "Savings", 1500.0, None),
    ("Savings", "Stocks", 1000.0, "Investing"),
    ("Savings", "Cash", 500.0, "Investing"),
]


def budget(**transform: Any) -> SankeyGraph:
    """The sample budget graph: 4 real categories, one uncategorised link."""
    return make_graph(BUDGET, **transform)


def plain() -> SankeyGraph:
    """The same flows without any category."""
    return make_graph([(s, t, v, None) for s, t, v, _c in BUDGET])


def style(**fields: Any) -> StyleSpec:
    return StyleSpec.model_validate(fields)


def many_categories(count: int) -> SankeyGraph:
    """``count`` categories with decreasing value on one source node (value ``1000 - i``)."""
    return make_graph([("Src", f"T{i}", 1000.0 - i, f"cat{i:02d}") for i in range(count)])


class HandLink(NamedTuple):
    """One link of a hand-built graph: node indexes, category slot (-1 = none), value."""

    source: int
    target: int
    category: int
    value: float


def hand_graph(
    nodes: tuple[str, ...], links: list[HandLink], categories: tuple[str, ...]
) -> SankeyGraph:
    """A graph assembled without ``build_graph``: parallel links may repeat a category."""
    return SankeyGraph(
        node_names=nodes,
        node_layers=(0,) * len(nodes),
        node_color_slot=tuple(range(len(nodes))),
        node_in=(0.0,) * len(nodes),
        node_out=(0.0,) * len(nodes),
        link_source=array("i", [link.source for link in links]),
        link_target=array("i", [link.target for link in links]),
        link_value=array("d", [link.value for link in links]),
        link_category=array("i", [link.category for link in links]),
        categories=categories,
        category_color_slot=tuple(range(len(categories))),
    )


def strings(value: object) -> Iterator[str]:
    """Every string value of a figure (keys excluded)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
