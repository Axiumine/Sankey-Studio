"""Plan the write-back of one edit to a MongoDB source (pure: no driver, no settings, no I/O).

``plan_pair_update`` turns a ``SetCategory`` into a selection filter and a one-field update,
``plan_insert`` turns an ``AddEntry`` into the document to insert. Every refusal is a
``SourceEditRefused(reason)`` raised BEFORE any driver call; the reasons are the stable ones of
``models.edits.Reason``. Two reasons belong to other layers: ``reserved_collection`` (see
``storage.mongo_source_writes.check_target``) and ``read_only_mode`` (the operator gates).

The alias map (alias -> canonical node name, from ``graph.intern.resolve_aliases``) is injected:
this module does not import ``graph``. A pair is matched by EVERY spelling the person merged
into the canonical name, so an edit of a merged node reaches all of its documents.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sankey_studio.errors import SourceEditRefused, UnsafeSourceError
from sankey_studio.mongo_safety import check_filter, check_write_document, check_write_update

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sankey_studio.models import AddEntry, MongoSource, SetCategory

#: Most spellings (the canonical name included) matched on one side of a pair.
ALIASES_MAX = 200
#: Integral values up to this magnitude are stored as integers, anything else as a float.
_EXACT_INT = 2**53


@dataclass(frozen=True, slots=True)
class PairUpdate:
    """The documents of one (source, target) pair and the single-field update for them."""

    filter: dict[str, Any]
    update: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Insert:
    """The document ``add_entry`` inserts."""

    document: dict[str, Any]


@contextmanager
def _unsafe_is_refused() -> Iterator[None]:
    """A ``mongo_safety`` refusal means the edit is not written: reason ``unsafe_value``."""
    try:
        yield
    except UnsafeSourceError:
        raise SourceEditRefused("unsafe_value") from None


def resolve_database(spec: MongoSource, default_database: str | None) -> str:
    """The database the edit goes to; ``source_incomplete`` when neither side names one."""
    database = spec.database if spec.database is not None else default_database
    if not database:
        raise SourceEditRefused("source_incomplete")
    return database


def _require_find(spec: MongoSource) -> None:
    if spec.mode != "find":
        raise SourceEditRefused("aggregate_mode")


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def equality_fields(flt: Mapping[str, object]) -> dict[str, Any]:
    """``{field: value}`` of a filter made only of ``field: scalar`` or ``field: {"$eq": scalar}``.

    ``filter_not_equality`` for anything else (operators, ``$and``, ranges, arrays, sub-documents).
    """
    found: dict[str, Any] = {}
    for field, value in flt.items():
        if field.startswith("$"):
            raise SourceEditRefused("filter_not_equality")
        if isinstance(value, Mapping) and set(value) == {"$eq"}:
            value = value["$eq"]  # noqa: PLW2901 - unwrap the explicit equality
        if not _is_scalar(value):
            raise SourceEditRefused("filter_not_equality")
        found[field] = value
    return found


def _filter_fields(node: object) -> set[str]:
    """Every field name used anywhere in a filter tree (operators skipped)."""
    found: set[str] = set()
    if isinstance(node, Mapping):
        found.update(key for key in node if not key.startswith("$"))
        children: list[object] = list(node.values())
    elif isinstance(node, list | tuple):
        children = list(node)
    else:
        return found
    for child in children:
        found |= _filter_fields(child)
    return found


def _overlap(first: str, second: str) -> bool:
    """The same path, or one inside the other (``meta`` and ``meta.from``)."""
    return first == second or first.startswith(f"{second}.") or second.startswith(f"{first}.")


def _check_no_conflict(written: Sequence[str], others: Sequence[str]) -> None:
    """``field_conflict`` unless the written paths are apart from each other and from ``others``."""
    if any(_overlap(path, "_id") for path in (*written, *others)):
        raise SourceEditRefused("field_conflict")
    for index, path in enumerate(written):
        rest = (*written[index + 1 :], *others)
        if any(_overlap(path, other) for other in rest):
            raise SourceEditRefused("field_conflict")


def _spellings(name: str, alias: Mapping[str, str]) -> list[str]:
    """The canonical name of ``name`` and every alias merged into it (sorted)."""
    canonical = alias.get(name, name)
    names = {canonical, *(spelling for spelling, target in alias.items() if target == canonical)}
    if len(names) > ALIASES_MAX:
        raise SourceEditRefused("too_many_aliases")
    return sorted(names)


def plan_pair_update(spec: MongoSource, edit: SetCategory, alias: Mapping[str, str]) -> PairUpdate:
    """Select the documents of the (source, target) pair and set or clear their category.

    The filter is ``{"$and": [spec.filter?, {source_field: {"$in": ...}}, {target_field: ...}]}``.
    Refusals: ``aggregate_mode``, ``no_category_field``, ``field_conflict`` (the category field
    equals or nests with the source field, the target field, the value field or a filter field,
    or touches ``_id``), ``too_many_aliases``, ``unsafe_value``.
    """
    _require_find(spec)
    if spec.category_field is None:
        raise SourceEditRefused("no_category_field")
    value = [] if spec.value_field is None else [spec.value_field]
    selecting = [spec.source_field, spec.target_field, *value, *sorted(_filter_fields(spec.filter))]
    _check_no_conflict([spec.category_field], selecting)
    sides = [
        {spec.source_field: {"$in": _spellings(edit.source, alias)}},
        {spec.target_field: {"$in": _spellings(edit.target, alias)}},
    ]
    flt = {"$and": [*([deepcopy(spec.filter)] if spec.filter else []), *sides]}
    field = spec.category_field
    update = {"$unset": {field: ""}} if edit.category is None else {"$set": {field: edit.category}}
    with _unsafe_is_refused():
        check_filter(flt)
        check_write_update(update)
    return PairUpdate(filter=flt, update=update)


def _nested(values: Mapping[str, object]) -> dict[str, Any]:
    """A document from dotted paths (``a.b`` -> ``{"a": {"b": ...}}``); the paths do not overlap."""
    document: dict[str, Any] = {}
    for path, value in values.items():
        *parents, leaf = path.split(".")
        node = document
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = value
    return document


def _stored_value(value: float) -> int | float:
    return int(value) if value.is_integer() and abs(value) < _EXACT_INT else value


def plan_insert(spec: MongoSource, edit: AddEntry) -> Insert:
    """The document for a new flow: the mapped fields merged with the filter's equality fields.

    The new document is therefore selected by the source's own query. Refusals:
    ``aggregate_mode``, ``no_value_field``, ``no_category_field``, ``filter_not_equality``,
    ``field_conflict``, ``unsafe_value``.
    """
    _require_find(spec)
    if spec.value_field is None:
        raise SourceEditRefused("no_value_field")
    if edit.category is not None and spec.category_field is None:
        raise SourceEditRefused("no_category_field")
    fixed = equality_fields(spec.filter)
    mapped = [
        (spec.source_field, edit.source),
        (spec.target_field, edit.target),
        (spec.value_field, _stored_value(edit.value)),
    ]
    if edit.category is not None and spec.category_field is not None:
        mapped.append((spec.category_field, edit.category))
    _check_no_conflict([*(path for path, _ in mapped), *fixed], [])
    document = _nested({**fixed, **dict(mapped)})
    with _unsafe_is_refused():
        check_write_document(document)
    return Insert(document=document)
