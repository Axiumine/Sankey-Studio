# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Step 3: hide nodes, aggregate to (source, target) PAIR totals, ``min_link_value``, top-N.

Pairs are category agnostic: categories never decide which pairs or nodes survive, so the
topology of a graph is the same with and without categories.
"""

from __future__ import annotations

from array import array
from itertools import accumulate
from typing import TYPE_CHECKING

from sankey_studio.graph.intern import TARGET_SHIFT
from sankey_studio.models.base import INDEX_TYPECODE

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sankey_studio.graph.state import BuildState


def take[T: (int, float)](column: array[T], keep: Iterable[int]) -> array[T]:
    """The rows of ``column`` at the positions ``keep``, as a new array of the same type."""
    return array(column.typecode, (column[i] for i in keep))


def hide_nodes(state: BuildState) -> None:
    """Drop every entry that touches a hidden node (names are post-merge)."""
    wanted = state.transform.hide_nodes
    if not wanted:
        return
    ids = {name: i for i, name in enumerate(state.names)}
    hidden = {ids[name] for name in wanted if name in ids}
    if not hidden:
        return
    pairs = enumerate(zip(state.e_src, state.e_tgt, strict=True))
    keep = [i for i, (s, t) in pairs if s not in hidden and t not in hidden]
    state.e_src = take(state.e_src, keep)
    state.e_tgt = take(state.e_tgt, keep)
    state.e_cat = take(state.e_cat, keep)
    state.e_val = take(state.e_val, keep)


def aggregate_pairs(state: BuildState) -> None:
    """Sum the entries per ``(source, target)`` pair; pairs keep first-appearance order."""
    index: dict[int, int] = {}
    p_src, p_tgt, p_val, e_pair = state.p_src, state.p_tgt, state.p_val, state.e_pair
    for s, t, value in zip(state.e_src, state.e_tgt, state.e_val, strict=True):
        pair_key = (s << TARGET_SHIFT) | t
        pair = index.get(pair_key)
        if pair is None:
            pair = index[pair_key] = len(p_val)
            p_src.append(s)
            p_tgt.append(t)
            p_val.append(0.0)
        p_val[pair] += value
        e_pair.append(pair)


def surviving_pairs(state: BuildState) -> list[int] | None:
    """Positions of the pairs that pass ``min_link_value`` and ``top_links`` (``None`` = all)."""
    minimum, top = state.transform.min_link_value, state.transform.top_links
    if minimum <= 0 and top is None:
        return None
    p_val = state.p_val
    keep = [p for p in range(state.n_pairs) if p_val[p] >= minimum]
    if top is not None:
        largest_first = sorted(keep, key=lambda p: -p_val[p])  # stable: ties keep first appearance
        keep = sorted(largest_first[:top])
    return keep


def filter_pairs(state: BuildState) -> None:
    """Apply ``min_link_value`` (``>=``) and then ``top_links`` on the pair totals."""
    keep = surviving_pairs(state)
    if keep is not None:
        apply_pair_selection(state, keep)


def apply_pair_selection(state: BuildState, keep: list[int]) -> None:
    """Keep only the pairs at ``keep`` (ascending); their entries are re-pointed, others get -1."""
    remap = array("i", [-1]) * state.n_pairs
    for new, old in enumerate(keep):
        remap[old] = new
    state.p_src = take(state.p_src, keep)
    state.p_tgt = take(state.p_tgt, keep)
    state.p_val = take(state.p_val, keep)
    state.e_pair = array("i", (-1 if p < 0 else remap[p] for p in state.e_pair))


def adjacency(n_nodes: int, p_src: array[int]) -> tuple[array[int], array[int]]:
    """Out-edges in compressed form: ``edges[start[u]:start[u + 1]]`` are the pairs leaving ``u``.

    Edges of one node keep pair order, so every traversal is deterministic.
    """
    counts = array(INDEX_TYPECODE, [0]) * n_nodes
    for source in p_src:
        counts[source] += 1
    start = array(INDEX_TYPECODE, accumulate(counts, initial=0))
    fill = array(INDEX_TYPECODE, start[:-1])
    edges = array(INDEX_TYPECODE, range(len(p_src)))  # every slot is overwritten below
    for pair, source in enumerate(p_src):
        edges[fill[source]] = pair
        fill[source] += 1
    return start, edges
