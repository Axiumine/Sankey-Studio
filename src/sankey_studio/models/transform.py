# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Transform spec: clean-up and categorisation applied to loaded links."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from sankey_studio.models.base import (
    MAX_ENTRY_CATEGORIES,
    MAX_EXTRA_LINKS,
    MAX_HIDE_NODES,
    MAX_MERGE_NODES,
    NAME_MAX,
    _Model,
)
from sankey_studio.models.fields import NameStr, OptUserCategory, UserCategory
from sankey_studio.models.sources import Link


class EntryCategory(_Model):
    """The user's explicit category for an entry, identified by its (source, target) pair.

    Applies to every loaded row with that pair, after ``merge_nodes``. Highest precedence.
    ``category=None`` means "force uncategorised": it clears a category that came from the data
    or from a rule. The field is required (no default) so an omission is never read as a clear.
    Only for ``text``/``mongo`` sources; a manual source edits ``Link.category`` instead.
    """

    source: NameStr
    target: NameStr
    category: OptUserCategory


class CategoryRule(_Model):
    """Assign a category to entries by node name. First matching rule wins."""

    match: Literal["source", "target", "either"] = "either"
    #: Case-insensitive glob (``*``, ``?``, ``[abc]``) tested against the whole node name.
    pattern: str = Field(min_length=1, max_length=NAME_MAX)
    category: UserCategory

    @field_validator("pattern")
    @classmethod
    def _pattern_text(cls, v: str) -> str:
        if "\0" in v:
            raise ValueError("pattern must not contain NUL")
        return v


class TransformSpec(_Model):
    """Clean-up and categorisation applied to loaded links before layout.

    ``build_graph`` order: merge/hide -> aggregate to (source, target) PAIR totals (category
    agnostic) -> ``min_link_value`` and ``top_links`` on pair totals -> cycle handling on pairs ->
    layers/node sums -> only then split the surviving pairs by category into parallel links.
    Categories therefore never change which nodes/links exist or where they sit.
    """

    min_link_value: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    #: Keep only the N largest (source, target) pairs, after ``min_link_value``. (Not to be
    #: confused with ``AppSettings.max_links``, the cap on RAW rows read from a source.)
    top_links: int | None = Field(default=None, ge=1)
    hide_nodes: list[NameStr] = Field(default_factory=list, max_length=MAX_HIDE_NODES)
    #: alias -> canonical node name (links are re-pointed, then duplicates summed). A link that
    #: becomes a self-loop through merging is dropped with a warning (also when ``on_cycle`` is
    #: ``"error"``).
    merge_nodes: dict[NameStr, NameStr] = Field(default_factory=dict, max_length=MAX_MERGE_NODES)
    #: A cycle cannot be laid out by Sankey: fail, or drop the back-edges that close it.
    on_cycle: Literal["error", "break"] = "error"
    #: Bad rows/values fail the load (True) or are skipped with a warning (False). The pipeline
    #: passes it on as ``services.source_context(strict=draft.transform.strict)``.
    strict: bool = False
    #: Category precedence per entry: ``entry_categories`` > data category > ``category_rules``
    #: (with ``rules_override`` the rules rank above the data category instead).
    entry_categories: list[EntryCategory] = Field(
        default_factory=list, max_length=MAX_ENTRY_CATEGORIES
    )
    category_rules: list[CategoryRule] = Field(default_factory=list, max_length=200)
    #: Flows that live in this graph only (added without touching the data). RAW names, so
    #: ``merge_nodes`` and ``hide_nodes`` apply like for any row; they count toward ``max_links``.
    extra_links: list[Link] = Field(default_factory=list, max_length=MAX_EXTRA_LINKS)
    rules_override: bool = False

    @model_validator(mode="after")
    def _unique_entry_pairs(self) -> TransformSpec:
        seen: set[tuple[str, str]] = set()
        for entry in self.entry_categories:
            pair = (entry.source, entry.target)
            if pair in seen:
                raise ValueError("entry_categories must not repeat a (source, target) pair")
            seen.add(pair)
        return self
