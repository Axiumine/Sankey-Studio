# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""A stored node order: which nodes are drawn in which order, and what the figure says about it."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import plotly.graph_objects as go
import pytest

from sankey_studio.errors import ExportUnavailableError
from sankey_studio.render.export import export_image
from sankey_studio.render.options import FigureOptions, ImageOptions
from sankey_studio.render.sankey import build_figure, node_block
from sankey_studio.render.scene import make_scene, select_drawn
from tests.graph_support import make_graph
from tests.render.support import budget, plain, style

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sankey_studio.models import SankeyGraph
    from sankey_studio.render.scene import Drawn

#: Node names of ``budget()`` in graph (first appearance) order.
GRAPH_ORDER = [
    "Salary",
    "Budget",
    "Bonus",
    "Housing",
    "Food",
    "Transport",
    "Savings",
    "Stocks",
    "Cash",
]


def drawn_names(graph: SankeyGraph, drawn: Drawn) -> list[str]:
    return [graph.node_names[node] for node in drawn.nodes]


def sankey_trace(figure: dict[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = figure["data"][0]
    return trace


def test_the_graph_order_is_what_the_sample_graph_is_built_with() -> None:
    assert list(budget().node_names) == GRAPH_ORDER


@pytest.mark.parametrize("order", [(), [], ["Ghost"], ["Ghost", "Nobody"]])
def test_no_order_or_none_of_its_names_keeps_the_graph_order(order: Sequence[str]) -> None:
    graph = budget()
    drawn = select_drawn(graph, None, order)
    assert drawn_names(graph, drawn) == GRAPH_ORDER
    assert not drawn.ordered


def test_the_order_argument_is_optional_and_means_the_graph_order() -> None:
    graph = budget()
    assert select_drawn(graph, None) == select_drawn(graph, None, ())
    assert not select_drawn(graph, None).ordered


def test_a_complete_order_decides_the_sequence_of_every_node() -> None:
    graph = budget()
    wanted = list(reversed(GRAPH_ORDER))
    drawn = select_drawn(graph, None, wanted)
    assert drawn_names(graph, drawn) == wanted
    assert drawn.ordered


def test_listing_a_node_marks_the_drawing_as_ordered_even_when_nothing_moves() -> None:
    graph = budget()
    drawn = select_drawn(graph, None, ["Salary"])
    assert drawn_names(graph, drawn) == GRAPH_ORDER
    assert drawn.ordered


def test_a_partial_order_puts_the_listed_nodes_first_and_the_rest_in_graph_order() -> None:
    graph = budget()
    drawn = select_drawn(graph, None, ["Cash", "Food"])
    assert drawn_names(graph, drawn) == [
        "Cash",
        "Food",
        "Salary",
        "Budget",
        "Bonus",
        "Housing",
        "Transport",
        "Savings",
        "Stocks",
    ]
    assert drawn.ordered


def test_names_that_are_not_in_the_graph_are_ignored() -> None:
    graph = budget()
    drawn = select_drawn(graph, None, ["Ghost", "Food", "Nobody", "Cash"])
    assert drawn_names(graph, drawn)[:2] == ["Food", "Cash"]
    assert drawn_names(graph, drawn)[2:] == [n for n in GRAPH_ORDER if n not in {"Food", "Cash"}]
    assert drawn.ordered


def test_the_order_never_changes_which_links_are_drawn_or_their_sequence() -> None:
    graph = budget()
    plain_drawn = select_drawn(graph, 5)
    ordered = select_drawn(graph, 5, list(reversed(GRAPH_ORDER)))
    assert ordered.links == plain_drawn.links
    assert ordered.total_links == plain_drawn.total_links
    assert sorted(ordered.nodes) == plain_drawn.nodes


def test_a_cap_drops_the_nodes_it_leaves_without_a_link_even_when_they_are_listed() -> None:
    graph = budget()
    drawn = select_drawn(graph, 2, ["Housing", "Savings", "Salary"])  # Savings is cut off
    assert drawn_names(graph, drawn) == ["Housing", "Salary", "Budget"]
    assert drawn.ordered


def test_a_cap_that_cuts_every_listed_node_is_not_an_ordered_drawing() -> None:
    graph = budget()
    drawn = select_drawn(graph, 2, ["Savings", "Cash"])
    assert drawn_names(graph, drawn) == ["Salary", "Budget", "Housing"]
    assert not drawn.ordered


def test_a_cap_of_zero_draws_nothing_in_any_order() -> None:
    drawn = select_drawn(budget(), 0, ["Salary"])
    assert drawn.nodes == []
    assert not drawn.ordered


def test_an_order_may_be_a_tuple_and_ties_keep_the_graph_order() -> None:
    graph = make_graph([("A", "B", 1.0, None), ("A", "C", 1.0, None), ("A", "D", 1.0, None)])
    drawn = select_drawn(graph, None, ("D",))
    assert drawn_names(graph, drawn) == ["D", "A", "B", "C"]


def test_the_scene_takes_the_order_from_the_style() -> None:
    graph = budget()
    scene = make_scene(graph, style(node_order=["Cash", "Food"]), "light", None)
    assert drawn_names(graph, scene.drawn)[:2] == ["Cash", "Food"]
    assert scene.drawn.ordered


def test_the_scene_applies_the_order_to_the_capped_drawing() -> None:
    graph = budget()
    options = FigureOptions(max_links=2)
    scene = make_scene(graph, style(node_order=["Housing", "Salary"]), "light", options)
    assert drawn_names(graph, scene.drawn) == ["Housing", "Salary", "Budget"]


def test_a_style_without_an_order_draws_in_graph_order() -> None:
    graph = budget()
    scene = make_scene(graph, style(), "light", None)
    assert drawn_names(graph, scene.drawn) == GRAPH_ORDER
    assert not scene.drawn.ordered


# --------------------------------------------------------------------------- the figure


def test_the_figure_asks_for_the_input_order_only_when_an_order_is_stored() -> None:
    graph = budget()
    assert "sort" not in sankey_trace(build_figure(graph, style(), "light"))["node"]
    assert (
        "sort"
        not in sankey_trace(build_figure(graph, style(node_order=["Ghost"]), "light"))["node"]
    )
    ordered = build_figure(graph, style(node_order=["Cash"]), "light")
    assert sankey_trace(ordered)["node"]["sort"] == "input"


def test_node_block_alone_carries_the_sort() -> None:
    graph = budget()
    scene = make_scene(graph, style(node_order=["Food"]), "light", None)
    assert node_block(scene)["sort"] == "input"
    assert "sort" not in node_block(make_scene(graph, style(), "light", None))


def test_the_figure_never_pins_a_node_position() -> None:
    figure = build_figure(budget(), style(node_order=list(reversed(GRAPH_ORDER))), "light")
    node = sankey_trace(figure)["node"]
    assert "x" not in node
    assert "y" not in node


def test_an_ordered_figure_is_valid_for_plotly() -> None:
    figure = build_figure(budget(), style(node_order=["Cash", "Food"]), "dark")
    assert go.Figure(figure).data[0].node.sort == "input"


def named_links(trace: dict[str, Any]) -> list[tuple[str, str, float, str]]:
    """Every link of a trace as ``(source label, target label, value, hover category)``."""
    labels = trace["node"]["label"]
    link = trace["link"]
    return sorted(
        (labels[s], labels[t], v, c[5])
        for s, t, v, c in zip(
            link["source"], link["target"], link["value"], link["customdata"], strict=True
        )
    )


def node_facts(trace: dict[str, Any]) -> dict[str, tuple[str, list[str]]]:
    """Colour and hover of every node, by its label."""
    node = trace["node"]
    return {
        label: (node["color"][i], node["customdata"][i]) for i, label in enumerate(node["label"])
    }


def test_labels_colours_hover_and_links_stay_aligned_after_a_reorder() -> None:
    graph = budget()
    plain_trace = sankey_trace(build_figure(graph, style(), "light"))
    order = list(reversed(GRAPH_ORDER))
    trace = sankey_trace(build_figure(graph, style(node_order=order), "light"))
    assert trace["node"]["label"] == order
    assert node_facts(trace) == node_facts(plain_trace)  # colours follow the node, not its place
    assert named_links(trace) == named_links(plain_trace)
    assert trace["link"]["value"] == plain_trace["link"]["value"]  # the link order is unchanged


def test_the_values_in_the_labels_follow_their_nodes() -> None:
    graph = budget()
    order = ["Cash", "Salary"]
    trace = sankey_trace(
        build_figure(graph, style(node_order=order, show_values_in_labels=True), "light")
    )
    labels = trace["node"]["label"]
    assert labels[0].startswith("Cash")
    assert labels[0].endswith("500")
    assert labels[1].startswith("Salary")
    assert labels[1].endswith("5,000")


def test_the_figure_height_does_not_depend_on_the_order() -> None:
    graph = plain()
    flat = build_figure(graph, style(), "light")["layout"]["height"]
    ordered = build_figure(graph, style(node_order=list(reversed(graph.node_names))), "light")
    assert ordered["layout"]["height"] == flat


def test_a_stored_order_survives_a_cap_in_the_figure() -> None:
    figure = build_figure(
        budget(), style(node_order=["Housing", "Salary"]), "light", FigureOptions(max_links=2)
    )
    trace = sankey_trace(figure)
    assert trace["node"]["label"] == ["Housing", "Salary", "Budget"]
    assert trace["node"]["sort"] == "input"
    assert len(trace["link"]["value"]) == 2


# --------------------------------------------------------------------------- real Chrome

NODE_IN_SVG = re.compile(
    r'<g class="sankey-node" transform="translate\(([\d.]+),([\d.-]+)\)".*?'
    r'class="node-label"[^>]*>([^<]*)</text>',
    re.DOTALL,
)


def exported_positions(order: list[str]) -> dict[str, tuple[float, float]]:
    """``{label: (x, y)}`` of the node rectangles in the SVG that Chrome draws for ``order``."""
    figure = build_figure(budget(), style(node_order=order), "light")
    try:
        svg = export_image(figure, "svg", ImageOptions(width=900, height=500, scale=1.0))
    except ExportUnavailableError:
        pytest.skip("Chrome is not installed (kaleido needs it for SVG and PNG)")
    found = NODE_IN_SVG.finditer(svg.decode())
    return {m.group(3): (float(m.group(1)), float(m.group(2))) for m in found}


def stack(positions: dict[str, tuple[float, float]], names: list[str]) -> list[str]:
    """``names`` sorted from the top of the chart to the bottom."""
    return sorted(names, key=lambda name: positions[name][1])


@pytest.mark.slow
def test_kaleido_stacks_the_nodes_of_a_layer_in_the_stored_order() -> None:
    last_layer = ["Housing", "Food", "Transport", "Stocks", "Cash"]
    assert stack(exported_positions([]), last_layer) == last_layer  # data order
    wanted = ["Transport", "Food", "Housing", "Cash", "Stocks"]
    assert stack(exported_positions(wanted), last_layer) == wanted
