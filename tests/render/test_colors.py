"""``ColorMap``: slots, overrides, ``has_hue``, and the compare-view ranking."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.render.colors import ColorMap, safe_key, to_rgba
from sankey_studio.render.palette import CATEGORICAL, NODE_NEUTRAL, OTHER_COLOR
from tests.graph_support import make_graph
from tests.render.support import many_categories, style

if TYPE_CHECKING:
    from sankey_studio.models import RawLink


class Hue(NamedTuple):
    slot: int
    has_hue: bool


@pytest.mark.parametrize(
    "case",
    [Hue(0, True), Hue(6, True), Hue(7, True), Hue(8, False), Hue(9, False), Hue(199, False)],
)
def test_slots_below_eight_have_a_hue(case: Hue) -> None:
    graph = many_categories(case.slot + 1)
    colors = ColorMap.for_graph(graph, style())
    name = graph.categories[case.slot]
    assert graph.category_color_slot[case.slot] == case.slot
    assert colors.has_hue(name) is case.has_hue
    expected = CATEGORICAL["light"][case.slot] if case.has_hue else OTHER_COLOR["light"]
    assert colors.category_color(name, "light") == expected


def test_an_unknown_or_invalid_name_has_no_hue() -> None:
    colors = ColorMap.for_graph(many_categories(3), style())
    assert colors.has_hue("nobody") is False
    assert colors.has_hue("bad\x00name") is False
    assert colors.category_color("nobody", "dark") == OTHER_COLOR["dark"]
    assert colors.category_color("bad\x00name", "dark") == OTHER_COLOR["dark"]
    assert safe_key("bad\x00name") is None
    assert safe_key("  Food ") == "food"


@pytest.mark.parametrize("lookup", ["cat01", "CAT01", " Cat01 ", "cat01\t"])
def test_lookups_use_the_category_key(lookup: str) -> None:
    colors = ColorMap.for_graph(many_categories(3), style())
    assert colors.has_hue(lookup) is True
    assert colors.category_color(lookup, "light") == CATEGORICAL["light"][1]


def test_nfc_variants_resolve_to_one_entry() -> None:
    graph = make_graph([("A", "B", 1.0, "Café")])
    colors = ColorMap.for_graph(graph, style())
    assert colors.has_hue("Café")
    assert colors.category_color("CAFÉ", "light") == CATEGORICAL["light"][0]


def test_an_override_gives_a_hue_to_a_slot_nine_category() -> None:
    graph = many_categories(10)
    plain_map = ColorMap.for_graph(graph, style())
    assert plain_map.has_hue("cat09") is False
    colors = ColorMap.for_graph(graph, style(category_colors={"CAT09": "#112233"}))
    assert colors.has_hue("cat09") is True
    assert colors.category_color("cat09", "light") == "#112233"
    assert colors.category_color("cat09", "dark") == "#112233"


def test_an_override_beats_the_slot() -> None:
    graph = many_categories(3)
    colors = ColorMap.for_graph(graph, style(category_colors={"cat00": "#abcdef"}))
    assert colors.category_color("cat00", "light") == "#abcdef"
    assert colors.category_color("cat01", "light") == CATEGORICAL["light"][1]


def test_node_colours_follow_the_graph_slots_and_overrides() -> None:
    graph = make_graph([(f"n{i}", f"n{i + 1}", 1.0, None) for i in range(10)])
    colors = ColorMap.for_graph(graph, style(node_colors={"n3": "#010203"}))
    assert colors.node_color("n0", "light") == CATEGORICAL["light"][0]
    assert colors.node_color("n7", "dark") == CATEGORICAL["dark"][7]
    assert colors.node_color("n8", "light") == NODE_NEUTRAL
    assert colors.node_color("n10", "light") == NODE_NEUTRAL
    assert colors.node_color("n3", "light") == "#010203"
    assert colors.node_color("unknown", "light") == NODE_NEUTRAL


def test_node_and_category_overrides_are_separate_dictionaries() -> None:
    graph = make_graph([("Housing", "Out", 1.0, "Housing")])
    colors = ColorMap.for_graph(graph, style(category_colors={"Housing": "#111111"}))
    assert colors.node_color("Housing", "light") == CATEGORICAL["light"][0]
    assert colors.category_color("Housing", "light") == "#111111"
    colors = ColorMap.for_graph(graph, style(node_colors={"Housing": "#222222"}))
    assert colors.node_color("Housing", "light") == "#222222"
    assert colors.category_color("Housing", "light") == CATEGORICAL["light"][0]


def test_the_two_themes_use_their_own_hexes() -> None:
    colors = ColorMap.for_graph(many_categories(2), style())
    assert colors.category_color("cat01", "light") != colors.category_color("cat01", "dark")
    assert colors.category_color("cat01", "dark") == CATEGORICAL["dark"][1]


def test_to_rgba_formats_channels_and_opacity() -> None:
    assert to_rgba("#2a78d6", 0.4) == "rgba(42, 120, 214, 0.4)"
    assert to_rgba("#000000", 1.0) == "rgba(0, 0, 0, 1)"
    assert to_rgba("#ffffff", 0.05) == "rgba(255, 255, 255, 0.05)"
    assert to_rgba("#2a78d6", 0.4) is to_rgba("#2a78d6", 0.4)


class Union(NamedTuple):
    first: list[RawLink]
    second: list[RawLink]
    ranked: list[str]


UNIONS = [
    Union(
        [("a", "b", 1.0, "x"), ("a", "c", 5.0, "y")],
        [("a", "b", 3.0, "x"), ("a", "c", 1.0, "z")],
        ["y", "x", "z"],
    ),
    Union([("a", "b", 2.0, "x"), ("a", "c", 2.0, "y")], [("a", "b", 2.0, "z")], ["x", "y", "z"]),
    Union([("a", "b", 2.0, "y"), ("a", "c", 2.0, "x")], [("a", "b", 2.0, "X")], ["x", "y"]),
    Union([("a", "b", 9.0, "q")], [("a", "b", 1.0, "w"), ("a", "c", 9.0, "q")], ["q", "w"]),
]


@pytest.mark.parametrize("case", UNIONS)
def test_for_graphs_ranks_the_union_by_summed_value_then_first_appearance(case: Union) -> None:
    graphs = [make_graph(case.first), make_graph(case.second)]
    colors = ColorMap.for_graphs(graphs, style())
    ranked = sorted(colors.category_slots, key=lambda key: colors.category_slots[key])
    assert ranked == case.ranked
    assert [colors.category_slots[key] for key in ranked] == list(range(len(ranked)))


def test_for_graphs_gives_one_hue_per_category_in_every_card() -> None:
    first = make_graph([("a", "b", 1.0, "Food"), ("a", "c", 9.0, "Rent")])
    second = make_graph([("a", "b", 4.0, "food")])
    colors = ColorMap.for_graphs([first, second], style())
    assert colors.category_color("Food", "light") == colors.category_color("FOOD", "light")
    assert colors.category_color("Rent", "light") == CATEGORICAL["light"][0]
    assert colors.category_color("Food", "light") == CATEGORICAL["light"][1]


def test_for_graphs_uses_the_given_style_overrides_and_has_no_node_colours() -> None:
    graph = make_graph([("a", "b", 1.0, "x")])
    colors = ColorMap.for_graphs(
        [graph], style(category_colors={"x": "#445566"}, node_colors={"a": "#000001"})
    )
    assert colors.category_color("x", "light") == "#445566"
    assert colors.node_color("a", "light") == NODE_NEUTRAL
    assert colors.node_slots == {}
    assert colors.node_overrides == {}


def test_for_graphs_ignores_uncategorised_links_when_summing() -> None:
    graph = make_graph([("a", "b", 100.0, None), ("a", "c", 1.0, "x"), ("a", "d", 2.0, "y")])
    colors = ColorMap.for_graphs([graph], style())
    assert colors.category_slots == {"y": 0, "x": 1}


def test_for_graphs_of_nothing_is_empty() -> None:
    colors = ColorMap.for_graphs([], style())
    assert colors.category_slots == {}
    assert colors.has_hue("x") is False


def test_a_colour_map_compares_and_hashes_by_identity() -> None:
    first = ColorMap.for_graph(many_categories(2), style())
    second = ColorMap.for_graph(many_categories(2), style())
    assert first != second
    assert {first: 1}[first] == 1
    assert hash(first) != hash(second)
