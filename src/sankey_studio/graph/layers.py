# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Step 5: layers (longest path from a source node, iterative Kahn) and node sums."""

from __future__ import annotations

from array import array
from typing import TYPE_CHECKING

from sankey_studio.graph.pairs import adjacency
from sankey_studio.models.base import INDEX_TYPECODE

if TYPE_CHECKING:
    from sankey_studio.graph.state import BuildState


def compute_layers(state: BuildState) -> None:
    """Fill ``state.layers``, ``node_in`` and ``node_out`` from the (acyclic) pair columns."""
    n_nodes, p_tgt = state.n_nodes, state.p_tgt
    start, edges = adjacency(n_nodes, state.p_src)
    missing = array(INDEX_TYPECODE, [0]) * n_nodes
    for target in p_tgt:
        missing[target] += 1
    layers = array(INDEX_TYPECODE, [0]) * n_nodes
    queue = [node for node in range(n_nodes) if missing[node] == 0]
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        for edge in edges[start[node] : start[node + 1]]:
            target = p_tgt[edge]
            layers[target] = max(layers[target], layers[node] + 1)
            missing[target] -= 1
            if missing[target] == 0:
                queue.append(target)
    state.layers = layers
    state.node_in = array("d", [0.0]) * n_nodes
    state.node_out = array("d", [0.0]) * n_nodes
    for source, target, value in zip(state.p_src, p_tgt, state.p_val, strict=True):
        state.node_out[source] += value
        state.node_in[target] += value
