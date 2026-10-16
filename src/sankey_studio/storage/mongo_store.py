# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``MongoGraphRepository``: saved graphs in the collection ``sankey_studio_graphs``.

With ``mongo_folder_store.py`` (the library folders, collection ``sankey_studio_collections``)
this is the library store: every write call below carries the ``sankey-no-mongo-writes`` waiver.
The storage connection therefore needs WRITE permission on ``AppSettings.storage_database``;
graph definitions never leave their collection.

Documents are keyed by ``_id`` = the graph id. Field names that come from user text (merge
tables, colour overrides) and operator keys of a Mongo source are rewritten by
``encode_mongo_doc`` before every write, and ``find_unsafe_key`` fails closed if anything else
still carries a key MongoDB < 5.0 rejects. Every call runs inside ``clients.slot(connection)``
and ``mongo_errors(connection, StorageError)``: driver text never reaches a message. The collection
handle is pinned to the primary (``primary_database``): a ``readPreference=secondary*`` in the
saved URI must not make a load miss the save before it.

A graph document also holds ``folder_id`` (the library folder, ``None`` = top level): ``create``
and ``put`` write it, ``update`` never touches it (its ``$set`` lists the editable fields only).

Listings fetch only the summary fields (the possibly large source and style documents stay on
the server), so they skip a record whose SUMMARY is unreadable; a record whose body is damaged is
still listed and ``get`` reports it (``iter_definitions`` reads whole documents and skips it).
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from sankey_studio.errors import NotFoundError, SourceNotFoundError, StorageError, UnsafeSourceError
from sankey_studio.models import SCHEMA_VERSION, GraphDefinition, GraphSummary
from sankey_studio.mongo import mongo_errors, primary_database
from sankey_studio.mongo_safety import validate_namespace
from sankey_studio.storage.base import (
    MONGO_FOLDERS_COLLECTION,
    MONGO_GRAPHS_COLLECTION,
    check_graph_id,
    decode_mongo_doc,
    encode_mongo_doc,
    find_unsafe_key,
)
from sankey_studio.storage.common import (
    Clock,
    clamp_page,
    exists_error,
    new_definition,
    parse_definition,
    search_term,
    stale_error,
    utc_now,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo.collection import Collection

    from sankey_studio.models import GraphCreate, GraphUpdate
    from sankey_studio.mongo import MongoClients

logger = logging.getLogger(__name__)

MSG_NOT_FOUND = "Graph not found"
MSG_UNSAFE_KEY = "The graph holds a field name that MongoDB cannot store"
#: Documents fetched per round trip by ``iter_definitions``.
ITER_PAGE = 100
_SORT = [("updated_at", -1), ("_id", 1)]
#: A listing needs these only; the (large) source and style documents stay on the server.
_SUMMARY_FIELDS = {
    "name": 1,
    "description": 1,
    "tags": 1,
    "source.type": 1,
    "revision": 1,
    "updated_at": 1,
    "folder_id": 1,
}


@dataclass(frozen=True, slots=True)
class MongoStoreTarget:
    """Where the graphs and the library folders live. Part of the ``Services`` cache key.

    ``collection`` holds the graphs, ``folders_collection`` the library folders ("collections" in
    the UI); both sit in ``database`` and both names go through ``validate_namespace``.
    """

    connection: str
    database: str
    collection: str = MONGO_GRAPHS_COLLECTION
    folders_collection: str = MONGO_FOLDERS_COLLECTION

    def __post_init__(self) -> None:
        if not self.connection:
            raise StorageError("No storage connection is selected")
        try:
            validate_namespace(self.database, self.collection)
            validate_namespace(self.database, self.folders_collection)
        except UnsafeSourceError as exc:
            raise StorageError(exc.message) from None
        if self.folders_collection == self.collection:
            raise StorageError("The graphs and the folders need two different collections")


# --------------------------------------------------------------------------- writes
# One tiny function per write so the waiver always sits on the first line of the call.


def _insert(coll: Collection[Any], doc: dict[str, Any]) -> None:
    coll.insert_one(doc)  # nosemgrep: sankey-no-mongo-writes -- graph store


def _replace(coll: Collection[Any], doc: dict[str, Any]) -> None:
    flt = {"_id": doc["_id"]}
    coll.replace_one(flt, doc, upsert=True)  # nosemgrep: sankey-no-mongo-writes -- graph store


def _cas_update(
    coll: Collection[Any], flt: dict[str, Any], changes: dict[str, Any]
) -> dict[str, Any] | None:
    return coll.find_one_and_update(  # nosemgrep: sankey-no-mongo-writes -- graph store
        flt, {"$set": changes}, return_document=ReturnDocument.AFTER
    )


def _remove(coll: Collection[Any], graph_id: str) -> int:
    result = coll.delete_one({"_id": graph_id})  # nosemgrep: sankey-no-mongo-writes -- graph store
    return result.deleted_count


def _ensure_indexes(coll: Collection[Any]) -> None:
    coll.create_index("updated_at")  # nosemgrep: sankey-no-mongo-writes -- graph store
    coll.create_index("tags")  # nosemgrep: sankey-no-mongo-writes -- graph store
    coll.create_index("folder_id")  # nosemgrep: sankey-no-mongo-writes -- graph store


# --------------------------------------------------------------------------- documents


def _check_keys(doc: dict[str, Any]) -> None:
    if find_unsafe_key(doc) is not None:
        raise StorageError(MSG_UNSAFE_KEY)


def _encode(graph: GraphDefinition) -> dict[str, Any]:
    """The stored form of ``graph``: ``_id`` instead of ``id``, real datetimes, safe key names."""
    doc = encode_mongo_doc(graph.model_dump(mode="json"))
    del doc["id"]
    doc.update(_id=graph.id, created_at=graph.created_at, updated_at=graph.updated_at)
    _check_keys(doc)
    return doc


def _changes(data: GraphUpdate, now: datetime) -> dict[str, Any]:
    """The fields an update ``$set``s (``created_at`` and ``_id`` never change)."""
    doc = encode_mongo_doc(data.model_dump(mode="json"))
    doc.update(schema_version=SCHEMA_VERSION, revision=data.revision + 1, updated_at=now)
    _check_keys(doc)
    return doc


def _aware(value: object) -> object:
    """A driver that was not built ``tz_aware`` hands back naive UTC datetimes."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _definition(raw: dict[str, Any]) -> GraphDefinition:
    doc = decode_mongo_doc(raw)
    doc["id"] = doc.get("_id")
    for name in ("created_at", "updated_at"):
        doc[name] = _aware(doc.get(name))
    return parse_definition(doc)


def _readable(raw: dict[str, Any]) -> GraphDefinition | None:
    try:
        return _definition(raw)
    except StorageError:
        logger.warning("Skipping unreadable stored graph %r", raw.get("_id"))
        return None


def _summary(raw: dict[str, Any]) -> GraphSummary | None:
    source = raw.get("source")
    fields = {
        "id": raw.get("_id"),
        "name": raw.get("name"),
        "description": raw.get("description", ""),
        "tags": raw.get("tags", []),
        "source_type": source.get("type") if isinstance(source, dict) else None,
        "revision": raw.get("revision"),
        "updated_at": _aware(raw.get("updated_at")),
        "folder_id": raw.get("folder_id"),
    }
    try:
        return GraphSummary.model_validate(fields)
    except ValidationError:
        logger.warning("Skipping unreadable stored graph %r", raw.get("_id"))
        return None


def _filter(query: str | None, tag: str | None) -> dict[str, Any]:
    flt: dict[str, Any] = {}
    term = search_term(query)
    if term is not None:
        pattern = {"$regex": re.escape(term), "$options": "i"}
        flt["$or"] = [{"name": pattern}, {"description": pattern}, {"tags": pattern}]
    if tag:
        flt["tags"] = tag
    return flt


def _current_revision(coll: Collection[Any], graph_id: str) -> tuple[int | None, datetime | None]:
    """Revision and ``updated_at`` of the stored graph; ``NotFoundError`` when it is gone."""
    raw = coll.find_one({"_id": graph_id}, {"revision": 1, "updated_at": 1})
    if raw is None:
        raise NotFoundError(MSG_NOT_FOUND)
    revision, updated = raw.get("revision"), _aware(raw.get("updated_at"))
    return (
        revision if isinstance(revision, int) else None,
        updated if isinstance(updated, datetime) else None,
    )


class MongoGraphRepository:
    def __init__(
        self, clients: MongoClients, target: MongoStoreTarget, *, clock: Clock = utc_now
    ) -> None:
        self._clients = clients
        self._target = target
        self._clock = clock
        self._indexed = False

    @contextmanager
    def _session(self) -> Iterator[Collection[Any]]:
        name = self._target.connection
        with self._clients.slot(name), mongo_errors(name, StorageError):
            try:
                client = self._clients.get(name)
            except SourceNotFoundError:
                raise StorageError(f"Storage connection '{name}' does not exist") from None
            yield primary_database(client, self._target.database)[self._target.collection]

    def _prepare(self, coll: Collection[Any]) -> None:
        """Create the indexes once per repository, before the first write."""
        if not self._indexed:
            _ensure_indexes(coll)
            self._indexed = True

    # ------------------------------------------------------------------ reads

    def list_graphs(
        self,
        *,
        query: str | None = None,
        tag: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[GraphSummary]:
        size, start = clamp_page(limit, offset)
        if size == 0:  # Mongo reads limit(0) as "no limit"
            return []
        with self._session() as coll:
            cursor = coll.find(_filter(query, tag), dict(_SUMMARY_FIELDS))  # copy: mocks edit it
            rows = list(cursor.sort(list(_SORT)).skip(start).limit(size))
        return [s for s in map(_summary, rows) if s is not None]

    def count(self, *, query: str | None = None, tag: str | None = None) -> int:
        with self._session() as coll:
            return coll.count_documents(_filter(query, tag))

    def all_tags(self) -> list[str]:
        with self._session() as coll:
            found = coll.distinct("tags")
        return sorted({tag for tag in found if isinstance(tag, str)})

    def get(self, graph_id: str) -> GraphDefinition:
        key = check_graph_id(graph_id)
        with self._session() as coll:
            raw = coll.find_one({"_id": key})
        if raw is None:
            raise NotFoundError(MSG_NOT_FOUND)
        return _definition(raw)

    def _documents(self) -> Iterator[dict[str, Any]]:
        """Every raw document in listing order, fetched ``ITER_PAGE`` at a time."""
        offset = 0
        while True:
            with self._session() as coll:
                batch = list(coll.find({}).sort(list(_SORT)).skip(offset).limit(ITER_PAGE))
            yield from batch
            if len(batch) < ITER_PAGE:
                return
            offset += ITER_PAGE

    def iter_definitions(self) -> Iterator[GraphDefinition]:
        for raw in self._documents():
            graph = _readable(raw)
            if graph is not None:
                yield graph

    def unreadable_ids(self) -> list[str]:
        """Reads every document once more (a body can only be judged whole); ids only come out."""
        found: list[str] = []
        for raw in self._documents():
            try:
                _definition(raw)
            except StorageError:
                found.append(str(raw.get("_id")))
        return found

    # ------------------------------------------------------------------ writes

    def create(self, data: GraphCreate, *, folder_id: str | None = None) -> GraphDefinition:
        graph = new_definition(data, self._clock(), folder_id)
        doc = _encode(graph)
        with self._session() as coll:
            self._prepare(coll)
            _insert(coll, doc)
        return graph

    def update(self, graph_id: str, data: GraphUpdate) -> GraphDefinition:
        key = check_graph_id(graph_id)
        changes = _changes(data, self._clock())
        with self._session() as coll:
            raw = _cas_update(coll, {"_id": key, "revision": data.revision}, changes)
            if raw is None:  # nothing matched {id, revision}: gone, or the revision moved on
                revision, updated = _current_revision(coll, key)
                raise stale_error(revision, updated)
        return _definition(raw)

    def put(self, graph: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        doc = _encode(graph)
        with self._session() as coll:
            self._prepare(coll)
            if overwrite:
                _replace(coll, doc)
            else:
                self._insert_new(coll, doc)
        return graph

    @staticmethod
    def _insert_new(coll: Collection[Any], doc: dict[str, Any]) -> None:
        try:
            _insert(coll, doc)
        except DuplicateKeyError:
            revision, updated = _current_revision(coll, doc["_id"])
            raise exists_error(revision, updated) from None

    def delete(self, graph_id: str) -> None:
        key = check_graph_id(graph_id)
        with self._session() as coll:
            deleted = _remove(coll, key)
        if deleted == 0:
            raise NotFoundError(MSG_NOT_FOUND)

    def ping(self) -> None:
        """Reachable and writable: a server ping plus ``create_index`` (needs write rights)."""
        with self._session() as coll:
            self._clients.ping(self._target.connection)
            _ensure_indexes(coll)
            self._indexed = True
