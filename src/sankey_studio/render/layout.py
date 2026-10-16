# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Layout pieces shared by the Sankey and the donut: fonts, surfaces, hover, modebar, title.

Everything is set explicitly (no plotly template): the browser and the kaleido export must look
identical, in both themes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sankey_studio.render.palette import TOKENS
from sankey_studio.render.text import escape_label

if TYPE_CHECKING:
    from sankey_studio.models import StyleSpec, Theme

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'
TRANSPARENT = "rgba(0, 0, 0, 0)"
#: Page margins and the extra bands that hold the title, the legend row and the note.
MARGIN = 16
TITLE_BAND = 36
LEGEND_BAND = 40
NOTE_BAND = 28


def font(color: str, size: int) -> dict[str, Any]:
    return {"family": FONT_FAMILY, "size": size, "color": color}


def margin(style: StyleSpec, *, legend: bool = False, note: bool = False) -> dict[str, int]:
    """Top margin makes room for the title and the legend row, bottom for the note."""
    top = MARGIN + (TITLE_BAND if style.title else 0) + (LEGEND_BAND if legend else 0)
    return {"l": MARGIN, "r": MARGIN, "t": top, "b": MARGIN + (NOTE_BAND if note else 0)}


def title_block(title: str, style: StyleSpec, theme: Theme) -> dict[str, Any]:
    """The chart title (escaped), top left of the container."""
    tokens = TOKENS[theme]
    return {
        "text": escape_label(title),
        "font": font(tokens.ink, style.font_size + 3),
        "x": 0,
        "xref": "container",
        "xanchor": "left",
        "y": 1,
        "yref": "container",
        "yanchor": "top",
        "pad": {"l": MARGIN, "t": MARGIN},
    }


def base_layout(style: StyleSpec, theme: Theme) -> dict[str, Any]:
    """Fonts, surfaces, hover label, modebar and (when set) the title."""
    tokens = TOKENS[theme]
    layout: dict[str, Any] = {
        "autosize": True,
        "font": font(tokens.ink, style.font_size),
        "paper_bgcolor": tokens.surface,
        "plot_bgcolor": tokens.surface,
        "hoverlabel": {
            "bgcolor": tokens.surface,
            "bordercolor": tokens.muted,
            "font": font(tokens.ink, style.font_size),
        },
        "modebar": {"bgcolor": TRANSPARENT, "color": tokens.muted, "activecolor": tokens.ink},
        "legend": {"font": font(tokens.ink, style.font_size), "bgcolor": TRANSPARENT},
    }
    if style.title:
        layout["title"] = title_block(style.title, style, theme)
    return layout


def note_annotation(text: str, style: StyleSpec, theme: Theme) -> dict[str, Any]:
    """A small secondary-ink note under the plot, bottom right (``Showing N of M links``)."""
    return {
        "text": escape_label(text),
        "xref": "paper",
        "yref": "paper",
        "x": 1,
        "y": 0,
        "xanchor": "right",
        "yanchor": "top",
        "showarrow": False,
        "font": font(TOKENS[theme].ink_secondary, max(style.font_size - 1, 8)),
    }
