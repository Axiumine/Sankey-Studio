# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The only code that writes to a MongoDB SOURCE collection (opt-in write-back of edits).

Four I/O primitives take plain dicts built by ``sources.mongo_write_plan``: ``count_matching``
and ``matching_ids`` read, ``update_by_ids`` runs ONE ``update_many`` scoped by ``_id``, and
``insert_document`` runs ONE ``insert_one``. Nothing else in the code base may write to a
collection the person reads data from (the graph store has its own module and collection).

Every primitive, in this order:

1. ``check_target``: ``validate_namespace`` (no ``admin``/``local``/``config``/``system.*``) and
   the reserved collections: ANY collection whose casefolded name starts with ``sankey_studio_``
   is refused (``reserved_collection``), so the graph and folder stores can never be a target;
2. ``check_filter`` / ``check_write_update`` / ``check_write_document`` of ``mongo_safety``;
3. ``clients.slot(connection)`` and ``mongo_errors(connection, SourceWriteError)``: a driver
   failure becomes a message with the connection NAME and the exception class only.

``OperationFailure`` 13/18 (not authorised) is ``SourceEditRefused("permission_denied")`` and a
``WriteError`` on insert or update (schema validation, a shard key that may not change) is
``"write_rejected"``: expected answers, the edit then stays in the graph. The update filter is
``{"$and": [{"_id": {"$in": ids}}, flt]}``, so a document that was edited between the id lookup
and the update is not touched.

Accepted risk (ADR-34): the API has no login, so a caller who can reach it can ``$set`` one
string field on documents selected by ``field in [names]`` and insert one scalar document, in any
non-system, non-``sankey_studio_`` collection that the connection's database user may write.
The controls are that user's privileges, the loopback bind or ``--allow-source-writes``, CSRF,
at most 1000 documents, ``find`` mode (an inserted document needs an equality filter), and the
namespace refusals above.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from pymongo.errors import OperationFailure, WriteError

