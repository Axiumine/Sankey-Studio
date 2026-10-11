"""Step 1: stream the links once, intern names and category values, aggregate entries.

Node ids are POST-merge and follow first appearance in the stream: this order is the stable
node colour slot, so nothing later (hide, ``min_link_value``, ``top_links``) may renumber it.
Entries are aggregated in a dict keyed by one packed Python int, so two ids below 2**32 and a
category id below 2**32 can never collide and no per-row tuple is allocated.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from sankey_studio.errors import GraphBuildError, GraphTooLargeError
from sankey_studio.util import RESERVED_CATEGORY_KEYS, category_key, normalize_category

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from sankey_studio.graph.state import BuildState
    from sankey_studio.models import RawLink

#: Width of one packed field. A key is ``source << 64 | target << 32 | category``.
FIELD_BITS = 32
FIELD_MASK = (1 << FIELD_BITS) - 1
SOURCE_SHIFT = 2 * FIELD_BITS
TARGET_SHIFT = FIELD_BITS


def pack_key(source: int, target: int, category: int) -> int:
    """Pack three ids below ``2**32`` into one int; ``category`` is the data category id + 1."""
    return (source << SOURCE_SHIFT) | (target << TARGET_SHIFT) | category


def unpack_key(key: int) -> tuple[int, int, int]:
    """Inverse of ``pack_key``."""
    return key >> SOURCE_SHIFT, (key >> TARGET_SHIFT) & FIELD_MASK, key & FIELD_MASK


def resolve_aliases(merge_nodes: Mapping[str, str]) -> dict[str, str]:
    """Follow alias chains (``a -> b -> c``) to their end: ``{a: c, b: c}``.

    A name mapped to itself is a no-op. A cyclic map (``a -> b -> a``) raises ``GraphBuildError``.
    """
    resolved: dict[str, str] = {}
    for start in merge_nodes:
        path: list[str] = []
        seen: set[str] = set()
        current = start
        while current in merge_nodes and current not in resolved and current not in seen:
            seen.add(current)
            path.append(current)
            current = merge_nodes[current]
        if current in seen and merge_nodes[current] != current:
            raise GraphBuildError(f"merge_nodes is cyclic: {_chain_text(path, current)}")
        terminal = resolved.get(current, current)
        for name in path:
            resolved[name] = terminal
    return {alias: target for alias, target in resolved.items() if alias != target}


def _chain_text(path: list[str], repeat: str) -> str:
    """``a -> b -> a`` for the part of ``path`` that loops back to ``repeat``."""
    loop = path[path.index(repeat) :]
    return " -> ".join([*loop[:8], repeat])


def intern_node(state: BuildState, name: str, alias: Mapping[str, str]) -> int:
    """Id of ``name`` after merging; new canonical names get the next id."""
    canonical = alias.get(name, name)
    node_id = state.ids.get(canonical)
    if node_id is None:
        node_id = len(state.names)
        state.names.append(canonical)
        state.ids[canonical] = node_id
    state.ids[name] = node_id
    return node_id


def data_category(state: BuildState, category: str | None) -> int:
    """Data category id + 1 of a row (0 = none or unusable), interned on first sight.

    Identity is ``category_key`` (case and NFC variants share one id); the first spelling seen
    is the display name. ``category_key`` runs once per DISTINCT raw value, never per row.
    """
    if category is None:
        return 0
    cat_id = state.data_cat_ids.get(category)
    if cat_id is None:
        return _intern_category(state, category)
    return cat_id


def _intern_category(state: BuildState, raw: str) -> int:
    """Intern a new raw category value; 0 when it is unusable.

    Sources already clean categories; this is the second line of defence for anything that
    reaches ``build_graph`` directly: control characters, empty and reserved names count as
    "no category" (one aggregated warning), and the first spelling seen is the display name.
    """
    cat_id = _category_id(state, raw)
    state.data_cat_ids[raw] = cat_id
    if cat_id == 0:
        state.unusable_categories += 1
    return cat_id


def _category_id(state: BuildState, raw: str) -> int:
    try:
        key = category_key(raw)
        display = normalize_category(raw)
    except ValueError:
        return 0
    if not key or key in RESERVED_CATEGORY_KEYS:
        return 0
    cat_id = state.data_cat_keys.get(key)
    if cat_id is None:
        state.data_cats.append(display)
        cat_id = len(state.data_cats)
        state.data_cat_keys[key] = cat_id
    return cat_id


@contextlib.contextmanager
def _closing(rows: Iterator[RawLink]) -> Iterator[Iterator[RawLink]]:
    """Close the source on every exit path; plain iterators (lists) have nothing to close."""
    try:
        yield rows
    finally:
        close = getattr(rows, "close", None)
        if close is not None:
            # An Iterator has no `close`, so the IDE types `close` as None: a false positive.
            # noinspection PyCallingNonCallable
            close()


def stream_links(links: Iterable[RawLink], state: BuildState, max_raw_links: int) -> None:
    """Read ``links`` once, never into a list, and aggregate them into ``state.agg``."""
    alias = resolve_aliases(state.transform.merge_nodes)
    ids, agg = state.ids, state.agg
    count = merged_loops = 0
    with _closing(iter(links)) as rows:
        for source, target, value, category in rows:
            count += 1
            if count > max_raw_links:
                raise GraphTooLargeError(
                    f"The source has more than {max_raw_links} links; raise max_links in the "
                    "settings or narrow the data"
                )
            s = ids.get(source)
            if s is None:
                s = intern_node(state, source, alias)
            t = ids.get(target)
            if t is None:
                t = intern_node(state, target, alias)
            if s == t and source != target:
                merged_loops += 1
                continue
            key = pack_key(s, t, data_category(state, category))
            agg[key] = agg.get(key, 0.0) + value
    if merged_loops:
        state.warnings.append(
            f"Dropped {merged_loops} link(s) that became self-loops after merging"
        )
