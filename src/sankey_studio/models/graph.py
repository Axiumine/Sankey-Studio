# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The built graph: a plain, columnar dataclass that is never persisted."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sankey_studio.models.base import INDEX_TYPECODE, VALUE_TYPECODE
from sankey_studio.util import RESERVED_CATEGORY_KEYS, category_key

if TYPE_CHECKING:
    from array import array

#: One entry before aggregation: (source name, target name, positive value, category or None).
RawLink = tuple[str, str, float, str | None]

Theme = Literal["light", "dark"]


@dataclass(frozen=True, slots=True, eq=False)
class SankeyGraph:
    """A draw-ready graph in columnar form.

    ``link_source`` / ``link_target`` index into ``node_names``. ``eq=False``: identity equality
    and hash (the array fields are unhashable), so a graph can key an ``lru_cache``.

    Topology (nodes, layers, node sums) comes from (source, target) PAIR totals and is identical
    with or without categories. Links are then unique per (source, target, category): a pair whose
    entries carry several categories is split into parallel links. ``node_layers`` is the
    longest-path depth from any source node (0-based).

    ONE representation of "no category": ``link_category == -1``, always. ``categories`` holds
    only REAL categories that appear on the final links, in first-appearance order of the
    unfiltered stream, display spelling = first seen. ``UNCATEGORIZED`` is a render-time label
    for the ``-1`` bucket and never appears in ``categories``. The donut is offered iff
    ``len(categories) > 0``.

    Colours follow the entity, not its rank in the current view: ``node_color_slot[i]`` is the
    index of node ``i`` in the unfiltered, post-merge, first-appearance node order, and
    ``category_color_slot[c]`` is the index of category ``c`` among all real categories of the
    unfiltered stream. A palette hue exists for slots 0-7; higher slots are neutral. Filters
    (``hide_nodes``, ``min_link_value``, ``top_links``) therefore never repaint survivors.

    Column typecodes: ``link_source/target/category`` are ``array('i')``, ``link_value`` is
    ``array('d')``. Fields are validated for length/typecode/range in ``__post_init__``, which also
    refuses reserved names and case/NFC duplicates (``util.category_key``) in ``categories``.
    """

    node_names: tuple[str, ...]
    node_layers: tuple[int, ...]
    node_color_slot: tuple[int, ...]
    node_in: tuple[float, ...]
    node_out: tuple[float, ...]
    link_source: array[int]
    link_target: array[int]
    link_value: array[float]
    link_category: array[int]
    categories: tuple[str, ...] = ()
    category_color_slot: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self._check_shapes()
        self._check_ranges()
        self._check_categories()

    def _check_shapes(self) -> None:
        n = len(self.node_names)
        node_cols = (self.node_layers, self.node_color_slot, self.node_in, self.node_out)
        if any(len(col) != n for col in node_cols):
            raise ValueError("node columns must all have one entry per node")
        links = len(self.link_value)
        link_cols = (self.link_source, self.link_target, self.link_category)
        if any(len(col) != links for col in link_cols):
            raise ValueError("link columns must all have one entry per link")
        if len(self.category_color_slot) != len(self.categories):
            raise ValueError("category_color_slot needs one entry per category")
        for name, col, code in (
            ("link_source", self.link_source, INDEX_TYPECODE),
            ("link_target", self.link_target, INDEX_TYPECODE),
            ("link_category", self.link_category, INDEX_TYPECODE),
            ("link_value", self.link_value, VALUE_TYPECODE),
        ):
            if getattr(col, "typecode", None) != code:
                raise ValueError(f"{name} must be array('{code}')")

    def _check_ranges(self) -> None:
        if not self.link_value:
            return
        n = len(self.node_names)
        for name, col in (("link_source", self.link_source), ("link_target", self.link_target)):
            if min(col) < 0 or max(col) >= n:
                raise ValueError(f"{name} must index node_names")
        if min(self.link_category) < -1 or max(self.link_category) >= len(self.categories):
            raise ValueError("link_category must be -1 (uncategorised) or index categories")

    def _check_categories(self) -> None:
        """``categories`` holds REAL categories only: no reserved names, no case/NFC duplicates."""
        keys = [category_key(name) for name in self.categories]
        if "" in keys:
            raise ValueError("categories must not contain an empty name")
        if any(key in RESERVED_CATEGORY_KEYS for key in keys):
            raise ValueError("categories must not contain the reserved names Uncategorized/Other")
        if len(set(keys)) != len(keys):
            raise ValueError("categories must be unique (names compare case-insensitively)")

    @property
    def n_nodes(self) -> int:
        return len(self.node_names)

    @property
    def n_links(self) -> int:
        return len(self.link_value)

    @property
    def has_categories(self) -> bool:
        """True when at least one drawn link is categorised (the donut is offered)."""
        return len(self.categories) > 0
