"""``legend_items``: the same items feed the page and the legend traces inside the figure."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.render.colors import ColorMap
from sankey_studio.render.legend import LegendItem, legend_items, legend_traces
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.palette import CATEGORICAL, LAYER_RAMP, OTHER_COLOR, UNCATEGORIZED_COLOR
from sankey_studio.render.sankey import build_figure
from tests.graph_support import make_graph
from tests.render.support import budget, many_categories, plain, style

if TYPE_CHECKING:
    from sankey_studio.models import Theme


@pytest.mark.parametrize("mode", ["node", "mono"])
def test_node_and_mono_modes_have_no_legend(mode: str) -> None:
    assert legend_items(budget(), style(color_mode=mode), "light") == []


def test_category_mode_lists_real_categories_then_uncategorized() -> None:
    items = legend_items(budget(), style(color_mode="category"), "light")
    assert items == [
        LegendItem("Income", CATEGORICAL["light"][0], "category", 5800.0),
        LegendItem("Fixed", CATEGORICAL["light"][1], "category", 2000.0),
        LegendItem("Variable", CATEGORICAL["light"][2], "category", 1300.0),
        LegendItem("Investing", CATEGORICAL["light"][3], "category", 1500.0),
        LegendItem("Uncategorized", UNCATEGORIZED_COLOR, "category", 1500.0),
    ]


def test_category_mode_without_categories_behaves_like_node_mode() -> None:
    assert legend_items(plain(), style(color_mode="category"), "light") == []


def test_categories_without_a_hue_fold_into_other_before_uncategorized() -> None:
    graph = make_graph(
        [("Src", f"T{i}", 10.0 + i, f"c{i}") for i in range(10)] + [("Src", "U", 3.0, None)]
    )
    items = legend_items(graph, style(color_mode="category"), "dark")
    assert [item.label for item in items] == [f"c{i}" for i in range(8)] + [
        "Other",
        "Uncategorized",
    ]
    other = items[8]
    assert other == LegendItem("Other", OTHER_COLOR["dark"], "category", 18.0 + 19.0)
    assert items[9].value == 3.0
    assert items[7].color == CATEGORICAL["dark"][7]


def test_other_is_absent_when_every_drawn_category_has_a_hue() -> None:
    items = legend_items(many_categories(8), style(color_mode="category"), "light")
    assert [item.label for item in items] == [f"cat{i:02d}" for i in range(8)]


def test_other_appears_only_when_a_drawn_link_carries_a_category_without_a_hue() -> None:
    graph = many_categories(9)
    full = legend_items(graph, style(color_mode="category"), "light")
    assert full[-1].label == "Other"
    cap = FigureOptions(max_links=8)
    capped = legend_items(graph, style(color_mode="category"), "light", cap)
    assert [item.label for item in capped] == [f"cat{i:02d}" for i in range(8)]


def test_the_legend_only_lists_categories_on_drawn_links() -> None:
    graph = budget()
    items = legend_items(graph, style(color_mode="category"), "light", FigureOptions(max_links=3))
    assert [item.label for item in items] == ["Income", "Fixed", "Uncategorized"]
    assert [item.value for item in items] == [5000.0, 2000.0, 1500.0]


class Overrides(NamedTuple):
    colors: dict[str, str]
    has_other: bool


@pytest.mark.parametrize(
    "case",
    [
        Overrides({}, True),
        Overrides({"cat08": "#010101"}, True),
        Overrides({"cat08": "#010101", "cat09": "#020202"}, False),
    ],
)
def test_overrides_give_a_hue_and_so_a_legend_entry(case: Overrides) -> None:
    graph = many_categories(10)
    items = legend_items(graph, style(color_mode="category", category_colors=case.colors), "light")
    assert [item.label for item in items if item.label == "Other"] == (
        ["Other"] if case.has_other else []
    )
    colors = {item.label: item.color for item in items}
    for name, color in case.colors.items():
        assert colors[name] == color


def test_the_compare_map_decides_who_has_a_hue_and_so_the_legend_other() -> None:
    first = make_graph([("a", "b", 1.0, "X"), ("a", "c", 100.0, "Y")])
    second = make_graph([("a", "b", 50.0, "X")])
    colors = ColorMap.for_graphs([first, second], style())
    items = legend_items(first, style(color_mode="category"), "light", FigureOptions(colors=colors))
    assert [(item.label, item.color) for item in items] == [
        ("X", CATEGORICAL["light"][1]),
        ("Y", CATEGORICAL["light"][0]),
    ]


def test_the_compare_map_can_push_a_category_into_other() -> None:
    many = [("a", f"t{i}", 100.0 - i, f"c{i}") for i in range(9)]
    graph = make_graph([("a", "z", 1.0, "late"), *many])
    colors = ColorMap.for_graphs([graph], style())
    items = legend_items(graph, style(color_mode="category"), "light", FigureOptions(colors=colors))
    assert [item.label for item in items][-1] == "Other"
    assert "late" not in [item.label for item in items]
    # with its own slots the same graph gives "late" a hue (it is the first category seen)
    own = legend_items(graph, style(color_mode="category"), "light")
    assert "late" in [item.label for item in own]


class Layers(NamedTuple):
    theme: Theme
    depth: int
    labels: list[str]


LAYERS = [
    Layers("light", 2, ["Layer 1", "Layer 2"]),
    Layers("light", 4, ["Layer 1", "Layer 2", "Layer 3", "Layer 4"]),
    Layers("light", 5, ["Layer 1", "Layer 2", "Layer 3", "Layer 4", "Layer 5"]),
    Layers("light", 6, ["Layer 1", "Layer 2", "Layer 3", "Layer 4", "Layers 5+"]),
    Layers("light", 9, ["Layer 1", "Layer 2", "Layer 3", "Layer 4", "Layers 5+"]),
    Layers("dark", 5, ["Layer 1", "Layer 2", "Layer 3", "Layer 4", "Layer 5"]),
    Layers("dark", 6, ["Layer 1", "Layer 2", "Layer 3", "Layer 4", "Layer 5", "Layer 6"]),
    Layers("dark", 7, ["Layer 1", "Layer 2", "Layer 3", "Layer 4", "Layer 5", "Layers 6+"]),
]


@pytest.mark.parametrize("case", LAYERS)
def test_layer_mode_lists_the_ramp_steps_in_use(case: Layers) -> None:
    graph = make_graph([(f"n{i}", f"n{i + 1}", 1.0, None) for i in range(case.depth - 1)])
    items = legend_items(graph, style(color_mode="layer"), case.theme)
    assert [item.label for item in items] == case.labels
    assert [item.color for item in items] == list(LAYER_RAMP[case.theme][: len(case.labels)])
    assert {item.kind for item in items} == {"layer"}
    assert {item.value for item in items} == {None}


def test_layer_mode_with_nothing_drawn_has_no_legend() -> None:
    items = legend_items(budget(), style(color_mode="layer"), "light", FigureOptions(max_links=0))
    assert items == []


def test_legend_traces_are_squares_with_escaped_names() -> None:
    items = [LegendItem("a<b>", "#123456", "category", 1.0), LegendItem("R&D", "#654321", "layer")]
    traces = legend_traces(items)
    assert [t["name"] for t in traces] == ["a&lt;b&gt;", "R&amp;D"]
    assert [t["marker"]["color"] for t in traces] == ["#123456", "#654321"]
    assert all(t["marker"]["symbol"] == "square" and t["marker"]["size"] == 10 for t in traces)
    assert all(t["showlegend"] is True and t["hoverinfo"] == "skip" for t in traces)
    assert legend_traces([]) == []


@pytest.mark.parametrize("mode", ["category", "layer"])
def test_the_page_legend_and_the_figure_legend_agree(mode: str) -> None:
    graph = budget()
    items = legend_items(graph, style(color_mode=mode), "light")
    figure = build_figure(graph, style(color_mode=mode), "light")
    assert [t["name"] for t in figure["data"][1:]] == [item.label for item in items]
    assert [t["marker"]["color"] for t in figure["data"][1:]] == [item.color for item in items]
