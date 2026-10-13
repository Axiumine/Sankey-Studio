"""The Sankey figure, built by hand as a plain dict (no ``plotly`` import).

Plotly renders pseudo-HTML in labels and hover text, so every user-derived string goes through
``escape_label``; user text never enters a ``hovertemplate`` (it travels in ``customdata``). The
legend is drawn INSIDE the figure, so SVG, PNG and HTML exports contain it.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from sankey_studio.models.base import UNCATEGORIZED
from sankey_studio.render.layout import base_layout, font, margin, note_annotation
from sankey_studio.render.legend import legend_traces, scene_legend
from sankey_studio.render.palette import TOKENS
from sankey_studio.render.scene import link_colors, make_scene, node_color
from sankey_studio.render.text import escape_label, strip_unseen, truncate_label, value_text

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph, StyleSpec, Theme
    from sankey_studio.render.legend import LegendItem
    from sankey_studio.render.options import FigureOptions
    from sankey_studio.render.scene import Scene

#: Vertical room per node of the fullest layer, and the fixed part of the height.
ROW_PX = 22
HEIGHT_BASE = 48
#: With a legend row the Sankey leaves the top 8% of the plot area to it.
LEGEND_DOMAIN_TOP = 0.92
#: Separates the name of a node from its value in the label (the value goes on a line of its own).
LABEL_BREAK = "<br>"
NODE_HOVER = "%{customdata[0]}<br>In: %{customdata[1]}<br>Out: %{customdata[2]}<extra></extra>"
LINK_HOVER = (
    "%{customdata[0]} → %{customdata[1]}<br><b>%{customdata[2]}</b>"
    "<br>%{customdata[3]} of the source's outflow"
    "<br>%{customdata[4]} of the target's inflow<extra></extra>"
)
LINK_HOVER_CATEGORY = LINK_HOVER.replace("<extra>", "<br>Category: %{customdata[5]}<extra>")


def truncation_note(shown: int, total: int) -> str:
    """``Showing N of M links``: the text of the in-figure note and of the bundle warning."""
    return f"Showing {shown} of {total} links"


@lru_cache(maxsize=2048)
def percent_text(permille: int) -> str:
    """Thousandths as a percentage with one decimal (cached: links share their strings)."""
    return f"{permille / 10:.1f}%"


def _share(part: float, whole: float) -> str:
    return percent_text(int(part / whole * 1000 + 0.5) if whole > 0 else 0)


def node_block(scene: Scene) -> dict[str, Any]:
    """Labels (truncated, escaped), colours, outline and hover of the drawn nodes."""
    graph, style = scene.graph, scene.style
    surface = TOKENS[scene.theme].surface
    labels, hover = [], []
    for node in scene.drawn.nodes:
        name = graph.node_names[node]
        label = escape_label(truncate_label(strip_unseen(name)))
        if style.show_values_in_labels:
            label += LABEL_BREAK + value_text(max(graph.node_in[node], graph.node_out[node]), style)
        labels.append(label)
        hover.append(
            [
                escape_label(name),
                value_text(graph.node_in[node], style),
                value_text(graph.node_out[node], style),
            ]
        )
    return {
        "label": labels,
        "color": [node_color(scene, node) for node in scene.drawn.nodes],
        "pad": style.node_pad,
        "thickness": style.node_thickness,
        "line": {"color": surface, "width": 2},
        "customdata": hover,
        "hovertemplate": NODE_HOVER,
    }


def link_hover(scene: Scene, link: int) -> list[str]:
    """Full source and target name, value, share of source out, share of target in, category."""
    graph, style = scene.graph, scene.style
    source, target = graph.link_source[link], graph.link_target[link]
    value = graph.link_value[link]
    category = graph.link_category[link]
    return [
        escape_label(graph.node_names[source]),
        escape_label(graph.node_names[target]),
        value_text(value, style),
        _share(value, graph.node_out[source]),
        _share(value, graph.node_in[target]),
        UNCATEGORIZED if category < 0 else escape_label(graph.categories[category]),
    ]


def link_block(scene: Scene) -> dict[str, Any]:
    """Source, target, value, colour and hover per drawn link."""
    graph = scene.graph
    position = {node: index for index, node in enumerate(scene.drawn.nodes)}
    links = scene.drawn.links
    return {
        "source": [position[graph.link_source[link]] for link in links],
        "target": [position[graph.link_target[link]] for link in links],
        "value": [graph.link_value[link] for link in links],
        "color": link_colors(scene),
        "customdata": [link_hover(scene, link) for link in links],
        "hovertemplate": LINK_HOVER_CATEGORY if graph.has_categories else LINK_HOVER,
    }


def sankey_trace(scene: Scene, *, legend: bool) -> dict[str, Any]:
    """The ``sankey`` trace; its domain leaves room for the legend row when there is one."""
    style, tokens = scene.style, TOKENS[scene.theme]
    return {
        "type": "sankey",
        "orientation": style.orientation,
        "arrangement": style.arrangement,
        "valueformat": escape_label(style.value_format),
        "valuesuffix": escape_label(style.value_suffix),
        "textfont": font(tokens.ink, style.font_size),
        "hoverlabel": {
            "bgcolor": tokens.surface,
            "bordercolor": tokens.muted,
            "font": font(tokens.ink, style.font_size),
        },
        "domain": {"x": [0, 1], "y": [0, LEGEND_DOMAIN_TOP if legend else 1]},
        "node": node_block(scene),
        "link": link_block(scene),
    }


def figure_height(scene: Scene) -> int:
    """``max(style.height, 22 * nodes in the fullest layer + 48)``."""
    layers = Counter(scene.graph.node_layers[node] for node in scene.drawn.nodes)
    return max([scene.style.height, *(ROW_PX * count + HEIGHT_BASE for count in layers.values())])


def empty_annotation(style: StyleSpec, theme: Theme) -> dict[str, Any]:
    """Shown instead of a chart when no link is drawn."""
    return {
        "text": "No entries to draw",
        "xref": "paper",
        "yref": "paper",
        "x": 0.5,
        "y": 0.5,
        "showarrow": False,
        "font": font(TOKENS[theme].ink_secondary, style.font_size),
    }


def sankey_layout(scene: Scene, items: list[LegendItem]) -> dict[str, Any]:
    """Base layout plus height, margins, the horizontal legend, notes and empty state."""
    style, theme, drawn = scene.style, scene.theme, scene.drawn
    layout = base_layout(style, theme)
    notes = []
    if drawn.truncated:
        notes.append(
            note_annotation(truncation_note(len(drawn.links), drawn.total_links), style, theme)
        )
    if not drawn.links:
        notes.append(empty_annotation(style, theme))
    layout["height"] = figure_height(scene)
    layout["margin"] = margin(style, legend=bool(items), note=drawn.truncated)
    layout["annotations"] = notes
    layout["showlegend"] = bool(items)
    if items:
        layout["legend"] |= {
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": 1,
            "yanchor": "bottom",
            "itemclick": False,
            "itemdoubleclick": False,
        }
        layout["xaxis"] = {"visible": False}
        layout["yaxis"] = {"visible": False}
    return layout


def build_figure(
    graph: SankeyGraph, style: StyleSpec, theme: Theme, options: FigureOptions | None = None
) -> dict[str, Any]:
    """The Plotly figure (``{"data": [...], "layout": {...}}``) of ``graph``, JSON-serialisable."""
    scene = make_scene(graph, style, theme, options)
    items = scene_legend(scene)
    return {
        "data": [sankey_trace(scene, legend=bool(items)), *legend_traces(items)],
        "layout": sankey_layout(scene, items),
    }
