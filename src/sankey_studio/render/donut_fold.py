# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Donut data: totals per category for a basis, and the ONE fold into slices.

``fold_totals`` is used by the donut figure AND by ``tables.category_table``, so the table view
always mirrors the slices exactly. The fold is decided by ``ColorMap.has_hue`` only, never by
looking at colour slots: the compare view re-ranks categories, and hue and fold would disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sankey_studio.models.base import OTHER, UNCATEGORIZED

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph, StyleSpec
    from sankey_studio.render.colors import ColorMap

Basis = Literal["all", "initial", "terminal"]
NO_CATEGORIES_TEXT = "No entry has a category, so there is no donut chart"


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    """Value and share of one category; ``kind="uncategorized"`` marks the ``-1`` bucket."""

    name: str
    value: float
    share: float
    kind: Literal["category", "uncategorized"] = "category"


@dataclass(frozen=True, slots=True)
class DonutSlice:
    """One slice of the donut (and one row of the category table)."""

    name: str
    value: float
    share: float
    kind: Literal["category", "uncategorized", "other"]


def basis_links(graph: SankeyGraph, basis: Basis) -> list[int]:
    """Links counted by ``basis``: all, those leaving a source node, those entering a sink node.

    A source node has ``node_in == 0`` and a sink node ``node_out == 0`` (after cycle breaking).
    """
    links = range(graph.n_links)
    if basis == "initial":
        return [i for i in links if graph.node_in[graph.link_source[i]] == 0]
    if basis == "terminal":
        return [i for i in links if graph.node_out[graph.link_target[i]] == 0]
    return list(links)


def category_totals(graph: SankeyGraph, basis: Basis) -> list[CategoryTotal]:
    """Per-category totals in ``graph.categories`` order, then ``Uncategorized``.

    Zero-value categories are dropped; shares use the total including ``Uncategorized``.
    """
    sums = [0.0] * len(graph.categories)
    loose = 0.0
    for link in basis_links(graph, basis):
        category = graph.link_category[link]
        if category < 0:
            loose += graph.link_value[link]
        else:
            sums[category] += graph.link_value[link]
    whole = sum(sums) + loose
    totals = [
        CategoryTotal(graph.categories[i], value, value / whole)
        for i, value in enumerate(sums)
        if value > 0
    ]
    if loose > 0:
        totals.append(CategoryTotal(UNCATEGORIZED, loose, loose / whole, "uncategorized"))
    return totals


def fold_totals(totals: list[CategoryTotal], max_slices: int, colors: ColorMap) -> list[DonutSlice]:
    """Keep the top ``max_slices`` categories that have a hue; fold the rest into ``Other``.

    Candidates are ranked by value (ties: position in ``totals``). Every other category, both
    the hue candidates beyond the top N and every category without a hue, becomes ONE ``Other``
    slice, always last; ``Uncategorized`` sits right before it.
    """
    real = [total for total in totals if total.kind == "category"]
    candidates = [total for total in real if colors.has_hue(total.name)]
    kept = sorted(candidates, key=lambda total: -total.value)[:max_slices]
    kept_names = {total.name for total in kept}
    slices = [DonutSlice(t.name, t.value, t.share, "category") for t in kept]
    slices.extend(
        DonutSlice(t.name, t.value, t.share, "uncategorized")
        for t in totals
        if t.kind == "uncategorized"
    )
    folded = [total for total in real if total.name not in kept_names]
    if folded:
        value = sum(total.value for total in folded)
        slices.append(DonutSlice(OTHER, value, sum(total.share for total in folded), "other"))
    return slices


def donut_slices(graph: SankeyGraph, style: StyleSpec, colors: ColorMap) -> list[DonutSlice]:
    """The slices of the donut in drawing order; empty when the basis selects no category.

    ``DonutStyle.sort`` orders the category slices by value (descending, as folded) or by name.
    """
    donut = style.donut
    totals = category_totals(graph, donut.basis)
    if not any(total.kind == "category" for total in totals):
        return []
    slices = fold_totals(totals, donut.max_slices, colors)
    if donut.sort == "value":
        return slices
    named = sorted((s for s in slices if s.kind == "category"), key=lambda s: s.name.casefold())
    return [*named, *(s for s in slices if s.kind != "category")]
