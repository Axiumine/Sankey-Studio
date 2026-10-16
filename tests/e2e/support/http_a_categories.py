# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers of the category flows: transform payloads, a preview call and the donut as numbers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.e2e.support.builders import graph_draft
from tests.e2e.support.clients import json_of

if TYPE_CHECKING:
    from collections.abc import Mapping

    import httpx


def entry(source: str, target: str, category: str | None) -> dict[str, Any]:
    """One ``entry_categories`` item (``None`` forces the pair to be uncategorised)."""
    return {"source": source, "target": target, "category": category}


def rule(match: str, pattern: str, category: str) -> dict[str, Any]:
    """One ``category_rules`` item (``match``: source, target or either)."""
    return {"match": match, "pattern": pattern, "category": category}


def preview(
    api: httpx.Client,
    content: str,
    transform: Mapping[str, Any] | None = None,
    style: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``POST /preview`` of an inline CSV with this transform and style; the render bundle."""
    draft = graph_draft(content, transform=transform, style=style)
    return dict(json_of(api.post("/api/v1/preview", json=draft)))


def slices(bundle: Mapping[str, Any]) -> dict[str, float]:
    """The donut table of a bundle as ``{name: value}`` (every kind, in table order)."""
    return {row["name"]: row["value"] for row in bundle["categories"]}


def entries(
    api: httpx.Client, content: str, transform: Mapping[str, Any] | None = None
) -> dict[tuple[str, str], dict[str, Any]]:
    """``POST /entries`` rows keyed by ``(source, target)``."""
    draft = graph_draft(content, transform=transform)
    page = json_of(api.post("/api/v1/entries", params={"limit": 500}, json=draft))
    return {(row["source"], row["target"]): row for row in page["rows"]}
