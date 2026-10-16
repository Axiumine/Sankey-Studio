# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Donut slice text: ``text_info``, and ``textinfo``, ``texttemplate``, ``text`` of the trace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import plotly.graph_objects as go
import pytest

from sankey_studio.models import DonutStyle, StyleSpec
from sankey_studio.render.donut import DIRECT_LABEL_MAX, build_donut_figure, text_info, text_parts
from sankey_studio.render.palette import TOKENS
from tests.graph_support import make_graph
from tests.render.support import budget, many_categories, strings, style

if TYPE_CHECKING:
    from sankey_studio.models import Theme


def pie(figure: dict[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = figure["data"][0]
    assert trace["type"] == "pie"
    return trace


class Info(NamedTuple):
    show_value: bool
    show_percent: bool
    direct: bool
    expected: str


INFO = [
    Info(False, False, True, "label"),
    Info(False, True, True, "label+percent"),
    Info(True, False, True, "label+text"),
    Info(True, True, True, "label+text+percent"),
    Info(False, False, False, "none"),
    Info(False, True, False, "percent"),
    Info(True, False, False, "text"),
    Info(True, True, False, "text+percent"),
]


@pytest.mark.parametrize("case", INFO, ids=repr)
def test_text_info_lists_the_flags_of_what_a_slice_prints(case: Info) -> None:
    donut = DonutStyle(show_value=case.show_value, show_percent=case.show_percent)
    assert text_info(donut, direct=case.direct) == case.expected


class Template(NamedTuple):
    slices: int
    value: bool
    percent: bool
    expected: str | None


TEMPLATES = [
    # the name only with up to four slices; the percentage always comes before the value
    Template(3, False, False, "%{label}"),
    Template(3, False, True, "%{label}<br>%{percent}"),
    Template(3, True, False, "%{label}<br>%{text}"),
    Template(3, True, True, "%{label}<br>%{percent}<br>%{text}"),
    Template(4, True, True, "%{label}<br>%{percent}<br>%{text}"),
    Template(5, True, True, "%{percent}<br>%{text}"),
    Template(5, False, True, "%{percent}"),
    Template(5, True, False, "%{text}"),
    Template(5, False, False, None),
]


@pytest.mark.parametrize("case", TEMPLATES, ids=repr)
def test_the_template_prints_the_name_then_the_percentage_then_the_value(case: Template) -> None:
    donut = {"show_value": case.value, "show_percent": case.percent}
    figure = build_donut_figure(many_categories(case.slices), style(donut=donut), "light")
    assert pie(figure).get("texttemplate") == case.expected


@pytest.mark.parametrize("direct", [True, False])
def test_text_parts_put_the_percentage_before_the_value(direct: bool) -> None:
    parts = text_parts(DonutStyle(show_value=True, show_percent=True), direct=direct)
    assert parts == (["label"] if direct else []) + ["percent", "text"]


class Labels(NamedTuple):
    slices: int
    value: bool
    percent: bool
    info: str
    position: str


LABELS = [
    # the defaults: percentage on, value off
    Labels(2, False, True, "label+percent", "outside"),
    Labels(3, False, True, "label+percent", "outside"),
    Labels(4, False, True, "label+percent", "outside"),
    Labels(5, False, True, "percent", "auto"),
    Labels(8, False, True, "percent", "auto"),
    # nothing but the name
    Labels(4, False, False, "label", "outside"),
    Labels(5, False, False, "none", "none"),
    Labels(8, False, False, "none", "none"),
    # the value on its own
    Labels(4, True, False, "label+text", "outside"),
    Labels(5, True, False, "text", "auto"),
    # value and percentage
    Labels(4, True, True, "label+text+percent", "outside"),
    Labels(5, True, True, "text+percent", "auto"),
    Labels(8, True, True, "text+percent", "auto"),
]


@pytest.mark.parametrize("case", LABELS, ids=repr)
def test_the_name_is_drawn_on_up_to_four_slices_and_value_and_percent_on_every_slice(
    case: Labels,
) -> None:
    donut = {"show_value": case.value, "show_percent": case.percent}
    figure = build_donut_figure(many_categories(case.slices), style(donut=donut), "light")
    trace = pie(figure)
    assert DIRECT_LABEL_MAX == 4
    assert trace["textinfo"] == case.info
    assert trace["textposition"] == case.position


def test_the_old_default_for_many_slices_now_shows_the_percentage() -> None:
    trace = pie(build_donut_figure(many_categories(6), style(), "light"))
    assert (trace["textinfo"], trace["textposition"]) == ("percent", "auto")


def test_the_text_array_is_the_formatted_value_of_each_slice() -> None:
    graph = make_graph([("a", "b", 1234.5, "x"), ("a", "c", 10.0, "y")])
    look = style(value_suffix="USD", donut={"show_value": True})
    trace = pie(build_donut_figure(graph, look, "light"))
    assert trace["text"] == ["1,234.5 USD", "10 USD"]
    assert trace["text"] == [row[0] for row in trace["customdata"]]


def test_the_text_array_follows_the_value_format_and_the_value_suffix() -> None:
    graph = make_graph([("a", "b", 1234.5, "x"), ("a", "c", 10.0, "y")])
    look = style(value_format=",.1f", value_suffix="%", donut={"show_value": True})
    assert pie(build_donut_figure(graph, look, "light"))["text"] == ["1,234.5%", "10.0%"]


def test_the_suffix_of_the_text_array_is_escaped() -> None:
    graph = make_graph([("a", "b", 10.0, "x"), ("a", "c", 5.0, "y")])
    look = style(value_suffix="<b>", donut={"show_value": True})
    assert pie(build_donut_figure(graph, look, "light"))["text"] == ["10&lt;b&gt;", "5&lt;b&gt;"]


@pytest.mark.parametrize("percent", [True, False])
def test_there_is_no_text_array_without_show_value(percent: bool) -> None:
    look = style(value_suffix="USD", donut={"show_value": False, "show_percent": percent})
    assert "text" not in pie(build_donut_figure(budget(), look, "light"))
    assert "text" not in pie(build_donut_figure(budget(), style(), "light"))


def test_the_text_array_has_one_entry_per_slice_even_when_slices_fold_into_other() -> None:
    look = style(donut={"show_value": True, "max_slices": 3})
    trace = pie(build_donut_figure(many_categories(10), look, "light"))
    assert len(trace["labels"]) == len(trace["text"]) == 4
    assert trace["labels"][-1] == "Other"
    assert trace["text"] == ["1,000", "999", "998", "6,958"]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("slices", [3, 6])
@pytest.mark.parametrize("flags", [(False, False), (False, True), (True, False), (True, True)])
def test_every_label_combination_is_valid_for_plotly(
    theme: Theme, slices: int, flags: tuple[bool, bool]
) -> None:
    donut = {"show_value": flags[0], "show_percent": flags[1]}
    figure = build_donut_figure(many_categories(slices), style(donut=donut), theme)
    go.Figure(figure)
    assert pie(figure)["textfont"]["color"] == TOKENS[theme].ink


def test_the_value_text_never_carries_markup() -> None:
    hostile = "<a href=x>&</a>"
    graph = make_graph([("a", "b", 5.0, hostile), ("a", "c", 2.0, "plain")])
    unchecked = StyleSpec.model_construct(
        title=hostile,
        value_suffix=hostile,
        value_format=hostile,
        donut=DonutStyle(show_value=True),
    )
    figure = build_donut_figure(graph, unchecked, "light")
    trace = pie(figure)
    assert len(trace["text"]) == 2
    assert trace["texttemplate"] == "%{label}<br>%{percent}<br>%{text}"  # placeholders only
    fixed = {trace["hovertemplate"], trace["texttemplate"]}
    texts = [text for text in strings(figure) if text not in fixed]
    assert [text for text in texts if "<" in text or ">" in text] == []
