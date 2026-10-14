"""Mongo folder store failure paths: broken driver, busy slots, lost races, bad targets."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from pydantic import SecretStr
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

from sankey_studio.errors import (
    BusyError,
    ConflictError,
    FolderNameTakenError,
    NotFoundError,
    SankeyError,
    StorageError,
)
from sankey_studio.models import AppSettings, FolderUpdate, MongoConnection
from sankey_studio.storage import MongoFolderRepository, MongoStoreTarget, mongo_folder_store
from sankey_studio.storage.base import MONGO_FOLDERS_COLLECTION
from tests.storage.conftest import STORE_DATABASE, STORE_TARGET
from tests.storage.folder_builders import body, fid, folder
from tests.storage.mongo_fakes import SlotLog, broken_clients
from tests.storage.support import ID_A

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo import MongoClient
    from pymongo.collection import Collection

    from sankey_studio.models import FolderDefinition
    from sankey_studio.mongo import MongoClients
    from tests.storage.support import Ticker

SECRET = "mongodb://user:hunter2@db.internal:27017/graphs"
UPDATE = FolderUpdate(name="x", parent_id=None, revision=1)


def _settings() -> AppSettings:
    conn = MongoConnection(name="test", uri=SecretStr("mongodb://tester:hunter2@mongo.invalid/"))
    return AppSettings(mongo_connections=[conn])


def _repo(clients: MongoClients) -> MongoFolderRepository:
    return MongoFolderRepository(clients, STORE_TARGET)


OPERATIONS: dict[str, Callable[[MongoFolderRepository], object]] = {
    "list_folders": lambda r: r.list_folders(),
    "list_definitions": lambda r: r.list_definitions(),
    "get": lambda r: r.get_folder(fid(1)),
    "list_in-top": lambda r: r.list_in("root"),
    "list_in-folder": lambda r: r.list_in(fid(1)),
    "count_in-top": lambda r: r.count_in("root"),
    "count_in-folder": lambda r: r.count_in(fid(1)),
    "create": lambda r: r.create_folder(body("f")),
    "update": lambda r: r.update_folder(fid(1), UPDATE),
    "delete": lambda r: r.delete_folder(fid(1)),
    "put": lambda r: r.put_folder(folder(1, "f")),
    "put-overwrite": lambda r: r.put_folder(folder(1, "f"), overwrite=True),
    "move": lambda r: r.move_graphs([ID_A], None),
    "move-into": lambda r: r.move_graphs([ID_A], fid(1)),
    "ping": lambda r: r.ping(),
}


# --------------------------------------------------------------------------- driver failures


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_a_driver_error_becomes_a_storage_error_without_driver_text(operation: str) -> None:
    repo = _repo(broken_clients(_settings(), PyMongoError(f"boom {SECRET}")))
    with pytest.raises(StorageError) as info:
        OPERATIONS[operation](repo)
    err = info.value
    assert err.message == "MongoDB operation on 'test' failed: PyMongoError"
    assert err.status_code == 503
    for text in (err.message, str(err), repr(err), *err.details):
        assert "hunter2" not in text
        assert "db.internal" not in text
    assert err.__cause__ is None
    assert err.__suppress_context__


def test_a_missing_write_permission_fails_the_ping() -> None:
    """``create_index`` needs write rights: a read-only user fails the ping."""
    repo = _repo(broken_clients(_settings(), OperationFailure("not allowed", 13)))
    with pytest.raises(StorageError, match="is not authorised"):
        repo.ping()


def test_an_unknown_storage_connection_is_a_storage_error(mongo_clients: MongoClients) -> None:
    repo = MongoFolderRepository(mongo_clients, MongoStoreTarget("missing", "sankey_studio"))
    for operation in OPERATIONS.values():
        with pytest.raises(StorageError) as info:
            operation(repo)
        assert info.value.message == "Storage connection 'missing' does not exist"
        assert info.value.status_code == 503


# --------------------------------------------------------------------------- slots


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_every_operation_runs_inside_the_connection_slot(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    log = SlotLog()
    log.install(monkeypatch, mongo_clients)
    with contextlib.suppress(SankeyError):  # a missing folder still used the slot
        OPERATIONS[operation](_repo(mongo_clients))
    assert log.names
    assert set(log.names) == {"test"}
    assert log.open == 0  # every slot was released again


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_a_busy_connection_is_reported_as_busy(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    SlotLog().install(monkeypatch, mongo_clients, fail_with=BusyError("busy"))
    with pytest.raises(BusyError):
        OPERATIONS[operation](_repo(mongo_clients))


# --------------------------------------------------------------------------- lost races
# A second writer slips in between the read of the siblings and the write. The pure rules saw
# an old list; the unique index is what refuses the write.


def _blind(monkeypatch: pytest.MonkeyPatch, seen: list[FolderDefinition]) -> None:
    """Make the store believe the folders are ``seen`` whatever the server holds."""
    monkeypatch.setattr(mongo_folder_store, "_read_all", lambda _folders: list(seen))


def test_a_create_that_loses_a_name_race_is_a_name_clash(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    mongo_folders.create_folder(body("Docs"))
    _blind(monkeypatch, [])
    with pytest.raises(FolderNameTakenError) as info:
        mongo_folders.create_folder(body("docs"))
    assert info.value.message == "A collection with this name already exists in the same place"
    monkeypatch.undo()
    assert [row.name for row in mongo_folders.list_folders()] == ["Docs"]


def test_an_update_that_loses_a_name_race_is_a_name_clash(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = mongo_folders.create_folder(body("box"))
    mongo_folders.create_folder(body("Taken"))
    _blind(monkeypatch, [box])
    with pytest.raises(FolderNameTakenError):
        mongo_folders.update_folder(box.id, FolderUpdate(name="taken", parent_id=None, revision=1))
    monkeypatch.undo()
    assert mongo_folders.get_folder(box.id).name == "box"


def test_a_put_that_overwrites_into_a_name_race_is_a_name_clash(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    one = mongo_folders.put_folder(folder(1, "one"))
    mongo_folders.put_folder(folder(2, "Two"))
    _blind(monkeypatch, [one])
    with pytest.raises(FolderNameTakenError):
        mongo_folders.put_folder(folder(1, "two", revision=2), overwrite=True)


def test_a_put_that_inserts_into_a_name_race_is_a_name_clash(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    mongo_folders.put_folder(folder(1, "Docs"))
    _blind(monkeypatch, [])
    with pytest.raises(FolderNameTakenError):
        mongo_folders.put_folder(folder(2, "docs"))
    monkeypatch.undo()
    assert [f.id for f in mongo_folders.list_definitions()] == [fid(1)]


def test_a_put_that_loses_an_id_race_is_an_id_conflict(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    mongo_folders.put_folder(folder(1, "first", revision=4))
    _blind(monkeypatch, [])
    with pytest.raises(ConflictError) as info:
        mongo_folders.put_folder(folder(1, "second"))
    assert info.value.message == "A collection with this id already exists"
    assert info.value.details[0] == "revision=4"
    monkeypatch.undo()
    assert mongo_folders.get_folder(fid(1)).name == "first"


def test_a_delete_whose_children_meet_a_new_sibling_is_a_name_clash(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = mongo_folders.create_folder(body("top"))
    mid = mongo_folders.create_folder(body("mid", top.id))
    kid = mongo_folders.create_folder(body("Kid", mid.id))
    mongo_folders.create_folder(body("kid", top.id))  # appears after the plan was made
    _blind(monkeypatch, [top, mid, kid])
    with pytest.raises(FolderNameTakenError):
        mongo_folders.delete_folder(mid.id)


def _lose_the_cas(monkeypatch: pytest.MonkeyPatch, coll: Collection[Any], gone: bool) -> None:
    """The compare-and-set finds no match: the folder was deleted, or someone else saved first."""

    def missed(_coll: object, flt: dict[str, Any], _changes: dict[str, Any]) -> None:
        if gone:
            coll.delete_one({"_id": flt["_id"]})
        else:
            coll.update_one({"_id": flt["_id"]}, {"$inc": {"revision": 1}})

    monkeypatch.setattr(mongo_folder_store, "_cas_folder", missed)


def test_an_update_whose_revision_moved_on_is_a_conflict_with_the_new_revision(
    mongo_folders: MongoFolderRepository,
    mongo_client: MongoClient[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = mongo_folders.create_folder(body("box"))
    coll = mongo_client[STORE_DATABASE][MONGO_FOLDERS_COLLECTION]
    _lose_the_cas(monkeypatch, coll, gone=False)
    with pytest.raises(ConflictError) as info:
        mongo_folders.update_folder(box.id, UPDATE)
    assert info.value.message == "Collection was modified since you loaded it; reload it"
    assert info.value.details[0] == "revision=2"
    assert info.value.current_updated_at == box.updated_at


def test_an_update_of_a_folder_deleted_meanwhile_is_not_found(
    mongo_folders: MongoFolderRepository,
    mongo_client: MongoClient[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = mongo_folders.create_folder(body("box"))
    _lose_the_cas(monkeypatch, mongo_client[STORE_DATABASE][MONGO_FOLDERS_COLLECTION], gone=True)
    with pytest.raises(NotFoundError) as info:
        mongo_folders.update_folder(box.id, UPDATE)
    assert info.value.message == "Folder not found"


class Odd(NamedTuple):
    changes: dict[str, Any]
    revision: int | None
    has_time: bool


@pytest.mark.parametrize(
    "case",
    [
        Odd({"revision": "x"}, None, True),
        Odd({"updated_at": "never"}, 1, False),
        Odd({"revision": "x", "updated_at": "never"}, None, False),
        Odd({}, 1, True),
    ],
    ids=["bad revision", "bad time", "both bad", "both good"],
)
def test_a_stale_report_leaves_out_what_the_record_does_not_hold_properly(
    mongo_folders: MongoFolderRepository,
    mongo_client: MongoClient[Any],
    monkeypatch: pytest.MonkeyPatch,
    case: Odd,
) -> None:
    box = mongo_folders.create_folder(body("box"))
    mongo_client[STORE_DATABASE][MONGO_FOLDERS_COLLECTION].update_one(
        {"_id": box.id}, {"$set": case.changes}
    )
    _blind(monkeypatch, [box])  # the pure rules saw a valid record
    monkeypatch.setattr(mongo_folder_store, "_cas_folder", lambda *_args: None)
    with pytest.raises(ConflictError) as info:
        mongo_folders.update_folder(box.id, UPDATE)
    assert info.value.current_revision == case.revision
    assert (info.value.current_updated_at is not None) is case.has_time


def test_a_delete_that_finds_the_record_gone_is_not_found(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = mongo_folders.create_folder(body("box"))
    monkeypatch.setattr(mongo_folder_store, "_remove_folder", lambda _coll, _id: 0)
    with pytest.raises(NotFoundError):
        mongo_folders.delete_folder(box.id)


def test_a_driver_duplicate_key_message_never_reaches_the_caller(
    mongo_folders: MongoFolderRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(_coll: object, _doc: dict[str, Any]) -> None:
        raise DuplicateKeyError(f"E11000 {SECRET}")

    monkeypatch.setattr(mongo_folder_store, "_insert_folder", refused)
    with pytest.raises(FolderNameTakenError) as info:
        mongo_folders.create_folder(body("x"))
    assert "hunter2" not in repr(info.value)
    assert info.value.__cause__ is None


# --------------------------------------------------------------------------- the target


def test_the_folders_live_in_the_documented_collection_by_default() -> None:
    target = MongoStoreTarget("test", "sankey_studio")
    assert target.folders_collection == "sankey_studio_collections"
    assert target.collection == "sankey_studio_graphs"


def test_targets_with_other_folder_collections_are_other_values() -> None:
    target = MongoStoreTarget("test", "db")
    assert target == MongoStoreTarget(
        "test", "db", "sankey_studio_graphs", "sankey_studio_collections"
    )
    assert hash(target) == hash(MongoStoreTarget("test", "db"))
    assert target != MongoStoreTarget("test", "db", folders_collection="mine")


class BadFolders(NamedTuple):
    folders: str
    message: str


BAD_COLL = "invalid MongoDB collection name"


@pytest.mark.parametrize(
    "case",
    [
        BadFolders("", BAD_COLL),
        BadFolders("a$b", BAD_COLL),
        BadFolders("x" * 121, BAD_COLL),
        BadFolders("system.profile", "MongoDB system collections are not allowed"),
        BadFolders(
            "sankey_studio_graphs", "The graphs and the folders need two different collections"
        ),
    ],
)
def test_a_bad_folder_collection_is_refused_with_a_fixed_message(case: BadFolders) -> None:
    with pytest.raises(StorageError) as info:
        MongoStoreTarget("test", "db", folders_collection=case.folders)
    assert info.value.message == case.message


def test_the_graph_collection_is_still_checked_and_the_folder_one_may_not_equal_it() -> None:
    with pytest.raises(StorageError, match="different collections"):
        MongoStoreTarget("test", "db", "mine", "mine")
    with pytest.raises(StorageError, match="system collections"):
        MongoStoreTarget("test", "db", "system.x")


@pytest.mark.parametrize("folders", ["x" * 120, "graphs.v2", "a-b_c"])
def test_the_limits_of_a_folder_collection_name_are_inclusive(folders: str) -> None:
    assert MongoStoreTarget("test", "db", folders_collection=folders).folders_collection == folders


def test_folders_in_another_collection_are_invisible(
    mongo_clients: MongoClients, clock: Ticker
) -> None:
    mine = MongoFolderRepository(mongo_clients, STORE_TARGET, clock=clock)
    other = MongoFolderRepository(
        mongo_clients, MongoStoreTarget("test", STORE_DATABASE, folders_collection="mine")
    )
    mine.create_folder(body("only here"))
    assert other.list_folders() == []
    assert len(mine.list_folders()) == 1
