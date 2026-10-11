"""What is drawn and in which colour: the shared base of the Sankey figure and its legend.

A ``Scene`` is built once per figure. The legend items shown on the page and the legend traces
inside the figure are derived from the same scene, so they cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sankey_studio.render.colors import ColorMap, to_rgba
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.palette import MONO_COLOR, NODE_NEUTRAL, UNCATEGORIZED_COLOR, layer_color

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph, StyleSpec, Theme


@dataclass(frozen=True, slots=True)
class Drawn:
    """The links and nodes that are drawn (all of them unless ``max_links`` cut the graph)."""

    links: list[int]
    nodes: list[int]
    total_links: int

    @property
    def truncated(self) -> bool:
        return len(self.links) < self.total_links


def select_drawn(graph: SankeyGraph, max_links: int | None) -> Drawn:
    """Top-``max_links`` links by value (ties: first link first), in original order.

    Nodes left without a drawn link are dropped.
    """
    links = list(range(graph.n_links))
    if max_links is not None:
        largest_first = sorted(links, key=lambda i: -graph.link_value[i])
        links = sorted(largest_first[: max(max_links, 0)])
    nodes = sorted(
        {graph.link_source[link] for link in links} | {graph.link_target[link] for link in links}
    )
    return Drawn(links=links, nodes=nodes, total_links=graph.n_links)


def effective_mode(graph: SankeyGraph, style: StyleSpec, drawn: Drawn) -> str:
    """``category`` colouring needs a categorised drawn link; without one it is plain ``node``."""
    if style.color_mode != "category":
        return style.color_mode
    if any(graph.link_category[link] >= 0 for link in drawn.links):
        return "category"
    return "node"


@dataclass(frozen=True, slots=True)
class Scene:
    """A graph, its style and theme, the colour maps and the drawn subset."""

    graph: SankeyGraph
    style: StyleSpec
    theme: Theme
    node_map: ColorMap
    category_map: ColorMap
    drawn: Drawn
    mode: str


def make_scene(
    graph: SankeyGraph, style: StyleSpec, theme: Theme, options: FigureOptions | None
) -> Scene:
    options = options or FigureOptions()
    node_map = ColorMap.for_graph(graph, style)
    drawn = select_drawn(graph, options.max_links)
    return Scene(
        graph=graph,
        style=style,
        theme=theme,
        node_map=node_map,
        category_map=options.colors or node_map,
        drawn=drawn,
        mode=effective_mode(graph, style, drawn),
    )


def node_color(scene: Scene, node: int) -> str:
    """Colour of graph node ``node`` per the effective colour mode."""
    if scene.mode == "layer":
        return layer_color(scene.theme, scene.graph.node_layers[node])
    if scene.mode == "mono":
        return MONO_COLOR[scene.theme]
    if scene.mode == "category":
        return NODE_NEUTRAL
    return scene.node_map.node_color(scene.graph.node_names[node], scene.theme)


def link_colors(scene: Scene) -> list[str]:
    """``rgba`` colour per drawn link: the source node's colour, or the category's colour."""
    graph, theme = scene.graph, scene.theme
    category_base = [scene.category_map.category_color(name, theme) for name in graph.categories]
    node_base = {node: node_color(scene, node) for node in scene.drawn.nodes}
    opacity = scene.style.link_opacity
    colors: list[str] = []
    for link in scene.drawn.links:
        category = graph.link_category[link]
        if scene.mode != "category":
            base = node_base[graph.link_source[link]]
        else:
            base = UNCATEGORIZED_COLOR if category < 0 else category_base[category]
        colors.append(to_rgba(base, opacity))
    return colors
