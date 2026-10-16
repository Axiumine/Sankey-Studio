# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""HTML and JSON exports of a figure dict.

Both go through ``plotly.io`` with ``validate=False``: it escapes ``</script>`` and adds no
template. The figure is never serialised with ``json.dumps`` and the title is always escaped.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any, Literal

import plotly.io

from sankey_studio.render.layout import FONT_FAMILY
from sankey_studio.render.palette import TOKENS

if TYPE_CHECKING:
    from sankey_studio.models import Theme

#: Browser-side options of the exported page (no logo; the chart follows the window).
PLOT_CONFIG = {"displaylogo": False, "responsive": True}


def export_json(figure: dict[str, Any]) -> str:
    """The figure as JSON text (``<`` and ``/`` escaped, safe inside a ``<script>`` block)."""
    out: str = plotly.io.to_json(figure, validate=False)
    return out


def export_html(
    figure: dict[str, Any],
    *,
    title: str,
    theme: Theme,
    include_plotlyjs: Literal["inline", "cdn"] = "inline",
) -> str:
    """A standalone page around the figure. ``inline`` embeds plotly.js (works offline)."""
    div: str = plotly.io.to_html(
        figure,
        config=PLOT_CONFIG,
        include_plotlyjs=True if include_plotlyjs == "inline" else "cdn",
        full_html=False,
        validate=False,
    )
    tokens = TOKENS[theme]
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>html, body {{ height: 100%; margin: 0; background: {tokens.surface}; "
        f"color: {tokens.ink}; font-family: {FONT_FAMILY}; }}</style>\n"
        f"</head>\n<body>\n{div}\n</body>\n</html>\n"
    )
