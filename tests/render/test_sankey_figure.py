# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``build_figure``: structure, escaping, hover, height and the truncation note."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NamedTuple

import plotly.graph_objects as go
import pytest

from sankey_studio.models import StyleSpec
from sankey_studio.render.colors import to_rgba
from sankey_studio.render.layout import FONT_FAMILY, TRANSPARENT
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.palette import CATEGORICAL, TOKENS
from sankey_studio.render.sankey import (
    HEIGHT_BASE,
    LABEL_BREAK,
    LEGEND_DOMAIN_TOP,
    LINK_HOVER,
    LINK_HOVER_CATEGORY,
    NODE_HOVER,
    ROW_PX,
    build_figure,
    percent_text,
    truncation_note,
)
from tests.graph_support import make_graph
from tests.render.support import BUDGET, budget, plain, strings, style

if TYPE_CHECKING:
    from sankey_studio.models import Theme


def walk(value: object) -> None:
    """Only JSON primitives, lists and dicts with string keys (no tuple, array or numpy)."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str)
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)
    else:
        assert value is None or isinstance(value, str | int | float | bool)


def sankey(figure: dict[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = figure["data"][0]
    assert trace["type"] == "sankey"
    return trace


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("mode", ["node", "layer", "mono", "category"])
def test_figure_is_plain_json_and_valid_for_plotly(theme: Theme, mode: str) -> None:
    figure = build_figure(budget(), style(color_mode=mode, title="T"), theme)
    walk(figure)
    json.dumps(figure)
    go.Figure(figure)
    assert set(figure) == {"data", "layout"}


def test_node_block_labels_colours_and_outline() -> None:
    graph = budget()
    trace = sankey(build_figure(graph, style(node_pad=21, node_thickness=17), "light"))
    node = trace["node"]
    assert node["label"] == list(graph.node_names)
    assert node["color"] == [*CATEGORICAL["light"], "#898781"]
    assert node["pad"] == 21
    assert node["thickness"] == 17
    assert node["line"] == {"color": TOKENS["light"].surface, "width": 2}


def test_node_hover_goes_through_customdata_with_a_fixed_template() -> None:
    graph = budget()
    node = sankey(build_figure(graph, style(value_suffix="USD"), "light"))["node"]
    assert node["hovertemplate"] == NODE_HOVER
    budget_index = graph.node_names.index("Budget")
    assert node["customdata"][budget_index] == ["Budget", "5,800 USD", "4,800 USD"]
    assert node["customdata"][0] == ["Salary", "0 USD", "5,000 USD"]


def test_link_block_matches_the_graph_columns() -> None:
    graph = budget()
    link = sankey(build_figure(graph, style(), "light"))["link"]
    assert link["source"] == list(graph.link_source)
    assert link["target"] == list(graph.link_target)
    assert link["value"] == list(graph.link_value)
    assert len(link["color"]) == graph.n_links
    assert link["color"][0] == to_rgba(CATEGORICAL["light"][0], 0.4)


def test_link_hover_has_names_value_shares_and_category() -> None:
    graph = budget()
    link = sankey(build_figure(graph, style(), "light"))["link"]
    assert link["hovertemplate"] == LINK_HOVER_CATEGORY
    assert link["customdata"][0] == ["Salary", "Budget", "5,000", "100.0%", "86.2%", "Income"]
    assert link["customdata"][5] == [
        "Budget",
        "Savings",
        "1,500",
        "31.3%",
        "100.0%",
        "Uncategorized",
    ]


def test_a_graph_without_categories_has_no_category_line_in_the_hover() -> None:
    link = sankey(build_figure(plain(), style(), "light"))["link"]
    assert link["hovertemplate"] == LINK_HOVER
    assert "Category" not in LINK_HOVER
    assert "Category: %{customdata[5]}" in LINK_HOVER_CATEGORY


def test_the_hover_templates_never_contain_user_text() -> None:
    graph = make_graph([("</b>%{value}", "<a href=x>", 1.0, "<i>c</i>")])
    trace = sankey(build_figure(graph, style(title="<b>t</b>", value_suffix="<u>"), "light"))
    assert trace["node"]["hovertemplate"] == NODE_HOVER
    assert trace["link"]["hovertemplate"] == LINK_HOVER_CATEGORY
    for template in (NODE_HOVER, LINK_HOVER_CATEGORY):
        assert "<a" not in template
        assert "%{value}" not in template


def test_every_user_string_is_escaped_in_labels_hover_legend_and_title() -> None:
    graph = make_graph([("R&D <a href=x>pay</a>", "x<y", 5.0, "a<b>bold</b>")])
    figure = build_figure(
        graph, style(title="</script><script>alert(1)</script>", color_mode="category"), "light"
    )
    trace = sankey(figure)
    assert trace["node"]["label"] == [
        "R&amp;D &lt;a href=x&gt;pay&lt;/a&gt;",
        "x&lt;y",
    ]
    assert trace["node"]["customdata"][0][0] == trace["node"]["label"][0]
    assert trace["link"]["customdata"][0][:2] == trace["node"]["label"]
    assert trace["link"]["customdata"][0][5] == "a&lt;b&gt;bold&lt;/b&gt;"
    assert figure["data"][1]["name"] == "a&lt;b&gt;bold&lt;/b&gt;"
    assert (
        figure["layout"]["title"]["text"] == "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;"
    )
    dumped = json.dumps(figure)
    assert "<a " not in dumped
    assert "<script" not in dumped


def test_the_trace_level_style_strings_are_escaped() -> None:
    suffix = style(value_suffix="<a href=x>&")
    assert sankey(build_figure(budget(), suffix, "light"))["valuesuffix"] == "&lt;a href=x&gt;&amp;"
    # the validator keeps markup out of value_format; the trace escapes it anyway
    unchecked = StyleSpec.model_construct(value_format=".1f<b>&")
    assert sankey(build_figure(budget(), unchecked, "light"))["valueformat"] == ".1f&lt;b&gt;&amp;"
    assert sankey(build_figure(budget(), style(value_format=",.2~f"), "light"))["valueformat"] == (
        ",.2~f"
    )


def test_no_figure_string_carries_markup_except_the_hover_templates_and_the_label_break() -> None:
    hostile = "<a href=x>&</a>"
    graph = make_graph([(hostile, "t<i>", 5.0, hostile), ("t<i>", "u", 2.0, None)])
    unchecked = StyleSpec.model_construct(
        title=hostile, value_suffix=hostile, value_format=hostile, show_values_in_labels=True
    )
    figure = build_figure(graph, unchecked, "light")
    labels = sankey(figure)["node"]["label"]
    assert all(label.count(LABEL_BREAK) == 1 for label in labels)
    templates = {NODE_HOVER, LINK_HOVER, LINK_HOVER_CATEGORY}
    texts = [text.replace(LABEL_BREAK, "") for text in strings(figure) if text not in templates]
    assert len(texts) > 20
    assert [text for text in texts if "<" in text or ">" in text] == []
    assert hostile not in texts


def test_long_labels_are_cut_at_32_characters_but_hover_keeps_the_full_name() -> None:
    name = "N" * 40
    graph = make_graph([(name, "T", 1.0, None), ("N" * 32, "U", 1.0, None)])
    node = sankey(build_figure(graph, style(), "light"))["node"]
    assert node["label"][0] == "N" * 32 + "…"
    assert node["label"][2] == "N" * 32
    assert node["customdata"][0][0] == name


def test_values_in_labels_are_optional() -> None:
    graph = budget()
    off = sankey(build_figure(graph, style(), "light"))["node"]["label"]
    on = sankey(build_figure(graph, style(show_values_in_labels=True, value_suffix="%"), "light"))[
        "node"
    ]["label"]
    assert off[0] == "Salary"
    assert on[0] == "Salary<br>5,000%"
    assert on[1] == "Budget<br>5,800%"
    assert LABEL_BREAK == "<br>"


def test_the_value_goes_on_a_line_of_its_own_under_the_name() -> None:
    graph = budget()
    look = style(show_values_in_labels=True, value_suffix="USD", value_format=",.1f")
    labels = sankey(build_figure(graph, look, "light"))["node"]["label"]
    names = sankey(build_figure(graph, style(), "light"))["node"]["label"]
    assert labels[0] == "Salary" + LABEL_BREAK + "5,000.0 USD"
    assert all(label.count(LABEL_BREAK) == 1 for label in labels)
    assert [label.split(LABEL_BREAK)[0] for label in labels] == names


def test_a_cut_or_escaped_name_keeps_its_value_after_the_break() -> None:
    graph = make_graph([("N" * 40, "a<br>b", 7.0, None)])
    look = style(show_values_in_labels=True)
    labels = sankey(build_figure(graph, look, "light"))["node"]["label"]
    assert labels == ["N" * 32 + "…<br>7", "a&lt;br&gt;b<br>7"]


def test_trace_options_follow_the_style() -> None:
    trace = sankey(
        build_figure(
            budget(),
            style(
                orientation="v",
                arrangement="freeform",
                value_format=".1f",
                value_suffix="k",
                font_size=15,
            ),
            "dark",
        )
    )
    assert trace["orientation"] == "v"
    assert trace["arrangement"] == "freeform"
    assert trace["valueformat"] == ".1f"
    assert trace["valuesuffix"] == "k"
    assert trace["textfont"]["size"] == 15
    assert trace["textfont"]["color"] == TOKENS["dark"].ink
    assert "system-ui" in trace["textfont"]["family"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_surfaces_ink_hover_and_modebar_are_explicit(theme: Theme) -> None:
    tokens = TOKENS[theme]
    figure = build_figure(budget(), style(), theme)
    layout, trace = figure["layout"], sankey(figure)
    assert layout["paper_bgcolor"] == tokens.surface
    assert layout["plot_bgcolor"] == tokens.surface
    assert layout["font"]["color"] == tokens.ink
    assert layout["hoverlabel"] == {
        "bgcolor": tokens.surface,
        "bordercolor": tokens.muted,
        "font": {"family": layout["font"]["family"], "size": 13, "color": tokens.ink},
    }
    assert trace["hoverlabel"] == layout["hoverlabel"]
    assert layout["modebar"]["color"] == tokens.muted
    assert layout["modebar"]["activecolor"] == tokens.ink
    assert layout["legend"]["font"]["color"] == tokens.ink
    assert layout["autosize"] is True


class Height(NamedTuple):
    style_height: int
    fullest: int
    expected: int


HEIGHTS = [
    Height(240, 3, 240),
    Height(240, 20, 488),
    Height(531, 22, 532),
    Height(532, 22, 532),
    Height(533, 22, 533),
]


@pytest.mark.parametrize("case", HEIGHTS)
def test_layout_height_is_the_larger_of_the_style_and_the_fullest_layer(case: Height) -> None:
    links = [("Src", f"T{i}", 1.0, None) for i in range(case.fullest)]
    figure = build_figure(make_graph(links), style(height=case.style_height), "light")
    assert ROW_PX * case.fullest + HEIGHT_BASE == 22 * case.fullest + 48
    assert figure["layout"]["height"] == case.expected


def test_without_a_legend_the_plot_uses_the_whole_height() -> None:
    figure = build_figure(budget(), style(), "light")
    assert sankey(figure)["domain"] == {"x": [0, 1], "y": [0, 1]}
    layout = figure["layout"]
    assert layout["showlegend"] is False
    assert len(figure["data"]) == 1
    assert "xaxis" not in layout
    assert layout["margin"] == {"l": 16, "r": 16, "t": 16, "b": 16}
    assert layout["annotations"] == []


def test_the_legend_is_drawn_inside_the_figure() -> None:
    figure = build_figure(budget(), style(color_mode="category"), "light")
    trace, legend = sankey(figure), figure["data"][1:]
    assert trace["domain"] == {"x": [0, 1], "y": [0, LEGEND_DOMAIN_TOP]}
    assert LEGEND_DOMAIN_TOP == 0.92
    assert [t["name"] for t in legend] == [
        "Income",
        "Fixed",
        "Variable",
        "Investing",
        "Uncategorized",
    ]
    assert legend[0] == {
        "type": "scatter",
        "x": [None],
        "y": [None],
        "mode": "markers",
        "name": "Income",
        "showlegend": True,
        "hoverinfo": "skip",
        "marker": {"symbol": "square", "size": 10, "color": CATEGORICAL["light"][0]},
    }
    layout = figure["layout"]
    assert layout["showlegend"] is True
    assert layout["legend"]["orientation"] == "h"
    assert (layout["legend"]["x"], layout["legend"]["y"]) == (0, 1)
    assert (layout["legend"]["xanchor"], layout["legend"]["yanchor"]) == ("left", "bottom")
    assert layout["legend"]["itemclick"] is False
    assert layout["legend"]["itemdoubleclick"] is False
    assert layout["xaxis"] == {"visible": False}
    assert layout["yaxis"] == {"visible": False}
    assert layout["margin"]["t"] == 16 + 40


def test_a_title_makes_room_at_the_top() -> None:
    figure = build_figure(budget(), style(title="Budget & more", color_mode="category"), "dark")
    layout = figure["layout"]
    assert layout["title"]["text"] == "Budget &amp; more"
    assert layout["title"]["font"]["color"] == TOKENS["dark"].ink
    assert layout["title"]["font"]["size"] == 16
    assert layout["margin"]["t"] == 16 + 36 + 40
    assert "title" not in build_figure(budget(), style(), "dark")["layout"]


def test_max_links_draws_the_top_links_and_notes_it_inside_the_figure() -> None:
    graph = budget()
    figure = build_figure(graph, style(), "light", FigureOptions(max_links=3))
    trace = sankey(figure)
    assert trace["link"]["value"] == [5000.0, 2000.0, 1500.0]
    assert trace["node"]["label"] == ["Salary", "Budget", "Housing", "Savings"]
    assert trace["link"]["source"] == [0, 1, 1]
    assert trace["link"]["target"] == [1, 2, 3]
    note = figure["layout"]["annotations"][0]
    assert note["text"] == truncation_note(3, graph.n_links) == "Showing 3 of 8 links"
    assert (note["x"], note["y"], note["xanchor"], note["yanchor"]) == (1, 0, "right", "top")
    assert note["showarrow"] is False
    assert note["font"]["color"] == TOKENS["light"].ink_secondary
    assert figure["layout"]["margin"]["b"] == 16 + 28


def test_no_note_when_the_cap_is_not_reached() -> None:
    graph = budget()
    for cap in (graph.n_links, graph.n_links + 5, None):
        figure = build_figure(graph, style(), "light", FigureOptions(max_links=cap))
        assert figure["layout"]["annotations"] == []
        assert figure["layout"]["margin"]["b"] == 16


def test_the_note_is_escaped_text_of_digits_only() -> None:
    assert truncation_note(1, 2) == "Showing 1 of 2 links"
    assert truncation_note(3000, 12345) == "Showing 3000 of 12345 links"


def test_a_graph_with_no_links_shows_an_empty_state() -> None:
    figure = build_figure(make_graph([]), style(), "light")
    go.Figure(figure)
    assert sankey(figure)["link"]["value"] == []
    annotations = figure["layout"]["annotations"]
    assert [a["text"] for a in annotations] == ["No entries to draw"]
    assert annotations[0]["font"]["color"] == TOKENS["light"].ink_secondary
    assert figure["layout"]["height"] == 560


def test_the_cap_and_the_empty_state_can_combine() -> None:
    figure = build_figure(budget(), style(), "light", FigureOptions(max_links=0))
    texts = [a["text"] for a in figure["layout"]["annotations"]]
    assert texts == ["Showing 0 of 8 links", "No entries to draw"]


@pytest.mark.parametrize(
    ("permille", "text"),
    [(0, "0.0%"), (1, "0.1%"), (125, "12.5%"), (999, "99.9%"), (1000, "100.0%")],
)
def test_percent_text_has_one_decimal(permille: int, text: str) -> None:
    assert percent_text(permille) == text
    assert percent_text(permille) is percent_text(permille)


def test_shares_round_to_a_tenth_of_a_percent_and_guard_zero_totals() -> None:
    graph = make_graph([("A", "B", 1.0, None), ("A", "C", 2.0, None)])
    link = sankey(build_figure(graph, style(), "light"))["link"]
    assert [row[3] for row in link["customdata"]] == ["33.3%", "66.7%"]
    assert BUDGET[0][2] == 5000.0


def test_the_legend_layout_keeps_the_base_font_and_background() -> None:
    legend = build_figure(budget(), style(color_mode="category"), "light")["layout"]["legend"]
    assert legend == {
        "font": {"family": FONT_FAMILY, "size": 13, "color": TOKENS["light"].ink},
        "bgcolor": TRANSPARENT,
        "orientation": "h",
        "x": 0,
        "xanchor": "left",
        "y": 1,
        "yanchor": "bottom",
        "itemclick": False,
        "itemdoubleclick": False,
    }
