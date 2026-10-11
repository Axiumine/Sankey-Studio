"""Step 6: split the surviving pairs by category into parallel links and build the graph."""

from __future__ import annotations

from array import array
from typing import TYPE_CHECKING

from sankey_studio.models import SankeyGraph

if TYPE_CHECKING:
    from sankey_studio.graph.state import BuildState


def surviving_nodes(state: BuildState) -> list[int]:
    """Node ids that still have a pair, in first-appearance order."""
    return sorted({*state.p_src, *state.p_tgt})


def link_order(state: BuildState) -> list[int]:
    """Entries of surviving pairs: pairs in first-appearance order, categories in slot order.

    Two stable sorts: first by slot with the uncategorised entry (-1) one past the last real slot,
    then by pair.
    """
    e_pair, e_cat = state.e_pair, state.e_cat
    uncategorised = len(state.categories)
    order = [i for i in range(state.n_entries) if e_pair[i] >= 0]
    order.sort(key=lambda i: e_cat[i] if e_cat[i] >= 0 else uncategorised)
    order.sort(key=e_pair.__getitem__)
    return order


def assemble(state: BuildState) -> SankeyGraph:
    """The final columnar graph; ``categories`` lists only categories on the final links."""
    nodes = surviving_nodes(state)
    new_id = {node: position for position, node in enumerate(nodes)}
    order = link_order(state)
    e_cat, e_pair = state.e_cat, state.e_pair
    present = sorted({e_cat[i] for i in order if e_cat[i] >= 0})
    final_index = {slot: index for index, slot in enumerate(present)}
    return SankeyGraph(
        node_names=tuple(state.names[n] for n in nodes),
        node_layers=tuple(state.layers[n] for n in nodes),
        node_color_slot=tuple(nodes),
        node_in=tuple(state.node_in[n] for n in nodes),
        node_out=tuple(state.node_out[n] for n in nodes),
        link_source=array("i", (new_id[state.p_src[e_pair[i]]] for i in order)),
        link_target=array("i", (new_id[state.p_tgt[e_pair[i]]] for i in order)),
        link_value=array("d", (state.e_val[i] for i in order)),
        link_category=array("i", (final_index.get(e_cat[i], -1) for i in order)),
        categories=tuple(state.categories[slot] for slot in present),
        category_color_slot=tuple(present),
        warnings=tuple(state.diag.finish() + state.warnings),
    )
