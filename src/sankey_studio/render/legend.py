"""Legend items (the same list feeds the page and the in-figure legend traces)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sankey_studio.models.base import OTHER, UNCATEGORIZED
from sankey_studio.render.palette import LAYER_RAMP, OTHER_COLOR, UNCATEGORIZED_COLOR
from sankey_studio.render.scene import make_scene
from sankey_studio.render.text import escape_label

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph, StyleSpec, Theme
    from sankey_studio.render.options import FigureOptions
    from sankey_studio.render.scene import Scene

LegendKind = Literal["category", "layer", "node"]


@dataclass(frozen=True, slots=True)
class LegendItem:
    """One legend entry; ``value`` is the drawn flow of a category (``None`` for layers)."""

    label: str
    color: str
    kind: LegendKind
    value: float | None = None


def category_items(scene: Scene) -> list[LegendItem]:
    """Real categories with a hue on a drawn link, then ``Other`` and ``Uncategorized``.

    ``Other`` stands for drawn categories WITHOUT a hue (decided by ``has_hue``); it is absent
    when every drawn category has one.
    """
    graph, theme, colors = scene.graph, scene.theme, scene.category_map
    sums: dict[int, float] = {}
    for link in scene.drawn.links:
        category = graph.link_category[link]
        sums[category] = sums.get(category, 0.0) + graph.link_value[link]
    items: list[LegendItem] = []
    hueless: list[float] = []
    for category in sorted(c for c in sums if c >= 0):
        name = graph.categories[category]
        if colors.has_hue(name):
            color = colors.category_color(name, theme)
            items.append(LegendItem(name, color, "category", sums[category]))
        else:
            hueless.append(sums[category])
    if hueless:
        items.append(LegendItem(OTHER, OTHER_COLOR[theme], "category", sum(hueless)))
    if -1 in sums:
        items.append(LegendItem(UNCATEGORIZED, UNCATEGORIZED_COLOR, "category", sums[-1]))
    return items


def layer_items(scene: Scene) -> list[LegendItem]:
    """The ramp steps in use: ``Layer 1`` ... ``Layer K`` (``Layers K+`` when deeper)."""
    ramp = LAYER_RAMP[scene.theme]
    depth = 1 + max(scene.graph.node_layers[node] for node in scene.drawn.nodes)
    steps = len(ramp)
    items = []
    for index in range(min(depth, steps)):
        label = f"Layer {index + 1}"
        if index == steps - 1 and depth > steps:
            label = f"Layers {steps}+"
        items.append(LegendItem(label, ramp[index], "layer"))
    return items


def scene_legend(scene: Scene) -> list[LegendItem]:
    """Legend items of a scene: categories, layers, or none (``node`` / ``mono``)."""
    if scene.mode == "category":
        return category_items(scene)
    if scene.mode == "layer" and scene.drawn.nodes:
        return layer_items(scene)
    return []


def legend_items(
    graph: SankeyGraph, style: StyleSpec, theme: Theme, options: FigureOptions | None = None
) -> list[LegendItem]:
    """The legend of ``build_figure(graph, style, theme, options)``."""
    return scene_legend(make_scene(graph, style, theme, options))


def legend_traces(items: list[LegendItem]) -> list[dict[str, Any]]:
    """One empty scatter trace per item: a coloured square and the (escaped) label."""
    return [
        {
            "type": "scatter",
            "x": [None],
            "y": [None],
            "mode": "markers",
            "name": escape_label(item.label),
            "showlegend": True,
            "hoverinfo": "skip",
            "marker": {"symbol": "square", "size": 10, "color": item.color},
        }
        for item in items
    ]
