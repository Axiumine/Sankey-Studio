"""Layout pieces shared by both charts: every constant is pinned, in both themes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.render.layout import (
    FONT_FAMILY,
    LEGEND_BAND,
    MARGIN,
    NOTE_BAND,
    TITLE_BAND,
    TRANSPARENT,
    base_layout,
    font,
    margin,
    note_annotation,
    title_block,
)
from sankey_studio.render.palette import TOKENS
from sankey_studio.render.sankey import _share, empty_annotation
from tests.render.support import style

if TYPE_CHECKING:
    from sankey_studio.models import Theme

SYSTEM_FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def test_constants() -> None:
    assert FONT_FAMILY == SYSTEM_FONT
    assert TRANSPARENT == "rgba(0, 0, 0, 0)"
    assert (MARGIN, TITLE_BAND, LEGEND_BAND, NOTE_BAND) == (16, 36, 40, 28)


def test_font_block() -> None:
    assert font("#123456", 17) == {"family": SYSTEM_FONT, "size": 17, "color": "#123456"}


class Room(NamedTuple):
    title: bool
    legend: bool
    note: bool
    top: int
    bottom: int


ROOMS = [
    Room(False, False, False, 16, 16),
    Room(True, False, False, 52, 16),
    Room(False, True, False, 56, 16),
    Room(False, False, True, 16, 44),
    Room(True, True, True, 92, 44),
]


@pytest.mark.parametrize("case", ROOMS)
def test_margins_make_room_for_title_legend_and_note(case: Room) -> None:
    result = margin(style(title="T" if case.title else None), legend=case.legend, note=case.note)
    assert result == {"l": 16, "r": 16, "t": case.top, "b": case.bottom}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_base_layout_is_fully_explicit(theme: Theme) -> None:
    tokens = TOKENS[theme]
    text = {"family": SYSTEM_FONT, "size": 14, "color": tokens.ink}
    assert base_layout(style(font_size=14), theme) == {
        "autosize": True,
        "font": text,
        "paper_bgcolor": tokens.surface,
        "plot_bgcolor": tokens.surface,
        "hoverlabel": {"bgcolor": tokens.surface, "bordercolor": tokens.muted, "font": text},
        "modebar": {
            "bgcolor": "rgba(0, 0, 0, 0)",
            "color": tokens.muted,
            "activecolor": tokens.ink,
        },
        "legend": {"font": text, "bgcolor": "rgba(0, 0, 0, 0)"},
    }


def test_title_block_is_top_left_in_ink_and_escaped() -> None:
    titled = style(title="a<b", font_size=10)
    block = title_block("a<b", titled, "dark")
    assert block == {
        "text": "a&lt;b",
        "font": {"family": SYSTEM_FONT, "size": 13, "color": TOKENS["dark"].ink},
        "x": 0,
        "xref": "container",
        "xanchor": "left",
        "y": 1,
        "yref": "container",
        "yanchor": "top",
        "pad": {"l": 16, "t": 16},
    }
    assert base_layout(titled, "dark")["title"] == block


def test_note_annotation_is_small_secondary_ink_text_under_the_plot() -> None:
    note = note_annotation("5 < 6", style(font_size=13), "light")
    assert note == {
        "text": "5 &lt; 6",
        "xref": "paper",
        "yref": "paper",
        "x": 1,
        "y": 0,
        "xanchor": "right",
        "yanchor": "top",
        "showarrow": False,
        "font": {"family": SYSTEM_FONT, "size": 12, "color": TOKENS["light"].ink_secondary},
    }
    assert note_annotation("n", style(font_size=8), "dark")["font"]["size"] == 8


def test_empty_annotation_is_centred_secondary_ink() -> None:
    expected: dict[str, Any] = {
        "text": "No entries to draw",
        "xref": "paper",
        "yref": "paper",
        "x": 0.5,
        "y": 0.5,
        "showarrow": False,
        "font": {"family": SYSTEM_FONT, "size": 13, "color": TOKENS["dark"].ink_secondary},
    }
    assert empty_annotation(style(), "dark") == expected


def test_share_guards_a_zero_total() -> None:
    assert _share(1.0, 0.0) == "0.0%"
    assert _share(1.0, -1.0) == "0.0%"
    assert _share(1.0, 3.0) == "33.3%"
    assert _share(1.0, 8.0) == "12.5%"
    assert _share(0.0005, 1.0) == "0.1%"
