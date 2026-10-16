# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Style spec: how a graph and its donut chart look."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from sankey_studio.models.base import (
    _VALUE_FORMAT_RE,
    CATEGORY_MAX,
    HEX_COLOR_RE,
    MAX_COLOR_OVERRIDES,
    MAX_NODE_ORDER,
    NAME_MAX,
    _Model,
)
from sankey_studio.models.fields import NameStr
from sankey_studio.util import category_key, is_reserved_category, normalize_category


class DonutStyle(_Model):
    """Donut chart of value per category."""

    #: all: every entry counted as entered. initial: only first-hop entries (source node =
    #: ``node_in == 0``). terminal: only last-hop entries (sink node = ``node_out == 0``).
    #: Middle entries are ignored by the initial/terminal bases by design.
    basis: Literal["all", "initial", "terminal"] = "all"
    #: Categories drawn in their own colour (top N by value, restricted to colour slots 0-7)
    #: before the rest fold into one patterned ``Other`` slice. Default 6, maximum 8.
    max_slices: int = Field(default=6, ge=2, le=8)
    hole: float = Field(default=0.58, ge=0.3, le=0.85)
    show_percent: bool = True
    #: The slice value (per ``value_format`` and ``value_suffix``) next to the percentage.
    show_value: bool = False
    show_total: bool = True
    sort: Literal["value", "name"] = "value"


def _color_dict(v: dict[str, str], what: str) -> dict[str, str]:
    bad = [name for name, color in v.items() if not HEX_COLOR_RE.match(color)]
    if bad:
        raise ValueError(f"{what} must be #rrggbb; bad entries: {bad[:5]}")
    return v


class StyleSpec(_Model):
    """How the graph looks. Colors come from the validated palette unless overridden."""

    title: str | None = Field(default=None, max_length=NAME_MAX)
    orientation: Literal["h", "v"] = "h"
    #: node: one palette slot per node, by the node's position in the UNFILTERED order
    #: (``SankeyGraph.node_color_slot``; slots 0-7 coloured, the rest neutral); layer: ordinal
    #: ramp by depth; mono: one hue; category: nodes neutral, links coloured by their entry
    #: category. With no categorised link, ``category`` behaves exactly like ``node``.
    color_mode: Literal["node", "layer", "mono", "category"] = "node"
    #: #rrggbb overrides keyed by NODE name (node mode only).
    node_colors: dict[NameStr, str] = Field(default_factory=dict, max_length=MAX_COLOR_OVERRIDES)
    #: #rrggbb overrides keyed by CATEGORY name (matched with ``util.category_key``); used by
    #: ``color_mode="category"``, the donut and the legends. ``Uncategorized``/``Other`` are
    #: not overridable. Kept apart from ``node_colors`` so a node and a category called
    #: "Housing" can be coloured independently.
    category_colors: dict[str, str] = Field(default_factory=dict, max_length=MAX_COLOR_OVERRIDES)
    #: ``color_mode="mono"``: the one colour of every node and link (#rrggbb). None keeps the
    #: palette colour of the theme.
    mono_color: str | None = None
    node_pad: int = Field(default=16, ge=0, le=100)
    node_thickness: int = Field(default=18, ge=1, le=100)
    link_opacity: float = Field(default=0.4, ge=0.05, le=1.0)
    arrangement: Literal["snap", "perpendicular", "freeform", "fixed"] = "snap"
    #: d3-format string for values, e.g. ",.2~f".
    value_format: str = ",.2~f"
    value_suffix: str = Field(default="", max_length=20)
    show_values_in_labels: bool = False
    font_size: int = Field(default=13, ge=8, le=32)
    height: int = Field(default=560, ge=240, le=2400)
    donut: DonutStyle = Field(default_factory=DonutStyle)
    #: Stored node order (post-merge names): layer 0 top to bottom, then layer 1, ... Names that
    #: are not listed rank after all listed ones; names that vanished are ignored. Empty = the
    #: order of the data.
    node_order: list[NameStr] = Field(default_factory=list, max_length=MAX_NODE_ORDER)

    @field_validator("node_order")
    @classmethod
    def _node_order(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("node_order must not repeat a node name")
        return v

    @field_validator("node_colors")
    @classmethod
    def _node_colors(cls, v: dict[str, str]) -> dict[str, str]:
        return _color_dict(v, "node_colors")

    @field_validator("category_colors")
    @classmethod
    def _category_colors(cls, v: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        seen: set[str] = set()
        for name, color in v.items():
            clean = normalize_category(name)
            if not clean or len(clean) > CATEGORY_MAX:
                raise ValueError("category_colors keys must be 1-100 characters")
            if is_reserved_category(clean):
                raise ValueError(
                    "'Uncategorized' and 'Other' are reserved names with fixed colours"
                )
            if category_key(clean) in seen:
                raise ValueError(
                    "category_colors repeats a category (names compare case-insensitively)"
                )
            seen.add(category_key(clean))
            out[clean] = color
        return _color_dict(out, "category_colors")

    @field_validator("mono_color")
    @classmethod
    def _mono_color(cls, v: str | None) -> str | None:
        if v is not None and not HEX_COLOR_RE.match(v):
            raise ValueError("mono_color must be #rrggbb")
        return v

    @field_validator("value_format")
    @classmethod
    def _value_format(cls, v: str) -> str:
        if not _VALUE_FORMAT_RE.match(v):
            raise ValueError("value_format must be a d3-format string such as ',.2~f'")
        return v
