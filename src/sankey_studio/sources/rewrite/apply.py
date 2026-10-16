# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The three edits, once, over any ``TextDoc``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import AddEntry, SetCategory
from sankey_studio.sources.rewrite.model import NewRow, canon, rank_key

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sankey_studio.models import ReorderNodes
    from sankey_studio.sources.rewrite.model import Item, TextDoc


def apply_edit(
    doc: TextDoc, edit: AddEntry | SetCategory | ReorderNodes, alias: Mapping[str, str]
) -> tuple[list[Item], int]:
    """The edited items and how many rows changed or were added."""
    if isinstance(edit, AddEntry):
        return _add(doc, edit)
    if isinstance(edit, SetCategory):
        return _set_category(doc, edit, alias)
    return _reorder(doc, edit, alias)


def _add(doc: TextDoc, edit: AddEntry) -> tuple[list[Item], int]:
    items = doc.terminated(list(doc.items))
    if edit.category is not None:
        items = doc.with_category_column(items)
    row = NewRow(edit.source, edit.target, edit.value, edit.category)
    return doc.appended(items, row), 1


def _set_category(
    doc: TextDoc, edit: SetCategory, alias: Mapping[str, str]
) -> tuple[list[Item], int]:
    pair = (canon(edit.source, alias), canon(edit.target, alias))
    if not any(item.pair == pair for item in doc.items):
        raise SourceEditRefused("no_match")
    items = list(doc.items)
    if edit.category is not None:
        items = doc.with_category_column(items)
    changed = 0
    for index, item in enumerate(items):
        if item.pair != pair:
            continue
        items[index] = doc.recategorised(item, edit.category)
        changed += items[index] is not item
    return items, changed


def _ranked(items: list[Item], order: list[str], alias: Mapping[str, str]) -> list[Item]:
    """The data items sorted by (rank of source, rank of target); unknown names last."""
    key = rank_key(order, alias)
    data = [item for item in items if item.pair is not None]
    return sorted(data, key=lambda item: key(item.pair or ("", "")))


def _refilled(items: list[Item], data: list[Item]) -> list[Item]:
    """``items`` with the data items replaced, in order, by ``data`` (raw items stay put)."""
    ordered = iter(data)
    return [item if item.pair is None else next(ordered) for item in items]


def _reorder(doc: TextDoc, edit: ReorderNodes, alias: Mapping[str, str]) -> tuple[list[Item], int]:
    items = list(doc.items)
    data = _ranked(items, edit.order, alias)
    moved = _refilled(items, data)
    if all(new is old for new, old in zip(moved, items, strict=True)):
        return items, 0
    items = doc.terminated(items)  # a moved last row must not run into the next one
    moved = _refilled(items, _ranked(items, edit.order, alias))
    return moved, sum(new is not old for new, old in zip(moved, items, strict=True))
