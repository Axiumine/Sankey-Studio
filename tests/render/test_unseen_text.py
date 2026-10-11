"""Hostile node, category and title text reaches a Plotly figure only as literal, visible text.

The names hold Plotly markup, a bell, an escape, DEL, a C1 control and bidi overrides. After
``escape_label`` no figure string contains an unseen character, and the markup is entity-escaped,
so Plotly draws it as the characters typed (the real-browser check is in the wave report).
"""

from __future__ import annotations

from typing import Any, Final

from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.sankey import build_figure
from sankey_studio.render.text import escape_label
from tests.graph_support import make_graph
from tests.render.support import strings, style

MARKUP: Final = "<a href=javascript:1>x</a><b>y</b><br>"
ESCAPED_MARKUP: Final = "&lt;a href=javascript:1&gt;x&lt;/a&gt;&lt;b&gt;y&lt;/b&gt;&lt;br&gt;"
#: Bell, escape, DEL, a C1 control, tab/LF/CR and the bidi override and isolate characters.
UNSEEN_TEXT: Final = "\x07\x1b\x7f\x85\t\n\r\u202e\u2066\u2069"
UNSEEN: Final = frozenset(UNSEEN_TEXT)


def hostile_graph() -> Any:
    """Node names with every unseen character; categories keep the bidi ones (control characters
    in a category make ``build_graph`` ignore the category altogether)."""
    return make_graph(
        [
            (f"{MARKUP}{UNSEEN_TEXT}", f"Rent{UNSEEN_TEXT}RTL", 5.0, "Fixed\u202e\u2066"),
            (f"{MARKUP}{UNSEEN_TEXT}", 'A & B "q" <i>', 3.0, "<i>Var</i> & more"),
        ]
    )


def hostile_style() -> Any:
    return style(
        title=f"{MARKUP}{UNSEEN_TEXT}",
        color_mode="category",
        value_suffix=f"<b>{UNSEEN_TEXT}$",
    )


def characters(figure: dict[str, Any]) -> set[str]:
    """Every character of every string value of the figure."""
    return set().union(*(set(text) for text in strings(figure)))


def test_a_sankey_figure_holds_no_unseen_character_anywhere() -> None:
    figure = build_figure(hostile_graph(), hostile_style(), "light")
    assert not UNSEEN & characters(figure)


def test_a_donut_figure_holds_no_unseen_character_anywhere() -> None:
    figure = build_donut_figure(hostile_graph(), hostile_style(), "light")
    assert not UNSEEN & characters(figure)


def test_the_sankey_draws_the_markup_as_literal_text() -> None:
    figure = build_figure(hostile_graph(), hostile_style(), "light")
    trace = figure["data"][0]
    assert trace["node"]["label"][0] == escape_label(MARKUP[:32]) + "…"
    assert ESCAPED_MARKUP in trace["node"]["customdata"][0][0]
    assert trace["node"]["customdata"][0][0] == ESCAPED_MARKUP
    assert trace["link"]["customdata"][0][0] == ESCAPED_MARKUP
    assert trace["link"]["customdata"][0][1] == "RentRTL"
    assert trace["node"]["label"][1] == "RentRTL"
    assert trace["valuesuffix"] == "&lt;b&gt;$"
    assert figure["layout"]["title"]["text"] == ESCAPED_MARKUP


def test_the_sankey_legend_entries_are_literal_text_too() -> None:
    figure = build_figure(hostile_graph(), hostile_style(), "light")
    names = [trace["name"] for trace in figure["data"][1:]]
    assert names == ["Fixed", "&lt;i&gt;Var&lt;/i&gt; &amp; more"]


def test_the_donut_slices_and_total_are_literal_text() -> None:
    figure = build_donut_figure(hostile_graph(), hostile_style(), "light")
    trace = figure["data"][0]
    assert trace["labels"] == ["Fixed", "&lt;i&gt;Var&lt;/i&gt; &amp; more"]
    assert trace["customdata"][0][0].endswith("&lt;b&gt;$")
    assert figure["layout"]["title"]["text"] == ESCAPED_MARKUP
    assert [a["text"] for a in figure["layout"]["annotations"]] == ["8&lt;b&gt;$"]