from sankey_studio.errors import SourceEditRefused, SourceWriteError, UnsafeSourceError
from sankey_studio.mongo import AUTH_FAILED_CODES, mongo_errors
from sankey_studio.mongo_safety import (
    check_filter,
    check_write_document,
    check_write_update,
    validate_namespace,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from pymongo.collection import Collection

    from sankey_studio.mongo import MongoClients

logger = logging.getLogger(__name__)

#: Most documents one edit may change; callers ask for ``MONGO_WRITE_MAX_DOCS + 1`` to see "more".
MONGO_WRITE_MAX_DOCS: Final = 1_000
#: Ids checked together by ``update_by_ids`` (each chunk stays far below the filter size cap).
ID_CHUNK: Final = 200
#: Collections whose casefolded name starts like this belong to this application.
RESERVED_PREFIX: Final = "sankey_studio_"


@dataclass(frozen=True, slots=True)
class SourceTarget:
    """A source collection: the client registry, the connection NAME, database and collection."""

    clients: MongoClients
    connection: str
    database: str
    collection: str


def check_target(target: SourceTarget) -> None:
    """``SourceEditRefused("reserved_collection")`` unless the target may be written to."""
    try:
        validate_namespace(target.database, target.collection)
    except UnsafeSourceError:
        raise SourceEditRefused("reserved_collection") from None
    if target.collection.casefold().startswith(RESERVED_PREFIX):
        raise SourceEditRefused("reserved_collection")


@contextmanager
def _unsafe_is_refused() -> Iterator[None]:
    try:
        yield
    except UnsafeSourceError:
        raise SourceEditRefused("unsafe_value") from None


@contextmanager
def _session(target: SourceTarget) -> Iterator[Collection[Any]]:
    """Hold a connection slot and map driver failures; yields the target collection."""
    name = target.connection
    with target.clients.slot(name), mongo_errors(name, SourceWriteError):
        try:
            yield target.clients.get(name)[target.database][target.collection]
        except OperationFailure as exc:
            if exc.code in AUTH_FAILED_CODES:
                raise SourceEditRefused("permission_denied") from None
            raise


def _time_limit(key: str, max_time_ms: int | None) -> dict[str, Any]:
    """The driver's server-side time limit under its own keyword, or nothing."""
    return {} if max_time_ms is None else {key: max_time_ms}


def count_matching(
    target: SourceTarget, flt: Mapping[str, Any], limit: int, max_time_ms: int | None = None
) -> int:
    """How many documents match ``flt``, counting at most ``limit`` (>= 1)."""
    check_target(target)
    with _unsafe_is_refused():
        check_filter(flt)
    with _session(target) as coll:
        return coll.count_documents(dict(flt), limit=limit, **_time_limit("maxTimeMS", max_time_ms))


def matching_ids(
    target: SourceTarget, flt: Mapping[str, Any], limit: int, max_time_ms: int | None = None
) -> list[Any]:
    """The ``_id`` of at most ``limit`` (>= 1) documents that match ``flt``."""
    check_target(target)
    with _unsafe_is_refused():
        check_filter(flt)
    with _session(target) as coll:
        cursor = coll.find(
            dict(flt), {"_id": 1}, limit=limit, **_time_limit("max_time_ms", max_time_ms)
        )
        return [doc["_id"] for doc in cursor]


def _update(coll: Collection[Any], flt: dict[str, Any], update: dict[str, Any]) -> int:
    try:
        result = coll.update_many(  # nosemgrep: sankey-no-mongo-writes -- source write-back, opt-in
            flt, update
        )
    except WriteError as exc:
        if exc.code in AUTH_FAILED_CODES:
            raise
        raise SourceEditRefused("write_rejected") from None
    return result.modified_count


def _insert(coll: Collection[Any], document: dict[str, Any]) -> None:
    try:
        coll.insert_one(  # nosemgrep: sankey-no-mongo-writes -- source write-back, opt-in
            document
        )
    except WriteError as exc:
        if exc.code in AUTH_FAILED_CODES:
            raise
        raise SourceEditRefused("write_rejected") from None


def _log(target: SourceTarget, operation: str, documents: int) -> None:
    logger.info(
        "source write: connection=%s database=%s collection=%s op=%s documents=%d",
        target.connection,
        target.database,
        target.collection,
        operation,
        documents,
    )


def _check_ids(ids: Sequence[Any]) -> None:
    """Run the filter safety walk over the ids in chunks.

    The ids come from the database and are bounded by ``MONGO_WRITE_MAX_DOCS``, so the 64 KiB
    cap of a user filter must not apply to the whole list (1000 long string ids exceed it).
    """
    for start in range(0, len(ids), ID_CHUNK):
        check_filter({"_id": {"$in": list(ids[start : start + ID_CHUNK])}})


def update_by_ids(
    target: SourceTarget,
    ids: Sequence[Any],
    flt: Mapping[str, Any],
    update: Mapping[str, Any],
) -> int:
    """Apply ``update`` to the documents of ``ids`` that STILL match ``flt``; ``modified_count``.

    More than ``MONGO_WRITE_MAX_DOCS`` ids is ``too_many_documents``. ``update`` is one ``$set``
    or ``$unset`` of one field (``check_write_update``).
    """
    check_target(target)
    if len(ids) > MONGO_WRITE_MAX_DOCS:
        raise SourceEditRefused("too_many_documents")
    scoped = {"$and": [{"_id": {"$in": list(ids)}}, dict(flt)]}
    with _unsafe_is_refused():
        check_filter(flt)
        _check_ids(ids)
        check_write_update(update)
    with _session(target) as coll:
        modified = _update(coll, scoped, dict(update))
    _log(target, "update", modified)
    return modified


def insert_document(target: SourceTarget, document: Mapping[str, Any]) -> int:
    """Insert one new document (``check_write_document``); returns 1."""
    check_target(target)
    with _unsafe_is_refused():
        check_write_document(document)
    with _session(target) as coll:
        _insert(coll, dict(document))  # a copy: the driver adds ``_id`` to what it is given
    _log(target, "insert", 1)
    return 1
