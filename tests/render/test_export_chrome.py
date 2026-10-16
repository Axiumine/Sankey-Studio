# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Real Chrome exports (slow; skipped when Chrome is not available)."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from sankey_studio.errors import ExportUnavailableError
from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.export import export_image
from sankey_studio.render.options import ImageFormat, ImageOptions
from sankey_studio.render.sankey import build_figure
from tests.graph_support import make_graph
from tests.render.support import budget, style

pytestmark = pytest.mark.slow

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
HOSTILE = "R&D <a href=https://evil.example>pay</a>"


def render(figure: dict[str, Any], fmt: ImageFormat, options: ImageOptions) -> bytes:
    try:
        return export_image(figure, fmt, options)
    except ExportUnavailableError:
        pytest.skip("Chrome is not installed (kaleido needs it for SVG and PNG)")


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(PNG_MAGIC)
    assert data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def test_sankey_svg_contains_the_chart_and_the_legend() -> None:
    figure = build_figure(budget(), style(color_mode="category"), "light")
    svg = render(figure, "svg", ImageOptions(width=900, height=500, scale=1.0))
    assert svg.startswith(b"<svg")
    text = svg.decode()
    for label in ("Salary", "Housing", "Income", "Uncategorized"):
        assert label in text


def test_sankey_png_has_the_requested_dimensions() -> None:
    figure = build_figure(budget(), style(), "dark")
    assert png_size(render(figure, "png", ImageOptions(width=600, height=400, scale=1.0))) == (
        600,
        400,
    )
    assert png_size(render(figure, "png", ImageOptions(width=500, height=300, scale=2.0))) == (
        1000,
        600,
    )


def test_transparent_png_is_a_png_with_alpha() -> None:
    figure = build_figure(budget(), style(), "light")
    data = render(figure, "png", ImageOptions(width=400, height=300, scale=1.0, transparent=True))
    assert png_size(data) == (400, 300)
    assert data[25] == 6  # colour type 6: RGBA


def test_donut_exports_to_svg_and_png() -> None:
    figure = build_donut_figure(budget(), style(donut={"max_slices": 2}), "light")
    svg = render(figure, "svg", ImageOptions(width=700, height=450, scale=1.0))
    assert svg.startswith(b"<svg")
    assert b"12,100" in svg
    assert png_size(render(figure, "png", ImageOptions(width=700, height=450, scale=1.0))) == (
        700,
        450,
    )


def test_hostile_names_render_as_text_with_no_anchor_in_the_svg() -> None:
    graph = make_graph(
        [
            (HOSTILE, "a<b>bold</b>", 5.0, "x</script><script>alert(1)</script>"),
            ("a<b>bold</b>", "%{value}", 2.0, "&lt;"),
        ]
    )
    figure = build_figure(graph, style(title=HOSTILE, color_mode="category"), "light")
    text = render(figure, "svg", ImageOptions(width=900, height=500, scale=1.0)).decode()
    assert "R&amp;D &#60;a href=https://evil.example&#62;pay&#60;/a&#62;" in text
    assert "<a " not in text
    assert "<a>" not in text
    assert "xlink:href" not in text
    assert "<script" not in text
    assert "%{value}" in text
