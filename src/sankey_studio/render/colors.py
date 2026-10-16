# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``ColorMap``: which colour an entity gets. Pure: no plotly, no theme inside the map.

The map stores SLOTS (stable per entity, see ``SankeyGraph.node_color_slot`` and
``category_color_slot``) and user overrides; a hex is only resolved when a theme is given.
Slots 0-7 are palette hues, higher slots are neutral. ``has_hue`` is the ONE test for "this
category is drawn in its own colour"; the donut fold and the legend ``Other`` both use it, so a
re-ranked compare-view map can never make hue and fold disagree.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING

from sankey_studio.render.palette import HUE_SLOTS, NODE_NEUTRAL, OTHER_COLOR, hue
from sankey_studio.util import category_key

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sankey_studio.models import SankeyGraph, StyleSpec, Theme


def safe_key(name: str) -> str | None:
    """``category_key`` or ``None`` for a name that is not a valid category."""
    try:
        return category_key(name)
    except ValueError:
        return None


@lru_cache(maxsize=1024)
def to_rgba(color: str, opacity: float) -> str:
    """``#rrggbb`` and an opacity as ``rgba(r, g, b, a)`` (cached: links share their strings)."""
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {opacity:g})"


def _category_overrides(style: StyleSpec) -> dict[str, str]:
    return {category_key(name): color for name, color in style.category_colors.items()}


@dataclass(frozen=True, slots=True, eq=False)
class ColorMap:
    """Slots and overrides of nodes (by name) and categories (by ``category_key``)."""

    node_slots: Mapping[str, int] = field(default_factory=dict)
    node_overrides: Mapping[str, str] = field(default_factory=dict)
    category_slots: Mapping[str, int] = field(default_factory=dict)
    category_overrides: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def for_graph(cls, graph: SankeyGraph, style: StyleSpec) -> ColorMap:
        """Slots from the graph itself: filters never repaint survivors."""
        return cls(
            node_slots={name: graph.node_color_slot[i] for i, name in enumerate(graph.node_names)},
            node_overrides=dict(style.node_colors),
            category_slots={
                category_key(name): graph.category_color_slot[i]
                for i, name in enumerate(graph.categories)
            },
            category_overrides=_category_overrides(style),
        )

    @classmethod
    def for_graphs(cls, graphs: Sequence[SankeyGraph], style: StyleSpec) -> ColorMap:
        """ONE category map for several graphs (compare view).

        Categories are the union over all graphs (identity = ``category_key``), ranked by summed
        link value (ties: first appearance); the rank is the slot, so a category has one hue in
        every card. ``style`` is the first compared graph's style: its overrides apply to all.
        """
        first_seen: dict[str, None] = {}
        totals: defaultdict[str, float] = defaultdict(float)
        for graph in graphs:
            keys = [category_key(name) for name in graph.categories]
            first_seen.update(dict.fromkeys(keys))
            for link, category in enumerate(graph.link_category):
                if category >= 0:
                    totals[keys[category]] += graph.link_value[link]
        ranked = sorted(first_seen, key=lambda key: -totals[key])
        return cls(
            category_slots={key: rank for rank, key in enumerate(ranked)},
            category_overrides=_category_overrides(style),
        )

    def node_color(self, name: str, theme: Theme) -> str:
        """Override, else the palette hue of the node's slot, else the neutral node colour."""
        override = self.node_overrides.get(name)
        if override is not None:
            return override
        slot = self.node_slots.get(name)
        return NODE_NEUTRAL if slot is None else (hue(theme, slot) or NODE_NEUTRAL)

    def category_color(self, name: str, theme: Theme) -> str:
        """Override, else the hue of the slot, else the neutral ``Other`` colour of the theme."""
        neutral = OTHER_COLOR[theme]
        key = safe_key(name)
        if key is None:
            return neutral
        override = self.category_overrides.get(key)
        if override is not None:
            return override
        slot = self.category_slots.get(key)
        return neutral if slot is None else (hue(theme, slot) or neutral)

    def has_hue(self, category: str) -> bool:
        """True iff ``category`` is drawn in its own colour: an override, or a slot below 8."""
        key = safe_key(category)
        if key is None:
            return False
        if key in self.category_overrides:
            return True
        return self.category_slots.get(key, HUE_SLOTS) < HUE_SLOTS
