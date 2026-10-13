"""The donut figure (value per category), built by hand as a plain dict (no ``plotly`` import)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sankey_studio.errors import NoCategoriesError
from sankey_studio.render.colors import ColorMap
from sankey_studio.render.donut_fold import NO_CATEGORIES_TEXT, category_totals, donut_slices
from sankey_studio.render.layout import base_layout, font, margin
from sankey_studio.render.palette import OTHER_COLOR, TOKENS, UNCATEGORIZED_COLOR
from sankey_studio.render.text import escape_label, value_text

if TYPE_CHECKING:
    from sankey_studio.models import DonutStyle, SankeyGraph, StyleSpec, Theme
    from sankey_studio.render.donut_fold import DonutSlice
    from sankey_studio.render.options import FigureOptions

__all__ = ["build_donut_figure", "category_totals", "slice_color", "total_font_size"]

#: Figure height and the share of it the pie itself uses (labels and the legend take the rest).
DONUT_HEIGHT = 460
PLOT_FRACTION = 0.7
#: Direct labels only up to this many slices, then the legend and the hover carry the names.
DIRECT_LABEL_MAX = 4
MIN_TOTAL_FONT = 14
MAX_TOTAL_FONT = 40
#: Width of one digit as a fraction of the font size, with room to spare.
TOTAL_FONT_RATIO = 1.5
EMPTY_TEXT = "No categorised entries for this basis"


def total_font_size(hole: float, chars: int) -> int:
    """Font size (px) for the centre total: fits ``chars`` characters into the hole, min 14."""
    diameter = DONUT_HEIGHT * PLOT_FRACTION * hole
    fitted = int(TOTAL_FONT_RATIO * diameter / max(chars, 1))
    return max(MIN_TOTAL_FONT, min(fitted, MAX_TOTAL_FONT))


def slice_color(slice_: DonutSlice, theme: Theme, colors: ColorMap) -> str:
    """Own hue for a category, muted neutral for ``Uncategorized``, secondary ink for ``Other``."""
    if slice_.kind == "category":
        return colors.category_color(slice_.name, theme)
    if slice_.kind == "uncategorized":
        return UNCATEGORIZED_COLOR
    return OTHER_COLOR[theme]


def pattern_block(slices: list[DonutSlice], palette: list[str], theme: Theme) -> dict[str, Any]:
    """Solid fills, except ``Other``: 45 degree lines, so it differs from adjacent neutrals."""
    surface = TOKENS[theme].surface
    other = [s.kind == "other" for s in slices]
    return {
        "shape": ["/" if is_other else "" for is_other in other],
        "bgcolor": [palette[i] if not is_other else surface for i, is_other in enumerate(other)],
        "fgcolor": palette,
        "size": 6,
        "solidity": 0.4,
    }


#: Plotly's own order of the flags in ``textinfo`` (the order is meaningless there).
TEXT_INFO_ORDER = ("label", "text", "percent")


def text_parts(donut: DonutStyle, *, direct: bool) -> list[str]:
    """What a slice prints, in print order: the name (few slices only), the percentage, the value.

    The order is the one of the switches in the viewer menu and of the editor checkboxes. ``text``
    is the slice value formatted by ``value_text`` (the ``text`` array of the trace).
    """
    parts = ["label"] if direct else []
    if donut.show_percent:
        parts.append("percent")
    if donut.show_value:
        parts.append("text")
    return parts


def text_info(donut: DonutStyle, *, direct: bool) -> str:
    """Plotly ``textinfo`` of a slice: the flags of ``text_parts`` (``none`` when empty)."""
    parts = text_parts(donut, direct=direct)
    return "+".join(sorted(parts, key=TEXT_INFO_ORDER.index)) or "none"


def slice_text(donut: DonutStyle, formatted: list[str], *, direct: bool) -> dict[str, Any]:
    """The text keys of the ``pie`` trace: what a slice prints, where, and in which order.

    ``textinfo`` says what, ``texttemplate`` (it wins in Plotly) says in which order: Plotly itself
    would print the value before the percentage. Fixed strings only; user text stays in
    ``labels`` and ``text``.
    """
    parts = text_parts(donut, direct=direct)
    block: dict[str, Any] = {
        "textinfo": text_info(donut, direct=direct),
        "textposition": "outside" if direct else ("auto" if parts else "none"),
    }
    if parts:
        block["texttemplate"] = "<br>".join(f"%{{{part}}}" for part in parts)
    if donut.show_value:
        block["text"] = formatted
    return block


def pie_trace(
    slices: list[DonutSlice], style: StyleSpec, theme: Theme, colors: ColorMap
) -> dict[str, Any]:
    """The ``pie`` trace: 2px surface gaps, ink text, the name on a slice for a few slices only.

    Percentage and value go on every slice when asked for (``DonutStyle.show_percent`` and
    ``show_value``); beyond ``DIRECT_LABEL_MAX`` slices they appear without the name, which the
    legend and the hover carry.
    """
    tokens, donut = TOKENS[theme], style.donut
    palette = [slice_color(s, theme, colors) for s in slices]
    direct = len(slices) <= DIRECT_LABEL_MAX
    text_font = font(tokens.ink, style.font_size)
    formatted = [value_text(s.value, style) for s in slices]
    return {
        "type": "pie",
        "labels": [escape_label(s.name) for s in slices],
        "values": [s.value for s in slices],
        "customdata": [[text] for text in formatted],
        "hovertemplate": "%{label}<br>%{customdata[0]} (%{percent})<extra></extra>",
        "hole": donut.hole,
        "direction": "clockwise",
        "sort": False,
        "marker": {
            "colors": palette,
            "line": {"color": tokens.surface, "width": 2},
            "pattern": pattern_block(slices, palette, theme),
        },
        **slice_text(donut, formatted, direct=direct),
        "textfont": text_font,
        "insidetextfont": text_font,
        "outsidetextfont": text_font,
        "showlegend": True,
        "automargin": True,
    }


def total_annotation(slices: list[DonutSlice], style: StyleSpec, theme: Theme) -> dict[str, Any]:
    """The total in the hole, sized to fit it."""
    text = value_text(sum(s.value for s in slices), style)
    size = total_font_size(style.donut.hole, len(text))
    return {
        "text": text,
        "xref": "paper",
        "yref": "paper",
        "x": 0.5,
        "y": 0.5,
        "showarrow": False,
        "font": font(TOKENS[theme].ink, size),
    }


def empty_annotation(style: StyleSpec, theme: Theme) -> dict[str, Any]:
    return {
        "text": EMPTY_TEXT,
        "xref": "paper",
        "yref": "paper",
        "x": 0.5,
        "y": 0.5,
        "showarrow": False,
        "font": font(TOKENS[theme].ink_secondary, style.font_size),
    }


def build_donut_figure(
    graph: SankeyGraph, style: StyleSpec, theme: Theme, options: FigureOptions | None = None
) -> dict[str, Any]:
    """The donut of ``graph`` for ``style.donut``; ``options.colors`` is the compare-view map.

    Raises ``NoCategoriesError`` when no drawn entry has a category. When categories exist but
    the basis selects none of them, the figure holds only the empty-state annotation.
    """
    if not graph.has_categories:
        raise NoCategoriesError(NO_CATEGORIES_TEXT)
    colors = (options.colors if options else None) or ColorMap.for_graph(graph, style)
    slices = donut_slices(graph, style, colors)
    layout = base_layout(style, theme)
    layout["height"] = DONUT_HEIGHT
    layout["margin"] = margin(style)
    layout["showlegend"] = bool(slices)
    layout["annotations"] = []
    if not slices:
        layout["annotations"].append(empty_annotation(style, theme))
        layout["xaxis"] = {"visible": False}
        layout["yaxis"] = {"visible": False}
        return {"data": [], "layout": layout}
    if style.donut.show_total:
        layout["annotations"].append(total_annotation(slices, style, theme))
    return {"data": [pie_trace(slices, style, theme, colors)], "layout": layout}
