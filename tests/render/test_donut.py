"""``build_donut_figure``: slices, colours, labels, centre total and the empty state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NamedTuple

import plotly.graph_objects as go
import pytest

from sankey_studio.errors import NoCategoriesError
from sankey_studio.models import StyleSpec
from sankey_studio.render.colors import ColorMap
from sankey_studio.render.donut import (
    DIRECT_LABEL_MAX,
    DONUT_HEIGHT,
    EMPTY_TEXT,
    MAX_TOTAL_FONT,
    MIN_TOTAL_FONT,
    build_donut_figure,
    category_totals,
    total_font_size,
)
from sankey_studio.render.donut_fold import NO_CATEGORIES_TEXT
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.palette import CATEGORICAL, OTHER_COLOR, TOKENS, UNCATEGORIZED_COLOR
from tests.graph_support import make_graph
from tests.render.support import budget, many_categories, plain, strings, style

if TYPE_CHECKING:
    from sankey_studio.models import Theme


def pie(figure: dict[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = figure["data"][0]
    assert trace["type"] == "pie"
    return trace


def test_a_graph_without_categories_has_no_donut() -> None:
    with pytest.raises(NoCategoriesError) as caught:
        build_donut_figure(plain(), style(), "light")
    assert caught.value.message == NO_CATEGORIES_TEXT
    assert NO_CATEGORIES_TEXT == "No entry has a category, so there is no donut chart"
    assert caught.value.code == "no_categories"
    assert caught.value.status_code == 422


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("basis", ["all", "initial", "terminal"])
def test_figure_is_plain_json_and_valid_for_plotly(theme: Theme, basis: str) -> None:
    figure = build_donut_figure(budget(), style(donut={"basis": basis}), theme)
    json.dumps(figure)
    go.Figure(figure)


def test_slices_values_and_colours() -> None:
    trace = pie(build_donut_figure(budget(), style(), "light"))
    assert trace["labels"] == ["Income", "Fixed", "Investing", "Variable", "Uncategorized"]
    assert trace["values"] == [5800.0, 2000.0, 1500.0, 1300.0, 1500.0]
    assert trace["marker"]["colors"] == [
        CATEGORICAL["light"][0],
        CATEGORICAL["light"][1],
        CATEGORICAL["light"][3],
        CATEGORICAL["light"][2],
        UNCATEGORIZED_COLOR,
    ]
    assert trace["marker"]["line"] == {"color": TOKENS["light"].surface, "width": 2}
    assert (trace["hole"], trace["direction"], trace["sort"]) == (0.58, "clockwise", False)
    assert trace["showlegend"] is True
    assert trace["automargin"] is True


def folded_figure(theme: Theme = "light") -> dict[str, Any]:
    graph = make_graph(
        [("a", f"t{i}", 100.0 - i, f"c{i}") for i in range(8)] + [("a", "u", 5.0, None)]
    )
    return build_donut_figure(graph, style(donut={"max_slices": 6}), theme)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_other_is_patterned_and_uncategorized_is_solid(theme: Theme) -> None:
    trace = pie(folded_figure(theme))
    assert trace["labels"][-2:] == ["Uncategorized", "Other"]
    colors, pattern = trace["marker"]["colors"], trace["marker"]["pattern"]
    assert colors[-2:] == [UNCATEGORIZED_COLOR, OTHER_COLOR[theme]]
    assert pattern["shape"] == [""] * 7 + ["/"]
    assert pattern["fgcolor"] == colors
    assert pattern["bgcolor"][:7] == colors[:7]
    assert pattern["bgcolor"][7] == TOKENS[theme].surface
    assert (pattern["size"], pattern["solidity"]) == (6, 0.4)


def test_category_slices_use_their_own_hue_in_each_theme() -> None:
    for theme in ("light", "dark"):
        trace = pie(folded_figure(theme))
        assert trace["marker"]["colors"][:6] == list(CATEGORICAL[theme][:6])


class Labels(NamedTuple):
    slices: int
    direct: bool


@pytest.mark.parametrize(
    "case", [Labels(2, True), Labels(3, True), Labels(4, True), Labels(5, False), Labels(8, False)]
)
def test_direct_labels_only_up_to_four_slices_and_never_auto(case: Labels) -> None:
    trace = pie(build_donut_figure(many_categories(case.slices), style(), "light"))
    assert DIRECT_LABEL_MAX == 4
    assert trace["textposition"] == ("outside" if case.direct else "none")
    assert trace["textinfo"] == ("label+percent" if case.direct else "none")


def test_percent_labels_follow_show_percent() -> None:
    graph = many_categories(3)
    on = pie(build_donut_figure(graph, style(donut={"show_percent": True}), "light"))
    off = pie(build_donut_figure(graph, style(donut={"show_percent": False}), "light"))
    assert on["textinfo"] == "label+percent"
    assert off["textinfo"] == "label"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_is_always_set_in_the_ink_token(theme: Theme) -> None:
    trace = pie(build_donut_figure(budget(), style(font_size=15), theme))
    for key in ("textfont", "insidetextfont", "outsidetextfont"):
        assert trace[key]["color"] == TOKENS[theme].ink
        assert trace[key]["size"] == 15


def test_hover_uses_customdata_and_a_fixed_template() -> None:
    graph = make_graph([("a", "b", 1234.5, "<i>x</i>"), ("a", "c", 10.0, "y")])
    trace = pie(build_donut_figure(graph, style(value_suffix="USD"), "light"))
    assert trace["hovertemplate"] == "%{label}<br>%{customdata[0]} (%{percent})<extra></extra>"
    assert trace["labels"] == ["&lt;i&gt;x&lt;/i&gt;", "y"]
    assert trace["customdata"] == [["1,234.5 USD"], ["10 USD"]]


def test_the_centre_total_covers_every_slice_and_follows_the_value_format() -> None:
    figure = build_donut_figure(budget(), style(value_format=",.1f", value_suffix="%"), "light")
    (annotation,) = figure["layout"]["annotations"]
    assert annotation["text"] == "12,100.0%"
    assert annotation["showarrow"] is False
    assert (annotation["x"], annotation["y"], annotation["xref"], annotation["yref"]) == (
        0.5,
        0.5,
        "paper",
        "paper",
    )
    assert annotation["font"]["color"] == TOKENS["light"].ink
    assert annotation["font"]["size"] == total_font_size(0.58, len("12,100.0%"))


def test_the_total_is_optional_and_escaped() -> None:
    off = build_donut_figure(budget(), style(donut={"show_total": False}), "light")
    assert off["layout"]["annotations"] == []
    on = build_donut_figure(budget(), style(value_suffix="<b>"), "light")
    assert on["layout"]["annotations"][0]["text"] == "12,100&lt;b&gt;"


class FontCase(NamedTuple):
    hole: float
    chars: int
    size: int


FONTS = [
    FontCase(0.58, 0, 40),
    FontCase(0.58, 1, 40),
    FontCase(0.58, 7, 40),
    FontCase(0.58, 8, 35),
    FontCase(0.58, 10, 28),
    FontCase(0.58, 19, 14),
    FontCase(0.58, 20, 14),
    FontCase(0.58, 21, 14),
    FontCase(0.58, 80, 14),
    FontCase(0.3, 3, 40),
    FontCase(0.3, 4, 36),
    FontCase(0.3, 10, 14),
    FontCase(0.85, 10, 40),
    FontCase(0.85, 11, 37),
    FontCase(0.1, 0, 40),
    FontCase(0.1, 1, 40),
    FontCase(0.1, 2, 24),
]


@pytest.mark.parametrize("case", FONTS)
def test_total_font_fits_the_hole_with_a_floor_of_14(case: FontCase) -> None:
    assert total_font_size(case.hole, case.chars) == case.size
    assert (MIN_TOTAL_FONT, MAX_TOTAL_FONT) == (14, 40)


def test_a_wider_hole_never_gives_a_smaller_total() -> None:
    sizes = [total_font_size(hole / 100, 12) for hole in range(30, 86, 5)]
    assert sizes == sorted(sizes)


def test_the_hole_and_the_title_come_from_the_style() -> None:
    figure = build_donut_figure(budget(), style(donut={"hole": 0.4}, title="Split <1>"), "dark")
    assert pie(figure)["hole"] == 0.4
    assert figure["layout"]["title"]["text"] == "Split &lt;1&gt;"
    assert figure["layout"]["margin"]["t"] == 16 + 36
    assert figure["layout"]["height"] == DONUT_HEIGHT == 460
    assert figure["layout"]["paper_bgcolor"] == TOKENS["dark"].surface


def test_no_donut_string_carries_markup_except_the_fixed_hover_template() -> None:
    hostile = "<a href=x>&</a>"
    graph = make_graph([("a", "b", 5.0, hostile), ("a", "c", 2.0, "plain")])
    unchecked = StyleSpec.model_construct(title=hostile, value_suffix=hostile, value_format=hostile)
    figure = build_donut_figure(graph, unchecked, "light")
    texts = [text for text in strings(figure) if text != pie(figure)["hovertemplate"]]
    assert len(texts) > 5
    assert [text for text in texts if "<" in text or ">" in text] == []
    assert hostile not in texts


def test_the_value_sort_orders_by_value_and_the_name_sort_by_name() -> None:
    graph = make_graph([("a", "b", 1.0, "b"), ("a", "c", 3.0, "a"), ("a", "d", 2.0, "c")])
    by_value = pie(build_donut_figure(graph, style(), "light"))["labels"]
    by_name = pie(build_donut_figure(graph, style(donut={"sort": "name"}), "light"))["labels"]
    assert by_value == ["a", "c", "b"]
    assert by_name == ["a", "b", "c"]


def test_the_basis_changes_what_is_counted() -> None:
    graph = budget()
    initial = pie(build_donut_figure(graph, style(donut={"basis": "initial"}), "light"))
    terminal = pie(build_donut_figure(graph, style(donut={"basis": "terminal"}), "light"))
    assert (initial["labels"], initial["values"]) == (["Income"], [5800.0])
    assert terminal["labels"] == ["Fixed", "Investing", "Variable"]
    assert terminal["values"] == [2000.0, 1500.0, 1300.0]


def test_an_empty_basis_gives_an_empty_state_figure() -> None:
    graph = make_graph([("a", "b", 1.0, None), ("b", "c", 1.0, "x")])
    figure = build_donut_figure(graph, style(donut={"basis": "initial"}), "light")
    go.Figure(figure)
    assert figure["data"] == []
    assert [a["text"] for a in figure["layout"]["annotations"]] == [EMPTY_TEXT]
    assert EMPTY_TEXT == "No categorised entries for this basis"
    assert figure["layout"]["annotations"][0]["font"]["color"] == TOKENS["light"].ink_secondary
    assert figure["layout"]["showlegend"] is False
    assert figure["layout"]["xaxis"]["visible"] is False
    assert figure["layout"]["yaxis"]["visible"] is False


def test_max_links_is_ignored_by_the_donut() -> None:
    graph = budget()
    plain_figure = build_donut_figure(graph, style(), "light")
    capped = build_donut_figure(graph, style(), "light", FigureOptions(max_links=1))
    assert capped == plain_figure


def test_the_colour_map_of_the_options_is_used_for_hues() -> None:
    graph = many_categories(2)
    colors = ColorMap.for_graph(graph, style(category_colors={"cat00": "#abcdef"}))
    trace = pie(build_donut_figure(graph, style(), "light", FigureOptions(colors=colors)))
    assert trace["marker"]["colors"] == ["#abcdef", CATEGORICAL["light"][1]]


def test_the_empty_state_annotation_is_centred_secondary_ink() -> None:
    graph = make_graph([("a", "b", 1.0, None), ("b", "c", 1.0, "x")])
    figure = build_donut_figure(graph, style(donut={"basis": "initial"}), "dark")
    assert figure["layout"]["annotations"] == [
        {
            "text": "No categorised entries for this basis",
            "xref": "paper",
            "yref": "paper",
            "x": 0.5,
            "y": 0.5,
            "showarrow": False,
            "font": {
                "family": 'system-ui, -apple-system, "Segoe UI", sans-serif',
                "size": 13,
                "color": TOKENS["dark"].ink_secondary,
            },
        }
    ]
    assert figure["layout"]["margin"] == {"l": 16, "r": 16, "t": 16, "b": 16}


def test_the_layout_has_the_fixed_height_margin_and_legend_flag() -> None:
    layout = build_donut_figure(budget(), style(), "light")["layout"]
    assert layout["height"] == 460
    assert layout["margin"] == {"l": 16, "r": 16, "t": 16, "b": 16}
    assert layout["showlegend"] is True


def test_category_totals_is_part_of_the_donut_module() -> None:
    assert next(t.name for t in category_totals(budget(), "all")) == "Income"
