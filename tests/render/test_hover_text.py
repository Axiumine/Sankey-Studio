# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Hover templates: their literal text, and the sentence a hover shows for a known node and link.

The templates only hold ``%{customdata[i]}`` slots; this fills the slots the way plotly.js does,
so a swapped index or a mislabelled share would change the sentence the user reads.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from sankey_studio.render.sankey import LINK_HOVER, LINK_HOVER_CATEGORY, NODE_HOVER, build_figure
from tests.render.support import budget, plain, style

SLOT = re.compile(r"%\{customdata\[(\d+)\]\}")

TEMPLATES = [
    (
        NODE_HOVER,
        "%{customdata[0]}<br>In: %{customdata[1]}<br>Out: %{customdata[2]}<extra></extra>",
    ),
    (
        LINK_HOVER,
        (
            "%{customdata[0]} → %{customdata[1]}<br><b>%{customdata[2]}</b>"
            "<br>%{customdata[3]} of the source's outflow"
            "<br>%{customdata[4]} of the target's inflow<extra></extra>"
        ),
    ),
    (
        LINK_HOVER_CATEGORY,
        (
            "%{customdata[0]} → %{customdata[1]}<br><b>%{customdata[2]}</b>"
            "<br>%{customdata[3]} of the source's outflow"
            "<br>%{customdata[4]} of the target's inflow"
            "<br>Category: %{customdata[5]}<extra></extra>"
        ),
    ),
]


def fill(template: str, customdata: list[str]) -> str:
    """The text a hover label shows: every ``%{customdata[i]}`` replaced by its entry."""
    return SLOT.sub(lambda match: customdata[int(match.group(1))], template)


def sankey_trace(figure: dict[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = figure["data"][0]
    return trace


@pytest.mark.parametrize(("template", "literal"), TEMPLATES)
def test_the_template_text_is_pinned(template: str, literal: str) -> None:
    assert template == literal


def test_a_node_hover_names_the_node_then_its_inflow_then_its_outflow() -> None:
    graph = budget()
    node = sankey_trace(build_figure(graph, style(), "light"))["node"]
    row = node["customdata"][graph.node_names.index("Budget")]
    assert fill(node["hovertemplate"], row) == "Budget<br>In: 5,800<br>Out: 4,800<extra></extra>"


def test_a_link_hover_gives_the_shares_of_the_source_and_of_the_target() -> None:
    link = sankey_trace(build_figure(budget(), style(), "light"))["link"]
    assert fill(link["hovertemplate"], link["customdata"][0]) == (
        "Salary → Budget<br><b>5,000</b><br>100.0% of the source's outflow"
        "<br>86.2% of the target's inflow<br>Category: Income<extra></extra>"
    )
    assert fill(link["hovertemplate"], link["customdata"][1]) == (
        "Bonus → Budget<br><b>800</b><br>100.0% of the source's outflow"
        "<br>13.8% of the target's inflow<br>Category: Income<extra></extra>"
    )


def test_a_link_hover_of_an_uncategorised_link_says_so() -> None:
    graph = budget()
    link = sankey_trace(build_figure(graph, style(), "light"))["link"]
    row = link["customdata"][5]  # Budget -> Savings is the one link without a category
    assert row[:2] == ["Budget", "Savings"]
    assert fill(link["hovertemplate"], row).endswith(
        "<br>31.3% of the source's outflow<br>100.0% of the target's inflow"
        "<br>Category: Uncategorized<extra></extra>"
    )


def test_a_plain_graph_hover_has_no_category_line() -> None:
    link = sankey_trace(build_figure(plain(), style(value_suffix=" EUR"), "light"))["link"]
    assert fill(link["hovertemplate"], link["customdata"][0]) == (
        "Salary → Budget<br><b>5,000 EUR</b><br>100.0% of the source's outflow"
        "<br>86.2% of the target's inflow<extra></extra>"
    )
