# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Builders shared by the rewriter tests."""

from __future__ import annotations

from sankey_studio.models import AddEntry, ReorderNodes, SetCategory


def add(source: str, target: str, value: float, category: str | None = None) -> AddEntry:
    return AddEntry(op="add_entry", source=source, target=target, value=value, category=category)


def categorise(source: str, target: str, category: str | None) -> SetCategory:
    return SetCategory(op="set_category", source=source, target=target, category=category)


def reorder(*order: str) -> ReorderNodes:
    return ReorderNodes(op="reorder", order=list(order))
