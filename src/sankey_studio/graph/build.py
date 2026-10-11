"""``build_graph``: the six steps in contract order (SPEC section 3, RENDER)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.graph.assemble import assemble
from sankey_studio.graph.categories import resolve_categories
from sankey_studio.graph.cycles import break_cycles
from sankey_studio.graph.intern import stream_links
from sankey_studio.graph.layers import compute_layers
from sankey_studio.graph.pairs import aggregate_pairs, filter_pairs, hide_nodes
from sankey_studio.graph.state import BuildState

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sankey_studio.models import RawLink, SankeyGraph, TransformSpec
    from sankey_studio.sources.base import Diagnostics


def build_graph(
    links: Iterable[RawLink], transform: TransformSpec, *, max_raw_links: int, diag: Diagnostics
) -> SankeyGraph:
    """Turn a stream of raw links into a draw-ready ``SankeyGraph``.

    Order is part of the contract: stream and intern once (merge aliases applied, more than
    ``max_raw_links`` rows raise ``GraphTooLargeError``), resolve one category per aggregated
    entry, hide nodes, aggregate to category-agnostic pair totals, ``min_link_value``,
    ``top_links``, cycles, layers, and only then split pairs into parallel per-category links.
    """
    state = BuildState(transform=transform, diag=diag)
    stream_links(links, state, max_raw_links)
    resolve_categories(state)
    hide_nodes(state)
    aggregate_pairs(state)
    filter_pairs(state)
    break_cycles(state)
    compute_layers(state)
    return assemble(state)
