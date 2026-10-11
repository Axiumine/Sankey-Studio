"""Draft -> graph -> bundle: the one place that strings sources, graph building and rendering.

``build_graph_from_draft`` loads a source and builds the ``SankeyGraph``; ``assemble_bundle`` turns
a graph and its draft into a ``RenderBundle``; ``render_bundle`` and ``render_compare`` are the two
entry points of the web layer.

Loaded graphs are kept in a small per-``Services`` LRU (``ResultCache``) so paging or filtering the
entries table does not parse a 25 MB file or query Mongo again on every keystroke. The key is the
digest of the source and transform specs in the order the user wrote them (a reordered MongoDB
``$sort`` is another query, so the dict keys are not sorted; a reorder only costs a miss; the style
is not part of it: it never changes the graph), plus what the specs do not say: the stat of a file
source (inode, size, mtime, ctime; a file touched in the last two seconds is not cached at all),
the identity of a Mongo connection, and ``AppSettings.max_links``. Entries live 120 s,
Mongo-backed ones 30 s.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from sankey_studio.bundle import BundleStats, RenderBundle
from sankey_studio.errors import GraphBuildError, SankeyError
from sankey_studio.graph import build_graph
from sankey_studio.models import ENTRIES_PREVIEW_LIMIT, MongoSource, TextSource
from sankey_studio.render.colors import ColorMap
from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.legend import legend_items
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.sankey import build_figure, truncation_note
from sankey_studio.render.tables import category_table, entry_rows
from sankey_studio.sources import open_source
from sankey_studio.sources.base import Diagnostics
from sankey_studio.sources.files import resolve_source_path
from sankey_studio.util import mask_uri

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from sankey_studio.bundle import DonutEmptyReason
    from sankey_studio.models import (
        GraphDraft,
        SankeyGraph,
        SourceSpec,
        StyleSpec,
        Theme,
        TransformSpec,
    )
    from sankey_studio.render.tables import EntryRow
    from sankey_studio.services import Services
    from sankey_studio.sources.base import SourceContext

__all__ = [
    "CACHE_ENTRIES",
    "FILE_TTL_S",
    "MONGO_TTL_S",
    "RACY_WINDOW_NS",
    "BundleOptions",
    "GraphCache",
    "ResultCache",
    "assemble_bundle",
    "build_graph_from_draft",
    "cache_for",
    "cache_key",
    "preview_entries",
    "render_bundle",
    "render_compare",
    "use_cache",
]

#: Graphs kept per cache. At least ``COMPARE_IDS_MAX`` (12): a smaller LRU evicts every card of a
#: compare view before the next request asks for it again, and nothing is ever served from it.
CACHE_ENTRIES = 16
#: Seconds a loaded graph stays valid (inline text, files, manual links).
FILE_TTL_S = 120.0
#: Seconds a graph loaded from MongoDB stays valid: the collection may change under us.
MONGO_TTL_S = 30.0
#: A file whose mtime or ctime is younger than this (nanoseconds) is not cached: a rewrite in the
#: same timestamp tick keeps the same size and mtime, so the stamp cannot tell it from the original.
RACY_WINDOW_NS = 2_000_000_000
_TOO_LARGE = "The flow sums are too large to draw: they exceed the float range."


# --------------------------------------------------------------------------- the cache


class GraphCache(Protocol):  # pragma: no mutate block - interface only, never executed
    """What the pipeline needs of a cache: ``ResultCache`` and any look-alike satisfy it."""

    def get(self, key: str, /) -> SankeyGraph | None: ...

    def put(self, key: str, value: SankeyGraph, ttl_s: float, /) -> None: ...


class ResultCache:
    """A small thread-safe LRU of built graphs with a per-entry time to live.

    ``clock`` is injectable (tests never sleep). An entry is valid while ``clock() < expires``.
    """

    def __init__(
        self, max_entries: int = CACHE_ENTRIES, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[float, SankeyGraph]] = OrderedDict()

    @property
    def size(self) -> int:
        """Entries held right now (expired ones that nobody asked for yet included)."""
        with self._lock:
            return len(self._items)

    def get(self, key: str) -> SankeyGraph | None:
        """The live graph for ``key`` (and mark it most recently used), else ``None``."""
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires, value = item
            if self._clock() >= expires:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: str, value: SankeyGraph, ttl_s: float) -> None:
        """Store ``value`` for ``ttl_s`` seconds; expired entries go first, then the oldest."""
        with self._lock:
            now = self._clock()
            for stale in [k for k, (expires, _) in self._items.items() if now >= expires]:
                del self._items[stale]
            self._items[key] = (now + ttl_s, value)
            self._items.move_to_end(key)
            while len(self._items) > self._max_entries:
                del self._items[next(iter(self._items))]


_CACHES: weakref.WeakKeyDictionary[Services, ResultCache] = weakref.WeakKeyDictionary()
_CACHES_LOCK = threading.Lock()


def cache_for(services: Services) -> ResultCache:
    """The cache that belongs to ``services`` (created on first use, gone with the instance)."""
    with _CACHES_LOCK:
        cache = _CACHES.get(services)
        if cache is None:
            cache = _CACHES[services] = ResultCache()
        return cache


def use_cache(services: Services, cache: ResultCache) -> None:
    """Replace the cache of ``services`` (a different size or clock; mostly for tests)."""
    with _CACHES_LOCK:
        _CACHES[services] = cache


# --------------------------------------------------------------------------- cache key


def _wall_ns() -> int:
    """The wall clock in nanoseconds (a seam: file times are wall-clock times)."""
    return time.time_ns()


def _file_stamp(sources_dir: Path, rel: str | None) -> dict[str, Any] | None:
    """What identifies the bytes of a managed file; ``None`` when it must not be cached.

    That is a source without a path, a file that cannot be stat'ed and a "racy" one, touched (or
    created, or renamed over) less than ``RACY_WINDOW_NS`` ago: its next rewrite may leave size and
    mtime as they are. The inode catches a replace, the ctime a rewrite whose mtime was put back
    (``cp -p``, ``rsync -t``).
    """
    if rel is None:
        return None
    try:
        info = resolve_source_path(sources_dir, rel).lstat()
    except SankeyError, OSError:
        return None
    if _wall_ns() - max(info.st_mtime_ns, info.st_ctime_ns) < RACY_WINDOW_NS:
        return None
    return {
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _mongo_stamp(spec: MongoSource, ctx: SourceContext) -> dict[str, Any]:
    """The connection behind the source: masked URI, a digest of the secret one, database, timeout.

    The masked URI hides the password, so it alone would leave a graph loaded with the old
    credentials in the cache after a rotation; the SHA-256 digest of the full secret URI moves the
    key whenever any part of it changes. The secret itself never enters the stamp, and the stamp
    only ever goes into the hashed payload of ``cache_key`` (never logged, never returned).
    """
    conn = ctx.settings.connection(spec.connection)
    if conn is None:
        return {}  # the load fails with "no such connection" and nothing is cached
    secret = conn.uri.get_secret_value()
    return {
        "uri": mask_uri(secret),
        "secret_sha256": hashlib.sha256(secret.encode()).hexdigest(),
        "database": conn.default_database,
        "timeout_ms": ctx.settings.mongo_timeout_ms,
    }


def _stamp(spec: SourceSpec, ctx: SourceContext) -> dict[str, Any] | None:
    """What the source depends on besides its spec; ``None`` means the load is not cacheable."""
    if isinstance(spec, TextSource) and spec.origin == "file":
        return _file_stamp(ctx.sources_dir, spec.path)
    if isinstance(spec, MongoSource):
        return _mongo_stamp(spec, ctx)
    return {}


def cache_key(draft: GraphDraft, ctx: SourceContext) -> str | None:
    """Digest of source + transform (+ stamp and ``max_links``); ``None`` when not cacheable.

    The style is left out on purpose: it never changes the graph. The keys of the specs are NOT
    sorted: the order of a ``$sort`` document or a ``$group`` changes the result, so two spellings
    are two keys (the model fields come in declaration order, the user's dicts in their own).
    """
    stamp = _stamp(draft.source, ctx)
    if stamp is None:
        return None
    specs = draft.model_dump(mode="json", include={"source", "transform"})
    payload = {**specs, "max_links": ctx.settings.max_links, "stamp": stamp}
    text = json.dumps(payload, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------- the graph


def _require_finite_totals(graph: SankeyGraph) -> None:
    """Refuse a graph whose flow sums overflow a float (two links of 1e308 into one node).

    Link values are positive (the sources and ``Link`` refuse the rest), so every node sum, total
    and category sum is a sub-sum of the sum of all link values: when that one is finite, they
    all fit. Otherwise the bundle would hold ``inf`` and could not be written as JSON.
    """
    try:
        finite = math.isfinite(math.fsum(graph.link_value))
    except OverflowError:
        raise GraphBuildError(_TOO_LARGE) from None
    if not finite:
        raise GraphBuildError(_TOO_LARGE)


def build_graph_from_draft(
    services: Services, draft: GraphDraft, cache: GraphCache | None = None
) -> SankeyGraph:
    """Load the source of ``draft`` and build its graph (served from the cache when fresh).

    The source context is strict exactly when ``draft.transform.strict``; ``AppSettings.max_links``
    caps the raw rows. Errors (``SourceError``, ``GraphBuildError``, ...) are never cached.
    ``cache`` is the app's cache; without one the per-``Services`` cache (``cache_for``) is used.
    """
    ctx = services.source_context(strict=draft.transform.strict)
    cache = cache_for(services) if cache is None else cache
    key = cache_key(draft, ctx)
    if key is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    diag = Diagnostics()
    links = open_source(draft.source, ctx).iter_links(diag)
    graph = build_graph(links, draft.transform, max_raw_links=ctx.settings.max_links, diag=diag)
    _require_finite_totals(graph)
    if key is not None:
        ttl = MONGO_TTL_S if isinstance(draft.source, MongoSource) else FILE_TTL_S
        cache.put(key, graph, ttl)
    return graph


# --------------------------------------------------------------------------- the bundle


@dataclass(frozen=True, slots=True)
class BundleOptions:
    """What ``assemble_bundle`` needs besides the graph and its draft.

    ``colors`` is the shared category map of the compare view. ``entries_limit`` caps the entries
    preview. ``max_drawn_links`` draws only the top-N links (``None``: all); ``render_bundle`` and
    ``render_compare`` fill it from ``AppSettings.max_drawn_links`` when it is ``None``.
    """

    theme: Theme
    colors: ColorMap | None = None
    entries_limit: int = ENTRIES_PREVIEW_LIMIT
    max_drawn_links: int | None = None


def preview_entries(
    graph: SankeyGraph, transform: TransformSpec, limit: int
) -> tuple[list[EntryRow], int]:
    """The ``limit`` largest entries and the total number of entries.

    Same order as ``entries_page(sort="value")`` (value descending, ties in first-appearance
    order), but without its ``ENTRIES_PAGE_MAX`` cap: the preview holds up to
    ``ENTRIES_PREVIEW_LIMIT`` rows.
    """
    rows = entry_rows(graph, transform)
    ordered = sorted(rows, key=lambda row: -row.value)
    return ordered[: max(limit, 0)], len(rows)


def _drawn_count(graph: SankeyGraph, max_drawn_links: int | None) -> int:
    if max_drawn_links is None:
        return graph.n_links
    return min(graph.n_links, max(max_drawn_links, 0))


def _stats(graph: SankeyGraph, drawn_links: int) -> BundleStats:
    nodes = range(graph.n_nodes)
    return BundleStats(
        nodes=graph.n_nodes,
        links=graph.n_links,
        drawn_links=drawn_links,
        total_in=math.fsum(graph.node_out[n] for n in nodes if graph.node_in[n] == 0),
        total_out=math.fsum(graph.node_in[n] for n in nodes if graph.node_out[n] == 0),
        layers=max(graph.node_layers, default=-1) + 1,
        category_count=len(graph.categories),
    )


def _donut(
    graph: SankeyGraph, style: StyleSpec, theme: Theme, options: FigureOptions
) -> tuple[dict[str, Any] | None, DonutEmptyReason | None]:
    """``(figure, empty reason)``: no figure without categories, an empty one for a dead basis."""
    if not graph.has_categories:
        return None, "no_categories"
    figure = build_donut_figure(graph, style, theme, options)
    return figure, (None if figure["data"] else "basis_empty")


def assemble_bundle(graph: SankeyGraph, draft: GraphDraft, options: BundleOptions) -> RenderBundle:
    """Everything the page needs for ``graph``, drawn with ``draft.style`` in ``options.theme``."""
    style, theme = draft.style, options.theme
    figure_options = FigureOptions(max_links=options.max_drawn_links, colors=options.colors)
    donut, reason = _donut(graph, style, theme, figure_options)
    entries, entries_total = preview_entries(graph, draft.transform, options.entries_limit)
    drawn = _drawn_count(graph, options.max_drawn_links)
    warnings = list(graph.warnings)
    if drawn < graph.n_links:
        warnings.append(truncation_note(drawn, graph.n_links))
    return RenderBundle(
        figure=build_figure(graph, style, theme, figure_options),
        legend=legend_items(graph, style, theme, figure_options),
        donut_available=donut is not None,
        donut=donut,
        donut_empty_reason=reason,
        categories=category_table(graph, style, theme, options.colors),
        category_names=list(graph.categories),
        stats=_stats(graph, drawn),
        entries=entries,
        entries_total=entries_total,
        warnings=warnings,
    )


def _with_settings_cap(services: Services, options: BundleOptions) -> BundleOptions:
    """``options`` with ``max_drawn_links`` taken from the settings unless it was given."""
    if options.max_drawn_links is not None:
        return options
    return replace(options, max_drawn_links=services.settings().max_drawn_links)


def render_bundle(
    services: Services, draft: GraphDraft, options: BundleOptions, cache: GraphCache | None = None
) -> RenderBundle:
    """Build the graph of ``draft`` and its bundle (the preview and render routes)."""
    graph = build_graph_from_draft(services, draft, cache)
    return assemble_bundle(graph, draft, _with_settings_cap(services, options))


def render_compare(
    services: Services,
    drafts: Sequence[GraphDraft],
    theme: Theme,
    cache: GraphCache | None = None,
) -> list[RenderBundle]:
    """One bundle per draft, all sharing ONE category colour map (``ColorMap.for_graphs``).

    Every graph is built first, so the map ranks categories over the whole set and no card
    re-ranks them; the overrides of the first draft's style apply to all cards.
    """
    if not drafts:
        return []
    built = [(build_graph_from_draft(services, draft, cache), draft) for draft in drafts]
    colors = ColorMap.for_graphs([graph for graph, _ in built], drafts[0].style)
    options = _with_settings_cap(services, BundleOptions(theme, colors))
    return [assemble_bundle(graph, draft, options) for graph, draft in built]
