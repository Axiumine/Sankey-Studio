"""Table views: entries (one row per source/target PAIR), nodes, and the category table.

Frozen dataclasses of JSON primitives (lists, never tuples or arrays), so the web layer can use
them as response models. The entries table is the accessible twin of the Sankey; the category
table is the twin of the donut and mirrors its slices exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sankey_studio.render.colors import ColorMap
from sankey_studio.render.donut import slice_color
from sankey_studio.render.donut_fold import donut_slices

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph, StyleSpec, Theme, TransformSpec
    from sankey_studio.render.options import EntriesOptions


@dataclass(frozen=True, slots=True)
class EntryRow:
    """One (source, target) pair. ``category`` is the category with the largest value when the
    pair has several (``mixed``); ``overridden`` marks a pair set in ``entry_categories``."""

    source: str
    target: str
    value: float
    category: str | None
    mixed: bool
    overridden: bool


@dataclass(frozen=True, slots=True)
class EntriesPage:
    """One page of the filtered, sorted entries; ``total`` counts all rows that match."""

    rows: list[EntryRow]
    total: int


@dataclass(frozen=True, slots=True)
class NodeRow:
    """A node with its layer and its flow in and out."""

    name: str
    layer: int
    node_in: float
    node_out: float


@dataclass(frozen=True, slots=True)
class CategoryRow:
    """A row of the category table: the same entries as a donut slice."""

    name: str
    color: str
    value: float
    share: float
    kind: Literal["category", "uncategorized", "other"]


def entry_rows(graph: SankeyGraph, transform: TransformSpec) -> list[EntryRow]:
    """One row per pair, in first-appearance order."""
    buckets: dict[tuple[int, int], dict[int, float]] = {}
    for link in range(graph.n_links):
        pair = (graph.link_source[link], graph.link_target[link])
        bucket = buckets.setdefault(pair, {})
        category = graph.link_category[link]
        bucket[category] = bucket.get(category, 0.0) + graph.link_value[link]
    overridden = {(entry.source, entry.target) for entry in transform.entry_categories}
    rows = []
    for (source, target), bucket in buckets.items():
        # the largest bucket wins; a tie goes to the lower slot, uncategorised (-1) last
        main = max(bucket, key=lambda c: (bucket[c], -(len(graph.categories) if c < 0 else c)))
        names = (graph.node_names[source], graph.node_names[target])
        rows.append(
            EntryRow(
                source=names[0],
                target=names[1],
                value=sum(bucket.values()),
                category=None if main < 0 else graph.categories[main],
                mixed=len(bucket) > 1,
                overridden=names in overridden,
            )
        )
    return rows


def _matches(row: EntryRow, needle: str) -> bool:
    haystack = (row.source, row.target, row.category or "")
    return any(needle in text.casefold() for text in haystack)


def _sorted(rows: list[EntryRow], sort: str) -> list[EntryRow]:
    """``value`` descending; text columns ascending (case-insensitive, uncategorised last).

    The sort is stable, so ties keep first-appearance order.
    """
    if sort == "value":
        return sorted(rows, key=lambda row: -row.value)
    if sort == "source":
        return sorted(rows, key=lambda row: row.source.casefold())
    if sort == "target":
        return sorted(rows, key=lambda row: row.target.casefold())
    # the first key element parks uncategorised rows last, whatever text the second one holds
    return sorted(rows, key=lambda row: (row.category is None, str(row.category).casefold()))


def entries_page(
    graph: SankeyGraph, transform: TransformSpec, options: EntriesOptions
) -> EntriesPage:
    """Filter (text, only uncategorised), sort and paginate the entries table."""
    rows = entry_rows(graph, transform)
    if options.q:
        needle = options.q.strip().casefold()
        rows = [row for row in rows if _matches(row, needle)]
    if options.only_uncategorized:
        rows = [row for row in rows if row.category is None]
    offset, limit = options.window()
    ordered = _sorted(rows, options.sort)
    return EntriesPage(rows=ordered[offset : offset + limit], total=len(ordered))


def nodes_table(graph: SankeyGraph) -> list[NodeRow]:
    """Every node with its layer and flows, in node order."""
    return [
        NodeRow(name, graph.node_layers[i], graph.node_in[i], graph.node_out[i])
        for i, name in enumerate(graph.node_names)
    ]


def category_table(
    graph: SankeyGraph, style: StyleSpec, theme: Theme, colors: ColorMap | None = None
) -> list[CategoryRow]:
    """The donut as a table: one row per slice, in donut order (empty when there is no donut)."""
    colors = colors or ColorMap.for_graph(graph, style)
    return [
        CategoryRow(s.name, slice_color(s, theme, colors), s.value, s.share, s.kind)
        for s in donut_slices(graph, style, colors)
    ]
