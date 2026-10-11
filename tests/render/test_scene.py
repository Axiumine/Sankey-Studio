"""``Scene``: which links and nodes are drawn and in which colour."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.render.colors import ColorMap, to_rgba
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.palette import (
    CATEGORICAL,
    LAYER_RAMP,
    MONO_COLOR,
    NODE_NEUTRAL,
    OTHER_COLOR,
    UNCATEGORIZED_COLOR,
)
from sankey_studio.render.scene import (
    effective_mode,
    link_colors,
    make_scene,
    node_color,
    select_drawn,
)
from tests.graph_support import make_graph
from tests.render.support import budget, many_categories, plain, style

if TYPE_CHECKING:
    from sankey_studio.models import Theme


class Cap(NamedTuple):
    max_links: int | None
    links: list[int]


def test_everything_is_drawn_without_a_cap() -> None:
    graph = budget()
    drawn = select_drawn(graph, None)
    assert drawn.links == list(range(graph.n_links))
    assert drawn.nodes == list(range(graph.n_nodes))
    assert drawn.total_links == graph.n_links
    assert not drawn.truncated


@pytest.mark.parametrize("size", [0, 1])
def test_a_cap_at_or_above_the_link_count_changes_nothing(size: int) -> None:
    graph = plain()
    drawn = select_drawn(graph, graph.n_links + size)
    assert drawn.links == list(range(graph.n_links))
    assert not drawn.truncated


def test_a_cap_keeps_the_largest_links_in_original_order() -> None:
    graph = make_graph(
        [("A", "B", 5.0, None), ("A", "C", 9.0, None), ("A", "D", 1.0, None), ("B", "E", 7.0, None)]
    )
    drawn = select_drawn(graph, 2)
    assert drawn.links == [1, 3]
    assert drawn.truncated
    assert drawn.total_links == 4
    assert [graph.node_names[n] for n in drawn.nodes] == ["A", "B", "C", "E"]


def test_cap_ties_keep_the_earlier_link() -> None:
    graph = make_graph([("A", "B", 2.0, None), ("A", "C", 2.0, None), ("A", "D", 2.0, None)])
    assert select_drawn(graph, 2).links == [0, 1]


@pytest.mark.parametrize("cap", [0, -3])
def test_a_cap_of_zero_or_less_draws_nothing(cap: int) -> None:
    drawn = select_drawn(plain(), cap)
    assert drawn.links == []
    assert drawn.nodes == []
    assert drawn.truncated


class Mode(NamedTuple):
    mode: str
    categorised: bool
    expected: str


@pytest.mark.parametrize(
    "case",
    [
        Mode("node", True, "node"),
        Mode("layer", True, "layer"),
        Mode("mono", False, "mono"),
        Mode("category", True, "category"),
        Mode("category", False, "node"),
    ],
)
def test_effective_mode_needs_a_categorised_link_for_category(case: Mode) -> None:
    graph = budget() if case.categorised else plain()
    drawn = select_drawn(graph, None)
    assert effective_mode(graph, style(color_mode=case.mode), drawn) == case.expected


def test_category_mode_follows_the_drawn_links_not_the_whole_graph() -> None:
    graph = make_graph([("A", "B", 9.0, None), ("A", "C", 1.0, "x")])
    scene = make_scene(graph, style(color_mode="category"), "light", FigureOptions(max_links=1))
    assert scene.mode == "node"
    assert make_scene(graph, style(color_mode="category"), "light", None).mode == "category"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_node_colours_per_mode(theme: Theme) -> None:
    graph = budget()
    cases = {
        "node": CATEGORICAL[theme][0],
        "layer": LAYER_RAMP[theme][0],
        "mono": MONO_COLOR[theme],
        "category": NODE_NEUTRAL,
    }
    for mode, expected in cases.items():
        scene = make_scene(graph, style(color_mode=mode), theme, None)
        assert node_color(scene, 0) == expected, mode
    mono = make_scene(graph, style(color_mode="mono"), theme, None)
    assert {node_color(mono, node) for node in range(graph.n_nodes)} == {MONO_COLOR[theme]}
    assert node_color(make_scene(graph, style(), theme, None), 1) == CATEGORICAL[theme][1]


def test_layer_mode_steps_with_the_layer() -> None:
    graph = budget()
    scene = make_scene(graph, style(color_mode="layer"), "light", None)
    by_name = {name: node_color(scene, i) for i, name in enumerate(graph.node_names)}
    assert by_name["Salary"] == LAYER_RAMP["light"][0]
    assert by_name["Budget"] == LAYER_RAMP["light"][1]
    assert by_name["Savings"] == LAYER_RAMP["light"][2]
    assert by_name["Stocks"] == LAYER_RAMP["light"][3]


def test_links_take_the_colour_of_their_source_node_at_the_link_opacity() -> None:
    graph = budget()
    scene = make_scene(graph, style(link_opacity=0.25), "light", None)
    colors = link_colors(scene)
    assert len(colors) == graph.n_links
    expected = [
        to_rgba(node_color(scene, graph.link_source[i]), 0.25) for i in range(graph.n_links)
    ]
    assert colors == expected
    assert colors[0] == to_rgba(CATEGORICAL["light"][0], 0.25)


def test_category_mode_colours_links_by_category() -> None:
    graph = budget()
    scene = make_scene(graph, style(color_mode="category", link_opacity=0.5), "dark", None)
    colors = link_colors(scene)
    names = [
        UNCATEGORIZED_COLOR
        if graph.link_category[i] < 0
        else CATEGORICAL["dark"][graph.link_category[i]]
        for i in range(graph.n_links)
    ]
    assert colors == [to_rgba(color, 0.5) for color in names]


def test_category_mode_uses_the_neutral_colour_for_categories_without_a_hue() -> None:
    graph = many_categories(10)
    scene = make_scene(graph, style(color_mode="category"), "light", None)
    colors = link_colors(scene)
    assert colors[8] == to_rgba(OTHER_COLOR["light"], 0.4)
    assert colors[9] == to_rgba(OTHER_COLOR["light"], 0.4)
    assert colors[7] == to_rgba(CATEGORICAL["light"][7], 0.4)


def test_the_compare_colour_map_decides_category_colours_not_the_graph_slots() -> None:
    graph = many_categories(2)
    colors = ColorMap.for_graphs([make_graph([("a", "b", 99.0, "cat01")]), graph], style())
    scene = make_scene(graph, style(color_mode="category"), "light", FigureOptions(colors=colors))
    link = link_colors(scene)
    assert link[1] == to_rgba(CATEGORICAL["light"][0], 0.4)
    assert link[0] == to_rgba(CATEGORICAL["light"][1], 0.4)
