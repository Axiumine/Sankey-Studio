# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Edits to the data of a graph and the answer to them (the write-back contract).

``AddEntry``, ``SetCategory`` and ``ReorderNodes`` are what the editor can do to a graph's
entries; ``EditRequest`` carries one together with the current draft, ``EditOutcome`` says where
the edit went. These models hold NO behaviour about consent: the target key and the effective
preference are computed by ``edits.target`` from the settings.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from sankey_studio.models.base import HEX_COLOR_RE, MAX_COLOR_OVERRIDES, MAX_NODE_ORDER, _Model
from sankey_studio.models.fields import NameStr, OptUserCategory
from sankey_studio.models.graphs import GraphDraft
from sankey_studio.models.sources import SourceSpec

#: Why an edit stayed in the graph (or was refused). Stable: the browser switches on these.
Reason = Literal[
    "preference",
    "read_only_mode",
    "order_in_graph",
    "no_consent",
    "no_match",
    "unsupported_format",
    "file_too_large",
    "cannot_verify",
    "unreadable",
    "unrepresentable",
    "too_many",
    "aggregate_mode",
    "source_incomplete",
    "no_category_field",
    "no_value_field",
    "filter_not_equality",
    "field_conflict",
    "too_many_aliases",
    "reserved_collection",
    "unsafe_value",
    "limit_reached",
    "too_many_documents",
    "permission_denied",
    "write_rejected",
    "would_recolour",
]
#: Reasons that need no notice: the person chose them or they are the normal case.
SILENT_REASONS = frozenset({"preference", "order_in_graph"})


class AddEntry(_Model):
    """Add one flow."""

    op: Literal["add_entry"]
    source: NameStr
    target: NameStr
    value: float = Field(gt=0, allow_inf_nan=False)
    category: OptUserCategory = None

    @model_validator(mode="after")
    def _distinct_ends(self) -> AddEntry:
        if self.source == self.target:
            raise ValueError("source and target must differ")
        return self


class SetCategory(_Model):
    """Give the entries of one (source, target) pair a category; ``None`` clears it."""

    op: Literal["set_category"]
    source: NameStr
    target: NameStr
    #: Required (no default): an omission is never read as "clear".
    category: OptUserCategory


class ReorderNodes(_Model):
    """Store a node order (global: layer 0 top to bottom, then layer 1, ...)."""

    op: Literal["reorder"]
    order: list[NameStr] = Field(max_length=MAX_NODE_ORDER)

    @model_validator(mode="after")
    def _no_repeats(self) -> ReorderNodes:
        if len(set(self.order)) != len(self.order):
            raise ValueError("order must not repeat a node name")
        return self


SourceEdit = Annotated[AddEntry | SetCategory | ReorderNodes, Field(discriminator="op")]


class EditRequest(_Model):
    """Body of ``POST /edits/plan`` and ``POST /edits/write``."""

    draft: GraphDraft
    edit: SourceEdit


class StylePins(_Model):
    """Colours to pin in the style so that a row reorder does not repaint the chart.

    Hex colours are the light-theme hues the nodes (``node_colors``) or categories
    (``category_colors``) had before the rows moved. The browser merges them into the style
    together with the new source, in the same history step.
    """

    node_colors: dict[NameStr, str] = Field(default_factory=dict, max_length=MAX_COLOR_OVERRIDES)
    category_colors: dict[str, str] = Field(default_factory=dict, max_length=MAX_COLOR_OVERRIDES)

    @field_validator("node_colors", "category_colors")
    @classmethod
    def _hex_colors(cls, v: dict[str, str]) -> dict[str, str]:
        if not all(HEX_COLOR_RE.match(color) for color in v.values()):
            raise ValueError("pinned colours must be #rrggbb")
        return v

    @property
    def empty(self) -> bool:
        return not (self.node_colors or self.category_colors)


class EditOutcome(_Model):
    """Where an edit went and what the browser must do next."""

    where: Literal["draft", "file", "mongo", "graph"]
    #: True only after ``/write`` changed a file or a collection.
    written: bool = False
    consent: Literal["none", "ask", "granted"] = "none"
    reason: Reason | None = None
    #: One fixed English sentence (``edits.reasons``); absent for ``SILENT_REASONS``.
    notice: str | None = None
    #: Display text such as ``budget/2025.csv`` or ``main / shop.flows``.
    target: str | None = None
    #: Opaque consent key, set when ``where`` is ``file`` or ``mongo``; the browser stores it
    #: verbatim in ``write_back.target`` when the person agrees.
    target_key: str | None = None
    #: Rows or documents changed or added.
    changed: int = 0
    #: ``where="draft"``: the whole new spec; a file written: the spec with pins; else ``None``.
    source: SourceSpec | None = None
    #: What the browser does with ``transform.entry_categories`` after a data write.
    override: Literal["drop", "set"] | None = None
    #: A row reorder that moved colour slots: pins that keep every colour, applied with ``source``.
    pins: StylePins | None = None
