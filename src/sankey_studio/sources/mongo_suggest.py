# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Field-name suggestions for the editor's Mongo form, from a few sample documents.

Heuristics only (the user can always overwrite them). A dotted path whose LAST segment is a
well-known name (``from``/``to``/``amount``/``type``/...) wins: the name listed first, then the
shallowest path, then the first seen. Named matches are settled for every field before any
fallback runs; without a name match the first still-unused text field becomes the source and then
the target, and the first still-unused positive number the value. The fallbacks never take ``_id``
(a sampled ObjectId is just a hex string, an opaque key rather than a name or a quantity). Arrays
are never suggested (they cannot be a name), and every suggestion is a valid ``MongoSource`` field
path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sankey_studio.models.base import FIELD_PATH_RE
from sankey_studio.sources.mongo_extract import (
    FieldRejectedError,
    coerce_name,
    coerce_value,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Deepest dotted path suggested (``a.b.c``).
MAX_PATH_SEGMENTS = 3
DEFAULT_SOURCE = "source"
DEFAULT_TARGET = "target"
DEFAULT_VALUE = "value"
#: The document key no fallback takes: its samples are opaque identifiers.
ID_FIELD = "_id"

type Values = list[object]
type Predicate = Callable[[Values], bool]


@dataclass(frozen=True, slots=True)
class FieldSuggestion:
    """Suggested field paths. ``category`` is ``None`` when no field looks like one."""

    source: str
    target: str
    value: str
    category: str | None


def _accepts(coerce: Callable[[object], object], value: object) -> bool:
    try:
        coerce(value)
    except FieldRejectedError:
        return False
    return True


def _usable_names(values: Values) -> bool:
    return any(_accepts(coerce_name, v) for v in values)


def _usable_numbers(values: Values) -> bool:
    return any(_accepts(coerce_value, v) for v in values)


def _plain_texts(values: Values) -> bool:
    return any(isinstance(v, str) and v.strip() != "" for v in values)


def _plain_numbers(values: Values) -> bool:
    """Real numbers only (``coerce_value`` refuses booleans, but accepts numeric text)."""
    return any(isinstance(v, int | float) and _accepts(coerce_value, v) for v in values)


@dataclass(frozen=True, slots=True)
class _Rule:
    """Names (priority order) that mark a field, and what its samples must look like."""

    names: tuple[str, ...]
    usable: Predicate


_SOURCE = _Rule(("source", "src", "from", "origin"), _usable_names)
_TARGET = _Rule(("target", "dst", "to", "dest", "destination"), _usable_names)
_VALUE = _Rule(("value", "amount", "count", "qty", "quantity", "total"), _usable_numbers)
_CATEGORY = _Rule(("category", "type", "kind", "group"), _plain_texts)


def _collect(node: Mapping[str, Any], prefix: str, leaves: dict[str, Values]) -> None:
    for key, value in node.items():
        path = f"{prefix}{key}"
        if "." in key or FIELD_PATH_RE.fullmatch(path) is None:
            continue
        if isinstance(value, Mapping):
            if path.count(".") + 1 < MAX_PATH_SEGMENTS:
                _collect(value, f"{path}.", leaves)
        elif not isinstance(value, list | tuple):
            leaves.setdefault(path, []).append(value)


def leaf_samples(docs: Sequence[Mapping[str, Any]]) -> dict[str, Values]:
    """Every scalar field path of the sample documents with its sampled values, in the order the
    paths first appear. Arrays, over-deep paths and keys that are not plain names are left out."""
    leaves: dict[str, Values] = {}
    for doc in docs:
        _collect(doc, "", leaves)
    return leaves


def _rank(path: str, position: int, names: tuple[str, ...]) -> tuple[int, int, int] | None:
    last = path.rpartition(".")[2].casefold()
    if last not in names:
        return None
    return names.index(last), path.count("."), position


def _by_name(leaves: Mapping[str, Values], rule: _Rule, used: set[str]) -> str | None:
    ranked: list[tuple[tuple[int, int, int], str]] = []
    for position, (path, values) in enumerate(leaves.items()):
        rank = _rank(path, position, rule.names)
        if rank is not None and path not in used and rule.usable(values):
            ranked.append((rank, path))
    return min(ranked)[1] if ranked else None


def _named(leaves: Mapping[str, Values], rule: _Rule, used: set[str]) -> str | None:
    """The best path for ``rule`` by its names; it is added to ``used``."""
    path = _by_name(leaves, rule, used)
    if path is not None:
        used.add(path)
    return path


def _fallback(leaves: Mapping[str, Values], looks_right: Predicate, used: set[str]) -> str | None:
    """The first path (never ``_id``) no other field took whose samples satisfy ``looks_right``."""
    for path, values in leaves.items():
        if path not in used and path != ID_FIELD and looks_right(values):
            used.add(path)
            return path
    return None


def suggest_fields(docs: Sequence[Mapping[str, Any]]) -> FieldSuggestion:
    """Suggest the source/target/value/category paths for a form from sample documents.

    Named matches are settled first for every field, so a fallback never takes the field that
    another one is named after.
    """
    leaves = leaf_samples(docs)
    used: set[str] = set()
    value = _named(leaves, _VALUE, used)
    category = _named(leaves, _CATEGORY, used)
    source = _named(leaves, _SOURCE, used)
    target = _named(leaves, _TARGET, used)
    source = source or _fallback(leaves, _plain_texts, used)
    target = target or _fallback(leaves, _plain_texts, used)
    value = value or _fallback(leaves, _plain_numbers, used)
    return FieldSuggestion(
        source=source or DEFAULT_SOURCE,
        target=target or DEFAULT_TARGET,
        value=value or DEFAULT_VALUE,
        category=category,
    )
