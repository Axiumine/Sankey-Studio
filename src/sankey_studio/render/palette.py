"""Colour tokens: constants and lookups only (values exactly as in the data-viz palette).

The categorical palette keeps its fixed order (the order is the colour-blind-safety mechanism).
Text never wears a data colour: labels use the ink tokens. Slots 0-7 are the eight hues; a
ninth hue is never generated, anything beyond slot 7 is neutral.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from sankey_studio.models import Theme

#: Slots 0-7 map to these hues; slots >= 8 are neutral.
HUE_SLOTS: Final = 8

CATEGORICAL: Final[dict[Theme, tuple[str, ...]]] = {
    "light": (
        "#2a78d6",  # blue
        "#eb6834",  # orange
        "#1baf7a",  # aqua
        "#eda100",  # yellow
        "#e87ba4",  # magenta
        "#008300",  # green
        "#6250d6",  # violet
        "#e34948",  # red
    ),
    "dark": (
        "#3987e5",
        "#d95926",
        "#199e70",
        "#c98500",
        "#d55181",
        "#008300",
        "#9085e9",
        "#e66767",
    ),
}


@dataclass(frozen=True, slots=True)
class Tokens:
    """Surface and ink tokens of one theme."""

    surface: str
    ink: str
    ink_secondary: str
    muted: str
    gridline: str
    baseline: str


TOKENS: Final[dict[Theme, Tokens]] = {
    "light": Tokens(
        surface="#fcfcfb",
        ink="#0b0b0b",
        ink_secondary="#52514e",
        muted="#898781",
        gridline="#e1e0d9",
        baseline="#c3c2b7",
    ),
    "dark": Tokens(
        surface="#1a1a19",
        ink="#f0efec",
        ink_secondary="#c3c2b7",
        muted="#898781",
        gridline="#2c2c2a",
        baseline="#383835",
    ),
}

#: The "no category" bucket: muted ink, the same in both themes.
UNCATEGORIZED_COLOR: Final = "#898781"
#: The donut fold bucket and the neutral category colour: secondary ink of the theme.
OTHER_COLOR: Final[dict[Theme, str]] = {"light": "#52514e", "dark": "#c3c2b7"}
#: Nodes without a hue (slot >= 8, or ``color_mode="category"``): the muted token.
NODE_NEUTRAL: Final = "#898781"

#: Ordinal ramp of ``color_mode="layer"`` (blue, light to dark steps): 5 steps on the light
#: surface (250/350/450/550/700), 6 on the dark surface (600/500/400/300/200/100).
LAYER_RAMP: Final[dict[Theme, tuple[str, ...]]] = {
    "light": ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"),
    "dark": ("#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"),
}
#: ``color_mode="mono"``: step 450 on light, step 400 on dark.
MONO_COLOR: Final[dict[Theme, str]] = {"light": "#2a78d6", "dark": "#3987e5"}


def other_color(theme: Theme) -> str:
    return OTHER_COLOR[theme]


def layer_color(theme: Theme, layer: int) -> str:
    """Ramp step of a 0-based layer: step ``min(layer, K - 1)``."""
    ramp = LAYER_RAMP[theme]
    return ramp[min(layer, len(ramp) - 1)]


def hue(theme: Theme, slot: int) -> str | None:
    """The palette hue of a colour slot, or ``None`` for a neutral slot (>= 8 or negative)."""
    if 0 <= slot < HUE_SLOTS:
        return CATEGORICAL[theme][slot]
    return None
