"""Colour tokens: every hex is asserted (the values are the validated data-viz palette)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.render import palette

if TYPE_CHECKING:
    from sankey_studio.models import Theme


def test_categorical_light_hexes_and_order() -> None:
    assert palette.CATEGORICAL["light"] == (
        "#2a78d6",
        "#eb6834",
        "#1baf7a",
        "#eda100",
        "#e87ba4",
        "#008300",
        "#6250d6",
        "#e34948",
    )


def test_categorical_dark_hexes_and_order() -> None:
    assert palette.CATEGORICAL["dark"] == (
        "#3987e5",
        "#d95926",
        "#199e70",
        "#c98500",
        "#d55181",
        "#008300",
        "#9085e9",
        "#e66767",
    )


def test_surface_and_ink_tokens() -> None:
    light, dark = palette.TOKENS["light"], palette.TOKENS["dark"]
    assert (light.surface, light.ink, light.ink_secondary) == ("#fcfcfb", "#0b0b0b", "#52514e")
    assert (light.muted, light.gridline, light.baseline) == ("#898781", "#e1e0d9", "#c3c2b7")
    assert (dark.surface, dark.ink, dark.ink_secondary) == ("#1a1a19", "#f0efec", "#c3c2b7")
    assert (dark.muted, dark.gridline, dark.baseline) == ("#898781", "#2c2c2a", "#383835")


def test_neutral_colours() -> None:
    assert palette.UNCATEGORIZED_COLOR == "#898781"
    assert palette.OTHER_COLOR == {"light": "#52514e", "dark": "#c3c2b7"}
    assert palette.NODE_NEUTRAL == "#898781"
    assert palette.other_color("light") == "#52514e"
    assert palette.other_color("dark") == "#c3c2b7"
    assert palette.HUE_SLOTS == 8


def test_ordinal_ramps_and_mono() -> None:
    assert palette.LAYER_RAMP["light"] == ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b")
    assert palette.LAYER_RAMP["dark"] == (
        "#184f95",
        "#256abf",
        "#3987e5",
        "#6da7ec",
        "#9ec5f4",
        "#cde2fb",
    )
    assert palette.MONO_COLOR == {"light": "#2a78d6", "dark": "#3987e5"}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_ramp_never_uses_the_forbidden_steps(theme: Theme) -> None:
    forbidden = {"light": {"#cde2fb", "#b7d3f6", "#104281"}, "dark": {"#104281", "#0d366b"}}
    assert not set(palette.LAYER_RAMP[theme]) & forbidden[theme]


@pytest.mark.parametrize(
    ("theme", "layer", "step"),
    [
        ("light", 0, 0),
        ("light", 3, 3),
        ("light", 4, 4),
        ("light", 5, 4),
        ("light", 99, 4),
        ("dark", 0, 0),
        ("dark", 4, 4),
        ("dark", 5, 5),
        ("dark", 6, 5),
        ("dark", 99, 5),
    ],
)
def test_layer_colour_is_step_min_layer_k_minus_one(theme: Theme, layer: int, step: int) -> None:
    assert palette.layer_color(theme, layer) == palette.LAYER_RAMP[theme][step]


@pytest.mark.parametrize(
    ("slot", "index"),
    [(0, 0), (1, 1), (6, 6), (7, 7), (8, None), (9, None), (200, None), (-1, None)],
)
def test_slots_zero_to_seven_have_a_hue_the_rest_are_neutral(slot: int, index: int | None) -> None:
    for theme in ("light", "dark"):
        expected = None if index is None else palette.CATEGORICAL[theme][index]
        assert palette.hue(theme, slot) == expected
