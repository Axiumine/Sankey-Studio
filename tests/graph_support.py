# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers shared by ``tests/test_graph*.py`` and ``tests/render``: build a graph, read it back."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Final

from sankey_studio.graph import build_graph
from sankey_studio.models import RawLink, SankeyGraph, TransformSpec
from sankey_studio.sources.base import Diagnostics

if TYPE_CHECKING:
    from collections.abc import Iterable

BIG = 10_000_000

#: The wall-clock bounds of the graph tests are set for the maintainer's machine; a hosted runner
#: (``CI`` is set) is several times slower on one thread, so its bounds are wider.
TIME_FACTOR: Final = 4.0 if os.environ.get("CI") else 1.0


def make_graph(links: Iterable[RawLink], **transform: Any) -> SankeyGraph:
    """``build_graph`` with a transform given as plain fields (``on_cycle="break"``, ...)."""
    return build_graph(
        links, TransformSpec.model_validate(transform), max_raw_links=BIG, diag=Diagnostics()
    )


def rows(graph: SankeyGraph) -> list[tuple[str, str, float, str | None]]:
    """The links of ``graph`` as ``(source, target, value, category)`` in link order."""
    out = []
    for i in range(graph.n_links):
        category = graph.link_category[i]
        out.append(
            (
                graph.node_names[graph.link_source[i]],
                graph.node_names[graph.link_target[i]],
                graph.link_value[i],
                None if category < 0 else graph.categories[category],
            )
        )
    return out


def pair_totals(graph: SankeyGraph) -> dict[tuple[str, str], float]:
    """Sum of the link values per (source, target) pair, pairs in first-appearance order."""
    totals: dict[tuple[str, str], float] = {}
    for source, target, value, _category in rows(graph):
        totals[(source, target)] = totals.get((source, target), 0.0) + value
    return totals


def topology(graph: SankeyGraph) -> dict[str, Any]:
    """Everything that must not depend on categories."""
    return {
        "names": graph.node_names,
        "layers": graph.node_layers,
        "slots": graph.node_color_slot,
        "node_in": graph.node_in,
        "node_out": graph.node_out,
        "pairs": pair_totals(graph),
    }


def stripped(links: list[RawLink]) -> list[RawLink]:
    """The same links without any category."""
    return [(s, t, v, None) for s, t, v, _c in links]
