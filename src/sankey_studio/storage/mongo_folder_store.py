"""``MongoFolderRepository``: library folders in the collection ``sankey_studio_collections``.

The twin of ``files/folders.py`` for the MongoDB backend. Together with ``mongo_store.py`` (graphs
in ``sankey_studio_graphs``) this is the only code that writes to MongoDB: every write call below
carries the ``sankey-no-mongo-writes`` waiver and sits in its own tiny function. Both collections
live in ``AppSettings.storage_database`` and are reached through the storage connection, so that
connection needs WRITE permission on both. Every call runs inside ``clients.slot(connection)`` and
``mongo_errors(connection, StorageError)``: driver text never reaches a message.

* A folder is one document ``{_id, name, name_key, parent_id, schema_version, revision,
  created_at, updated_at}``. ``name_key`` (NFC + case-folded name) is derived here, never read
  from a caller. ``parent_id`` is always stored (``None`` for a top-level folder), so the unique
  index on ``(parent_id, name_key)`` makes sibling names unique atomically; the pure rules of
  ``folder_tree`` are checked first (friendly errors), the index is the guard against a race.
* Membership lives on the graph (``folder_id`` in the graph collection). Moving a graph only
  ``$set``s that one field: no revision bump, no ``updated_at`` change. A ``folder_id`` that names
  no folder reads as top level (``$nin`` the known ids, or ``None`` / absent).
* Deleting a folder moves its graphs up FIRST, then removes the record, then moves its
  sub-folders up. The record has to go before its children move: a child may carry the name of
  the folder being deleted and would collide with it under the unique index. A crash after the
  record is gone leaves sub-folders pointing at a missing parent, which every reader treats as
  the top level (the tree helpers never loop on a missing parent).
* There are no transactions: two racing moves can leave a cycle; the readers are cycle-safe.
* Both collection handles are pinned to the primary (``primary_database``), whatever
  ``readPreference`` the saved URI carries: a delete then an import must not see the old folders.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from sankey_studio.errors import (
    FolderNameTakenError,
    NotFoundError,
    SourceNotFoundError,
    StorageError,
)
from sankey_studio.models import FOLDERS_MAX, FolderDefinition, MoveReport
from sankey_studio.mongo import mongo_errors, primary_database
from sankey_studio.storage.base import check_graph_id
from sankey_studio.storage.common import Clock, clamp_page, utc_now
from sankey_studio.storage.folder_tree import (
    MSG_NAME_TAKEN,
    MSG_NOT_FOUND,
    Placement,
    check_name_free,
    name_key,
    reparent_plan,
    requested_parent,
    validate_new_count,
    validate_placement,
    with_counts,
)
from sankey_studio.storage.folders_base import (
    check_folder_id,
    exists_error,
    new_folder_id,
    parse_folder,
    scope_id,
    stale_error,
)
from sankey_studio.storage.mongo_store import _SORT, _SUMMARY_FIELDS, _aware, _summary

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from pymongo.collection import Collection

    from sankey_studio.models import FolderCreate, FolderSummary, FolderUpdate, GraphSummary
    from sankey_studio.mongo import MongoClients
    from sankey_studio.storage.mongo_store import MongoStoreTarget

logger = logging.getLogger(__name__)

#: A store never holds more folders than this; one more is read so a full store is noticed.
_READ_LIMIT = FOLDERS_MAX + 1


@dataclass(frozen=True, slots=True)
class _Handles:
    """The two collections of the storage database."""

    graphs: Collection[Any]
    folders: Collection[Any]


# --------------------------------------------------------------------------- writes
# One tiny function per write so the waiver always sits on the first line of the call.


def _insert_folder(coll: Collection[Any], doc: dict[str, Any]) -> None:
    coll.insert_one(doc)  # nosemgrep: sankey-no-mongo-writes -- folder store


def _replace_folder(coll: Collection[Any], doc: dict[str, Any]) -> None:
    flt = {"_id": doc["_id"]}
    coll.replace_one(flt, doc, upsert=True)  # nosemgrep: sankey-no-mongo-writes -- folder store


def _cas_folder(
    coll: Collection[Any], flt: dict[str, Any], changes: dict[str, Any]
) -> dict[str, Any] | None:
    return coll.find_one_and_update(  # nosemgrep: sankey-no-mongo-writes -- folder store
        flt, {"$set": changes}, return_document=ReturnDocument.AFTER
    )


def _remove_folder(coll: Collection[Any], folder_id: str) -> int:
    result = coll.delete_one(  # nosemgrep: sankey-no-mongo-writes -- folder store
        {"_id": folder_id}
    )
    return result.deleted_count


def _reparent_folders(coll: Collection[Any], old: str, new: str | None, now: datetime) -> None:
    changes = {"$set": {"parent_id": new, "updated_at": now}, "$inc": {"revision": 1}}
    coll.update_many(  # nosemgrep: sankey-no-mongo-writes -- folder store
        {"parent_id": old}, changes
    )


def _set_graph_folder(coll: Collection[Any], flt: dict[str, Any], target: str | None) -> None:
    """Point the graphs matching ``flt`` at ``target``: the one field this store ever sets."""
    coll.update_many(  # nosemgrep: sankey-no-mongo-writes -- folder store
        flt, {"$set": {"folder_id": target}}
    )


def _ensure_folder_indexes(coll: Collection[Any]) -> None:
    keys = [("parent_id", 1), ("name_key", 1)]
    coll.create_index(keys, unique=True)  # nosemgrep: sankey-no-mongo-writes -- folder store


@contextmanager
def _name_clash() -> Iterator[None]:
    """A unique-index violation is a sibling-name clash: the pure pre-check lost a race."""
    try:
        yield
    except DuplicateKeyError:
        raise FolderNameTakenError(MSG_NAME_TAKEN) from None


# --------------------------------------------------------------------------- documents


def _encode(folder: FolderDefinition) -> dict[str, Any]:
    """The stored form: ``_id`` instead of ``id``, the derived ``name_key``, real datetimes."""
    return {
        "_id": folder.id,
        "name": folder.name,
        "name_key": name_key(folder.name),
        "parent_id": folder.parent_id,
        "schema_version": folder.schema_version,
        "revision": folder.revision,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
    }


def _definition(raw: dict[str, Any]) -> FolderDefinition:
    """The record as stored; ``name_key`` is derived data and an unknown field is ignored."""
    doc = dict(raw)
    doc["id"] = doc.get("_id")
    for field in ("created_at", "updated_at"):
        doc[field] = _aware(doc.get(field))
    return parse_folder(doc)


def _readable(raw: dict[str, Any]) -> FolderDefinition | None:
    try:
        return _definition(raw)
    except StorageError:
        logger.warning("Skipping unreadable stored folder %r", raw.get("_id"))
        return None


def _read_all(folders: Collection[Any]) -> list[FolderDefinition]:
    """Every readable folder record (unsorted); at most ``_READ_LIMIT`` documents are fetched."""
    records = (_readable(raw) for raw in folders.find({}).limit(_READ_LIMIT))
    return [folder for folder in records if folder is not None]


def _find(items: Sequence[FolderDefinition], folder_id: str) -> FolderDefinition:
    for item in items:
        if item.id == folder_id:
            return item
    raise NotFoundError(MSG_NOT_FOUND)


def _stored_state(folders: Collection[Any], folder_id: str) -> tuple[int | None, datetime | None]:
    """Revision and ``updated_at`` of the stored folder; ``NotFoundError`` when it is gone."""
    raw = folders.find_one({"_id": folder_id}, {"revision": 1, "updated_at": 1})
    if raw is None:
        raise NotFoundError(MSG_NOT_FOUND)
    revision, updated = raw.get("revision"), _aware(raw.get("updated_at"))
    return (
        revision if isinstance(revision, int) else None,
        updated if isinstance(updated, datetime) else None,
    )


def _scope_filter(folders: Collection[Any], target: str | None) -> dict[str, Any] | None:
    """The graph filter of a listing scope; ``None`` when ``target`` names no folder.

    ``None`` (and an absent field) matches the top level, and so does any id that is no folder.
    """
    if target is not None:
        if folders.find_one({"_id": target}, {"_id": 1}) is None:
            return None
        return {"folder_id": target}
    known = folders.distinct("_id")
    return {"$or": [{"folder_id": None}, {"folder_id": {"$nin": known}}]}


def _graph_counts(
    graphs: Collection[Any], items: Sequence[FolderDefinition]
) -> dict[str | None, int]:
    """Graphs directly inside each folder (a fixed pipeline over our own ids, read only)."""
    known = [item.id for item in items]
    if not known:
        return {}
    pipeline: list[dict[str, Any]] = [
        {"$match": {"folder_id": {"$in": known}}},
        {"$group": {"_id": "$folder_id", "n": {"$sum": 1}}},
    ]
    return {row["_id"]: row["n"] for row in graphs.aggregate(pipeline)}


class MongoFolderRepository:
    def __init__(
        self, clients: MongoClients, target: MongoStoreTarget, *, clock: Clock = utc_now
    ) -> None:
        self._clients = clients
        self._target = target
        self._clock = clock
        self._indexed = False

    @contextmanager
    def _session(self) -> Iterator[_Handles]:
        name = self._target.connection
        with self._clients.slot(name), mongo_errors(name, StorageError):
            try:
                client = self._clients.get(name)
            except SourceNotFoundError:
                raise StorageError(f"Storage connection '{name}' does not exist") from None
            database = primary_database(client, self._target.database)
            yield _Handles(
                graphs=database[self._target.collection],
                folders=database[self._target.folders_collection],
            )

    def _prepare(self, folders: Collection[Any]) -> None:
        """Create the unique index once per repository, before the first write."""
        if not self._indexed:
            _ensure_folder_indexes(folders)
            self._indexed = True

    # ------------------------------------------------------------------ reads

    def list_folders(self) -> list[FolderSummary]:
        with self._session() as db:
            items = _read_all(db.folders)
            counts = _graph_counts(db.graphs, items)
        return with_counts(items, counts)

    def list_definitions(self) -> list[FolderDefinition]:
        with self._session() as db:
            items = _read_all(db.folders)
        return sorted(items, key=lambda item: (name_key(item.name), item.id))

    def get_folder(self, folder_id: str) -> FolderDefinition:
        key = check_folder_id(folder_id)
        with self._session() as db:
            raw = db.folders.find_one({"_id": key})
        if raw is None:
            raise NotFoundError(MSG_NOT_FOUND)
        return _definition(raw)

    def list_in(self, scope: str, *, limit: int = 200, offset: int = 0) -> list[GraphSummary]:
        target = scope_id(scope)
        size, start = clamp_page(limit, offset)
        if size == 0:  # Mongo reads limit(0) as "no limit"
            return []
        with self._session() as db:
            flt = _scope_filter(db.folders, target)
            if flt is None:
                return []
            cursor = db.graphs.find(flt, dict(_SUMMARY_FIELDS))  # copy: mocks edit it
            rows = list(cursor.sort(list(_SORT)).skip(start).limit(size))
        return [s for s in map(_summary, rows) if s is not None]

    def count_in(self, scope: str) -> int:
        target = scope_id(scope)
        with self._session() as db:
            flt = _scope_filter(db.folders, target)
            return 0 if flt is None else db.graphs.count_documents(flt)

    # ------------------------------------------------------------------ writes

    def create_folder(self, data: FolderCreate) -> FolderDefinition:
        with self._session() as db:
            self._prepare(db.folders)
            items = _read_all(db.folders)
            validate_new_count(items)
            validate_placement(items, Placement(None, data.parent_id, data.name))
            now = self._clock()
            folder = FolderDefinition(
                id=new_folder_id(),
                name=data.name,
                parent_id=data.parent_id,
                created_at=now,
                updated_at=now,
            )
            with _name_clash():
                _insert_folder(db.folders, _encode(folder))
        return folder

    def update_folder(self, folder_id: str, data: FolderUpdate) -> FolderDefinition:
        key = check_folder_id(folder_id)
        with self._session() as db:
            self._prepare(db.folders)
            items = _read_all(db.folders)
            current = _find(items, key)
            if current.revision != data.revision:
                raise stale_error(current.revision, current.updated_at)
            parent = requested_parent(items, current, data.parent_id)
            validate_placement(items, Placement(key, parent, data.name))
            changes = {
                "name": data.name,
                "name_key": name_key(data.name),
                "parent_id": parent,
                "revision": data.revision + 1,
                "updated_at": self._clock(),
            }
            with _name_clash():
                raw = _cas_folder(db.folders, {"_id": key, "revision": data.revision}, changes)
            if raw is None:  # nothing matched {id, revision}: gone, or the revision moved on
                raise stale_error(*_stored_state(db.folders, key))
        return _definition(raw)

    def delete_folder(self, folder_id: str) -> None:
        key = check_folder_id(folder_id)
        with self._session() as db:
            self._prepare(db.folders)
            items = _read_all(db.folders)
            parent = _find(items, key).parent_id
            moving = reparent_plan(items, key)  # refuse a name clash before anything changes
            _set_graph_folder(db.graphs, {"folder_id": key}, parent)
            if _remove_folder(db.folders, key) == 0:
                raise NotFoundError(MSG_NOT_FOUND)
            if moving:
                with _name_clash():
                    _reparent_folders(db.folders, key, parent, self._clock())

    def put_folder(self, folder: FolderDefinition, *, overwrite: bool = False) -> FolderDefinition:
        with self._session() as db:
            self._prepare(db.folders)
            items = _read_all(db.folders)
            existing = next((item for item in items if item.id == folder.id), None)
            if existing is not None and not overwrite:
                raise exists_error(existing.revision, existing.updated_at)
            if existing is None:
                validate_new_count(items)
            check_name_free(items, folder.parent_id, folder.name, folder.id)
            if existing is None:
                self._insert_new(db.folders, _encode(folder))
            else:
                with _name_clash():
                    _replace_folder(db.folders, _encode(folder))
        return folder

    @staticmethod
    def _insert_new(folders: Collection[Any], doc: dict[str, Any]) -> None:
        """Insert; the unique index refused it: the id is taken, or a sibling has the name."""
        try:
            _insert_folder(folders, doc)
        except DuplicateKeyError:
            if folders.find_one({"_id": doc["_id"]}, {"_id": 1}) is None:
                raise FolderNameTakenError(MSG_NAME_TAKEN) from None
            raise exists_error(*_stored_state(folders, doc["_id"])) from None

    def move_graphs(self, ids: Sequence[str], folder_id: str | None) -> MoveReport:
        wanted = list(dict.fromkeys(check_graph_id(graph_id) for graph_id in ids))
        target = None if folder_id is None else check_folder_id(folder_id)
        with self._session() as db:
            if target is not None and db.folders.find_one({"_id": target}, {"_id": 1}) is None:
                raise NotFoundError(MSG_NOT_FOUND)
            found = set(db.graphs.distinct("_id", {"_id": {"$in": wanted}}))
            _set_graph_folder(db.graphs, {"_id": {"$in": sorted(found)}}, target)
        return MoveReport(moved=len(found), missing=[g for g in wanted if g not in found])

    def ping(self) -> None:
        """Reachable and writable: a server ping plus ``create_index`` (needs write rights)."""
        with self._session() as db:
            self._clients.ping(self._target.connection)
            _ensure_folder_indexes(db.folders)
            self._indexed = True
