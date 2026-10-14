"""Pins that keep the colours of a chart when a row reorder moves the colour slots.

``SankeyGraph.node_color_slot`` is the first-appearance id of a node and the category slots are
first-seen order, so re-sorting the rows can swap hues (slots 0-7 are palette hues, higher slots
are neutral). The row reorder of a node drag must not repaint the chart (rule 34), so the edit
answers the light-theme hex of every name whose hue would move (``StylePins``) and the browser
pins them in ``style.node_colors`` (mode ``node``) or ``style.category_colors`` (mode
``category``) together with the new rows. ``layer`` and ``mono`` never recolour. A pinned colour
is one fixed hex in both themes, like any colour the person sets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import StylePins
from sankey_studio.models.base import MAX_COLOR_OVERRIDES
from sankey_studio.render.palette import HUE_SLOTS, NODE_NEUTRAL, OTHER_COLOR, hue
from sankey_studio.util import category_key

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sankey_studio.models import SankeyGraph, StyleSpec

#: ``key -> (name, slot)``: the key identifies the entity, the name is what a style pins.
Slots = dict[str, tuple[str, int]]


def _hue(slot: int) -> int | None:
    """The palette hue of a slot; every neutral slot (>= ``HUE_SLOTS``) is the same colour."""
    return slot if slot < HUE_SLOTS else None


def _moved(before: Slots, after: Slots, pinned: Mapping[str, str], neutral: str) -> dict[str, str]:
    """``name -> colour`` it has in ``before``, for a name on both sides, without a pinned
    colour, whose hue changes."""
    return {
        name: hue("light", slot) or neutral
        for key, (name, slot) in before.items()
        if key in after and key not in pinned and _hue(slot) != _hue(after[key][1])
    }


def _node_slots(graph: SankeyGraph) -> Slots:
    return {
        name: (name, slot)
        for name, slot in zip(graph.node_names, graph.node_color_slot, strict=True)
    }


def _category_slots(graph: SankeyGraph) -> Slots:
    return {
        category_key(name): (name, slot)
        for name, slot in zip(graph.categories, graph.category_color_slot, strict=True)
    }


def _fits(existing: Mapping[str, str], moved: Mapping[str, str]) -> bool:
    return len(existing) + len(moved) <= MAX_COLOR_OVERRIDES


def pins_for(before: SankeyGraph, after: SankeyGraph, style: StyleSpec) -> StylePins | None:
    """The pins that keep every colour of ``before`` in ``after``; ``None`` when none is needed.

    Names that already have a pinned colour in ``style`` are left alone. ``SourceEditRefused``
    (``would_recolour``) when the pins would not fit in the style (``MAX_COLOR_OVERRIDES``).
    """
    if style.color_mode == "node":
        existing: Mapping[str, str] = style.node_colors
        moved = _moved(_node_slots(before), _node_slots(after), existing, NODE_NEUTRAL)
        pins = StylePins(node_colors=moved)
    elif style.color_mode == "category":
        existing = style.category_colors
        pinned = {category_key(name): color for name, color in existing.items()}
        moved = _moved(
            _category_slots(before), _category_slots(after), pinned, OTHER_COLOR["light"]
        )
        pins = StylePins(category_colors=moved)
    else:
        return None
    if not _fits(existing, moved):
        raise SourceEditRefused("would_recolour")
    return None if pins.empty else pins
