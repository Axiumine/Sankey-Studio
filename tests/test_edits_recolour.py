# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``edits.recolour``: the pins that keep the colours when a row reorder moves the slots."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.edits.recolour import pins_for
from sankey_studio.errors import SourceEditRefused
from sankey_studio.graph import build_graph
from sankey_studio.models import StylePins, StyleSpec, TransformSpec
from sankey_studio.models.base import MAX_COLOR_OVERRIDES
from sankey_studio.sources.base import Diagnostics

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph

Row = tuple[str, str, float, str | None]
A_FIRST: list[Row] = [("a", "x", 1, None), ("b", "y", 1, None)]
B_FIRST: list[Row] = [("b", "y", 1, None), ("a", "x", 1, None)]
RED_FIRST: list[Row] = [("a", "x", 1, "Red"), ("a", "y", 1, "Blue")]
BLUE_FIRST: list[Row] = [("a", "y", 1, "Blue"), ("a", "x", 1, "Red")]
#: The light-theme hues of slots 0-3.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
NEUTRAL = "#898781"


def graph_of(rows: list[Row]) -> SankeyGraph:
    return build_graph(rows, TransformSpec(), max_raw_links=1000, diag=Diagnostics())


def style(**fields: object) -> StyleSpec:
    return StyleSpec.model_validate(fields)


def pins(before: list[Row], after: list[Row], **fields: object) -> StylePins | None:
    return pins_for(graph_of(before), graph_of(after), style(**fields))


def test_swapped_first_appearance_pins_the_hues_of_the_nodes_in_node_mode() -> None:
    result = pins(A_FIRST, B_FIRST, color_mode="node")
    assert result == StylePins(node_colors={"a": BLUE, "x": ORANGE, "b": AQUA, "y": YELLOW})


def test_node_mode_is_the_default() -> None:
    assert pins(A_FIRST, B_FIRST) is not None


def test_the_same_order_needs_no_pins() -> None:
    assert pins(A_FIRST, A_FIRST) is None


@pytest.mark.parametrize("mode", ["layer", "mono"])
def test_layer_and_mono_never_need_pins(mode: str) -> None:
    assert pins(A_FIRST, B_FIRST, color_mode=mode) is None


def test_a_name_with_a_pinned_colour_is_left_alone() -> None:
    all_pinned = dict.fromkeys(("a", "b", "x", "y"), "#112233")
    assert pins(A_FIRST, B_FIRST, node_colors=all_pinned) is None
    some = dict.fromkeys(("a", "b", "x"), "#112233")
    assert pins(A_FIRST, B_FIRST, node_colors=some) == StylePins(node_colors={"y": YELLOW})


def wide(offset: int) -> list[Row]:
    """Ten flows in a ring-free chain; ``offset`` rotates the row order."""
    rows: list[Row] = [(f"s{i}", f"t{i}", 1, None) for i in range(10)]
    return rows[offset:] + rows[:offset]


def test_neutral_slots_are_one_colour() -> None:
    """Slots 8 and up are all the neutral grey: swapping two of them pins nothing."""
    base = wide(0)
    swapped = [*base[:8], base[9], base[8]]
    assert pins(base, swapped) is None


def test_a_node_that_turns_from_neutral_to_a_hue_is_pinned_neutral() -> None:
    base = wide(0)
    moved = [base[8], *base[:8], base[9]]
    result = pins(base, moved)
    assert result is not None
    assert result.node_colors["s0"] == BLUE
    assert result.node_colors["s1"] == AQUA
    assert (result.node_colors["s8"], result.node_colors["t8"]) == (NEUTRAL, NEUTRAL)
    assert "s4" not in result.node_colors  # neutral on both sides


def test_a_node_that_only_one_side_has_is_ignored() -> None:
    assert pins(A_FIRST, [*A_FIRST, ("c", "z", 1, None)]) is None


def test_category_mode_pins_the_category_hues() -> None:
    result = pins(RED_FIRST, BLUE_FIRST, color_mode="category")
    assert result == StylePins(category_colors={"Red": BLUE, "Blue": ORANGE})
    assert pins(RED_FIRST, RED_FIRST, color_mode="category") is None
    assert pins(A_FIRST, B_FIRST, color_mode="category") is None


def test_category_mode_ignores_a_reorder_that_keeps_the_category_order() -> None:
    first: list[Row] = [("a", "x", 1, "Red"), ("b", "y", 1, "Blue"), ("c", "z", 1, "Red")]
    second: list[Row] = [first[0], first[2], first[1]]
    assert pins(first, second, color_mode="category") is None
    assert pins(first, second) is not None


def test_pinned_categories_are_ignored_case_insensitively() -> None:
    both = {"red": "#aa0000", "BLUE": "#0000aa"}
    assert pins(RED_FIRST, BLUE_FIRST, color_mode="category", category_colors=both) is None
    one = {"red": "#aa0000"}
    result = pins(RED_FIRST, BLUE_FIRST, color_mode="category", category_colors=one)
    assert result == StylePins(category_colors={"Blue": ORANGE})


def test_a_category_that_only_one_side_has_is_ignored() -> None:
    after = [*RED_FIRST, ("a", "z", 1, "Green")]
    assert pins(RED_FIRST, after, color_mode="category") is None


@pytest.mark.parametrize(
    ("existing", "allowed"), [(MAX_COLOR_OVERRIDES - 4, True), (MAX_COLOR_OVERRIDES - 3, False)]
)
def test_the_pins_must_fit_in_the_style(existing: int, allowed: bool) -> None:
    colors = {f"n{i}": "#112233" for i in range(existing)}
    if allowed:
        assert pins(A_FIRST, B_FIRST, node_colors=colors) is not None
        return
    with pytest.raises(SourceEditRefused) as refused:
        pins(A_FIRST, B_FIRST, node_colors=colors)
    assert refused.value.reason == "would_recolour"


def test_the_category_pins_must_fit_in_the_style() -> None:
    colors = {f"c{i}": "#112233" for i in range(MAX_COLOR_OVERRIDES - 1)}
    with pytest.raises(SourceEditRefused):
        pins(RED_FIRST, BLUE_FIRST, color_mode="category", category_colors=colors)
