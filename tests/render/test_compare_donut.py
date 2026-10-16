# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Compare-view donut (GAPS-V2 item 2): hue and fold agree because both ask ``has_hue``."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.render.colors import ColorMap
from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.donut_fold import donut_slices
from sankey_studio.render.legend import legend_items
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.palette import CATEGORICAL, OTHER_COLOR
from sankey_studio.render.tables import category_table
from tests.graph_support import make_graph
from tests.render.support import style

if TYPE_CHECKING:
    from sankey_studio.models import RawLink, SankeyGraph, Theme


class Pair(NamedTuple):
    a: SankeyGraph
    b: SankeyGraph


def build_pair() -> Pair:
    """``X`` is slot 8 in A but the biggest category over A and B; ``Y`` is slot 0 in A but last.

    A sees (in order) Y, z1..z7, X. B holds X (1000), w1..w8 (50 each).
    """
    a_links: list[RawLink] = [("src", "y", 1.0, "Y")]
    a_links += [("src", f"z{i}", 10.0, f"z{i}") for i in range(1, 8)]
    a_links += [("src", "x", 2.0, "X")]
    b_links: list[RawLink] = [("src", "x", 1000.0, "X")]
    b_links += [("src", f"w{i}", 50.0, f"w{i}") for i in range(1, 9)]
    return Pair(make_graph(a_links), make_graph(b_links))


def test_the_fixture_has_the_slots_the_scenario_needs() -> None:
    pair = build_pair()
    slots = dict(zip(pair.a.categories, pair.a.category_color_slot, strict=True))
    assert slots["Y"] == 0
    assert slots["X"] == 8
    colors = ColorMap.for_graphs([pair.a, pair.b], style())
    assert colors.category_slots["x"] == 0
    assert colors.category_slots["y"] >= 8


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_donut_follows_the_union_ranking(theme: Theme) -> None:
    pair = build_pair()
    colors = ColorMap.for_graphs([pair.a, pair.b], style())
    figure = build_donut_figure(pair.a, style(), theme, FigureOptions(colors=colors))
    trace = figure["data"][0]
    assert trace["labels"] == ["X", "Other"]  # X keeps its own slice, Y and the z's fold
    assert trace["values"] == [2.0, 1.0 + 7 * 10.0]
    assert trace["marker"]["colors"] == [colors.category_color("X", theme), OTHER_COLOR[theme]]
    assert trace["marker"]["colors"][0] == CATEGORICAL[theme][0]
    assert trace["marker"]["pattern"]["shape"] == ["", "/"]


def test_without_a_compare_map_the_single_graph_slots_apply() -> None:
    pair = build_pair()
    trace = build_donut_figure(pair.a, style(), "light")["data"][0]
    assert trace["labels"] == [f"z{i}" for i in range(1, 7)] + ["Other"]  # X is slot 8: no hue
    assert trace["marker"]["colors"][:6] == list(CATEGORICAL["light"][1:7])
    assert trace["values"][-1] == 10.0 + 1.0 + 2.0  # z7, Y and X


def test_an_other_slice_exists_iff_some_category_lacks_a_hue() -> None:
    pair = build_pair()
    union = ColorMap.for_graphs([pair.a, pair.b], style())
    with_other = donut_slices(pair.a, style(), union)
    assert [s.kind for s in with_other] == ["category", "other"]
    small = make_graph([("a", "b", 1.0, "p"), ("a", "c", 2.0, "q")])
    own = ColorMap.for_graph(small, style())
    assert all(s.kind != "other" for s in donut_slices(small, style(), own))
    assert all(
        s.kind != "other"
        for s in donut_slices(small, style(), ColorMap.for_graphs([small], style()))
    )


def test_every_non_other_slice_has_the_colour_of_the_shared_map() -> None:
    pair = build_pair()
    colors = ColorMap.for_graphs([pair.a, pair.b], style(category_colors={"z3": "#0a0b0c"}))
    figure = build_donut_figure(pair.a, style(), "light", FigureOptions(colors=colors))
    trace = figure["data"][0]
    for label, color in zip(trace["labels"], trace["marker"]["colors"], strict=True):
        if label != "Other":
            assert color == colors.category_color(label, "light")
    assert "z3" in trace["labels"]
    assert trace["marker"]["colors"][trace["labels"].index("z3")] == "#0a0b0c"


def test_the_sankey_legend_shows_other_under_the_same_condition() -> None:
    pair = build_pair()
    colors = ColorMap.for_graphs([pair.a, pair.b], style())
    options = FigureOptions(colors=colors)
    items = legend_items(pair.a, style(color_mode="category"), "light", options)
    assert [item.label for item in items] == ["X", "Other"]
    assert items[0].color == colors.category_color("X", "light")
    assert items[1].color == OTHER_COLOR["light"]
    small = make_graph([("a", "b", 1.0, "p")])
    only = legend_items(
        small,
        style(color_mode="category"),
        "light",
        FigureOptions(colors=ColorMap.for_graphs([small], style())),
    )
    assert [item.label for item in only] == ["p"]


def test_the_category_table_has_the_rows_of_the_slices() -> None:
    pair = build_pair()
    colors = ColorMap.for_graphs([pair.a, pair.b], style())
    slices = donut_slices(pair.a, style(), colors)
    rows = category_table(pair.a, style(), "light", colors)
    assert [(r.name, r.value, r.share, r.kind) for r in rows] == [
        (s.name, s.value, s.share, s.kind) for s in slices
    ]
    assert [r.color for r in rows] == [colors.category_color("X", "light"), OTHER_COLOR["light"]]
    own = category_table(pair.a, style(), "light")
    assert [r.name for r in own][-1] == "Other"
    assert len(own) == 7


def test_the_figure_options_colours_never_touch_node_colours() -> None:
    from sankey_studio.render.sankey import build_figure

    pair = build_pair()
    colors = ColorMap.for_graphs([pair.a, pair.b], style())
    own = build_figure(pair.a, style(), "light")
    shared = build_figure(pair.a, style(), "light", FigureOptions(colors=colors))
    assert shared["data"][0]["node"]["color"] == own["data"][0]["node"]["color"]
