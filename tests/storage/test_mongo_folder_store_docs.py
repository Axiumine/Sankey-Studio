# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""What the Mongo folder store writes and reads: document shape, derived keys, damaged records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from sankey_studio.errors import FolderRuleError, StorageError
from sankey_studio.models import FOLDERS_MAX, FolderUpdate
from sankey_studio.mongo import MongoClients
from sankey_studio.storage import MongoFolderRepository
from sankey_studio.storage.base import MONGO_FOLDERS_COLLECTION, MONGO_GRAPHS_COLLECTION
from tests.storage.conftest import STORE_DATABASE, STORE_TARGET
from tests.storage.folder_builders import body, fid, folder
from tests.storage.support import ID_A, ID_B, ID_C, NOW, Ticker, definition

if TYPE_CHECKING:
    from pymongo import MongoClient
    from pymongo.collection import Collection

    from sankey_studio.models import AppSettings
    from sankey_studio.storage import MongoGraphRepository

KEYS = {
    "_id",
    "name",
    "name_key",
    "parent_id",
    "schema_version",
    "revision",
    "created_at",
    "updated_at",
}


@pytest.fixture
def folders_coll(mongo_client: MongoClient[Any]) -> Collection[Any]:
    """The raw folder collection of the in-memory server (what a real server would hold)."""
    return mongo_client[STORE_DATABASE][MONGO_FOLDERS_COLLECTION]


@pytest.fixture
def graphs_coll(mongo_client: MongoClient[Any]) -> Collection[Any]:
    return mongo_client[STORE_DATABASE][MONGO_GRAPHS_COLLECTION]


def _raw(coll: Collection[Any], doc_id: str) -> dict[str, Any]:
    found: dict[str, Any] | None = coll.find_one({"_id": doc_id})
    assert found is not None
    return found


def _doc(number: int, name: Any = "ok", **changes: Any) -> dict[str, Any]:
    """A valid raw folder document; ``changes`` override or add fields."""
    base = {
        "_id": fid(number),
        "name": name,
        "name_key": str(name).casefold(),
        "parent_id": None,
        "schema_version": 1,
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return {**base, **changes}


# --------------------------------------------------------------------------- written documents


def test_a_created_folder_is_stored_with_exactly_these_fields(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    created = mongo_folders.create_folder(body("Docs"))
    assert _raw(folders_coll, created.id) == {
        "_id": created.id,
        "name": "Docs",
        "name_key": "docs",
        "parent_id": None,
        "schema_version": 1,
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    assert folders_coll.count_documents({}) == 1


class Key(NamedTuple):
    name: str
    key: str


@pytest.mark.parametrize(
    "case",
    [
        Key("Docs", "docs"),
        Key("DOCS", "docs"),
        Key("ÉCOLE", "école"),
        Key("école", "école"),  # NFC: `e` + combining acute becomes one character
        Key("Straße", "strasse"),  # casefold, not lower
    ],
)
def test_the_name_key_is_the_nfc_casefolded_name(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any], case: Key
) -> None:
    created = mongo_folders.create_folder(body(case.name))
    assert _raw(folders_coll, created.id)["name_key"] == case.key
    assert mongo_folders.get_folder(created.id).name == case.name  # the name itself is kept


@pytest.mark.parametrize(
    "name", ["$where", "a.b", "$x.y", "{}", "x\ny", "\N{RIGHT-TO-LEFT OVERRIDE}txt"]
)
def test_a_hostile_name_is_only_ever_a_value(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any], name: str
) -> None:
    created = mongo_folders.create_folder(body(name))
    inner = mongo_folders.create_folder(body(name, created.id))
    for item in (created, inner):
        assert set(_raw(folders_coll, item.id)) == KEYS
        assert mongo_folders.get_folder(item.id) == item
    assert [row.name for row in mongo_folders.list_folders()] == [name, name]


def test_the_parent_is_stored_as_null_for_a_top_folder_and_as_the_id_below_it(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    top = mongo_folders.create_folder(body("top"))
    low = mongo_folders.create_folder(body("low", top.id))
    assert _raw(folders_coll, top.id)["parent_id"] is None
    assert _raw(folders_coll, low.id)["parent_id"] == top.id


def test_the_folders_and_the_graphs_live_in_two_collections_of_one_database(
    mongo_folders: MongoFolderRepository,
    mongo_repo: MongoGraphRepository,
    mongo_client: MongoClient[Any],
) -> None:
    mongo_folders.create_folder(body("box"))
    mongo_repo.put(definition(ID_A, "g"))
    assert sorted(mongo_client[STORE_DATABASE].list_collection_names()) == [
        MONGO_FOLDERS_COLLECTION,
        MONGO_GRAPHS_COLLECTION,
    ]
    assert mongo_client[STORE_DATABASE][MONGO_FOLDERS_COLLECTION].count_documents({}) == 1
    assert mongo_client[STORE_DATABASE][MONGO_GRAPHS_COLLECTION].count_documents({}) == 1


def test_an_update_rewrites_name_key_parent_revision_and_time_and_keeps_created_at(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    box = mongo_folders.create_folder(body("box"))
    other = mongo_folders.create_folder(body("other"))
    mongo_folders.update_folder(box.id, FolderUpdate(name="BOX 2", parent_id=other.id, revision=1))
    assert _raw(folders_coll, box.id) == {
        "_id": box.id,
        "name": "BOX 2",
        "name_key": "box 2",
        "parent_id": other.id,
        "schema_version": 1,
        "revision": 2,
        "created_at": NOW,
        "updated_at": NOW + timedelta(seconds=2),
    }


def test_put_stores_the_folder_verbatim_with_a_derived_key(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    mongo_folders.put_folder(folder(3, "Kept", 2, revision=7))
    assert _raw(folders_coll, fid(3)) == _doc(3, "Kept", parent_id=fid(2), revision=7)
    mongo_folders.put_folder(folder(3, "Kept 2", revision=8), overwrite=True)
    assert _raw(folders_coll, fid(3)) == _doc(3, "Kept 2", revision=8)
    assert set(_raw(folders_coll, fid(3))) == KEYS


def test_a_delete_moves_each_child_once_and_leaves_deeper_folders_alone(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    top = mongo_folders.create_folder(body("top"))
    mid = mongo_folders.create_folder(body("mid", top.id))
    low = mongo_folders.create_folder(body("low", mid.id))
    deep = mongo_folders.create_folder(body("deep", low.id))
    mongo_folders.delete_folder(mid.id)
    moved, deeper = _raw(folders_coll, low.id), _raw(folders_coll, deep.id)
    assert (moved["parent_id"], moved["revision"]) == (top.id, 2)
    assert moved["updated_at"] == NOW + timedelta(seconds=4)
    assert (deeper["parent_id"], deeper["revision"]) == (low.id, 1)
    assert deeper["updated_at"] == deep.updated_at
    assert set(moved) == KEYS
    assert folders_coll.find_one({"_id": mid.id}) is None


def test_moving_graphs_changes_only_their_folder_field(
    mongo_folders: MongoFolderRepository,
    mongo_repo: MongoGraphRepository,
    graphs_coll: Collection[Any],
) -> None:
    box = mongo_folders.create_folder(body("box"))
    mongo_repo.put(definition(ID_A, "a"))
    mongo_repo.put(definition(ID_B, "b"))
    before = {key: _raw(graphs_coll, key) for key in (ID_A, ID_B)}
    mongo_folders.move_graphs([ID_A], box.id)
    after = {key: _raw(graphs_coll, key) for key in (ID_A, ID_B)}
    assert after[ID_B] == before[ID_B]
    assert after[ID_A] == {**before[ID_A], "folder_id": box.id}


def test_deleting_a_folder_changes_only_the_folder_field_of_its_graphs(
    mongo_folders: MongoFolderRepository,
    mongo_repo: MongoGraphRepository,
    graphs_coll: Collection[Any],
) -> None:
    box = mongo_folders.create_folder(body("box"))
    mongo_repo.put(definition(ID_A, "a").model_copy(update={"folder_id": box.id}))
    before = _raw(graphs_coll, ID_A)
    mongo_folders.delete_folder(box.id)
    assert _raw(graphs_coll, ID_A) == {**before, "folder_id": None}


# --------------------------------------------------------------------------- the index


def test_ping_creates_a_unique_index_over_the_parent_and_the_name_key(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    mongo_folders.ping()
    indexes = folders_coll.index_information()
    [spec] = [i for i in indexes.values() if i["key"] != [("_id", 1)]]
    assert spec["key"] == [("parent_id", 1), ("name_key", 1)]
    assert spec["unique"] is True
    folders_coll.insert_one(_doc(1, "same"))
    with pytest.raises(DuplicateKeyError):  # the index is what stops a racing writer
        folders_coll.insert_one(_doc(2, "SAME", name_key="same"))


def test_one_name_key_may_repeat_below_different_parents(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    mongo_folders.ping()
    folders_coll.insert_many([_doc(1, "x"), _doc(2, "x", parent_id=fid(1)), _doc(3, "y")])
    assert folders_coll.count_documents({}) == 3


# --------------------------------------------------------------------------- reading


@dataclass(slots=True)
class NaiveStore:
    """A store on a driver that hands back naive datetimes (not built ``tz_aware``)."""

    repo: MongoFolderRepository
    collection: Collection[Any]


@pytest.fixture
def naive_store(app_settings: AppSettings, clock: Ticker) -> NaiveStore:
    client: MongoClient[Any] = mongomock.MongoClient(tz_aware=False)
    clients = MongoClients(lambda: app_settings, factory=lambda _uri, _timeout: client)
    return NaiveStore(
        MongoFolderRepository(clients, STORE_TARGET, clock=clock),
        client[STORE_DATABASE][MONGO_FOLDERS_COLLECTION],
    )


def test_naive_datetimes_from_a_driver_without_tz_support_are_read_as_utc(
    naive_store: NaiveStore,
) -> None:
    created = naive_store.repo.create_folder(body("f"))
    assert _raw(naive_store.collection, created.id)["created_at"].tzinfo is None  # the premise
    stored = naive_store.repo.get_folder(created.id)
    assert stored.created_at == stored.updated_at == NOW
    assert stored.updated_at.utcoffset() == timedelta(0)
    assert [r.updated_at for r in naive_store.repo.list_folders()] == [NOW]
    assert [r.updated_at for r in naive_store.repo.list_definitions()] == [NOW]


def test_an_unknown_field_and_a_wrong_name_key_are_ignored_on_read(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    folders_coll.insert_one(_doc(1, "Real", name_key="not the key", extra={"a": 1}))
    [stored] = mongo_folders.list_definitions()
    assert (stored.id, stored.name) == (fid(1), "Real")
    assert mongo_folders.get_folder(fid(1)) == stored


class Broken(NamedTuple):
    label: str
    changes: dict[str, Any]
    message: str


BROKEN = [
    Broken("no name", {"name": None}, "Stored folder is unreadable"),
    Broken("empty name", {"name": ""}, "Stored folder is unreadable"),
    Broken("long name", {"name": "x" * 101}, "Stored folder is unreadable"),
    Broken("bad parent", {"parent_id": "nope"}, "Stored folder is unreadable"),
    Broken("zero revision", {"revision": 0}, "Stored folder is unreadable"),
    Broken("no time", {"updated_at": None}, "Stored folder is unreadable"),
    Broken(
        "newer schema",
        {"schema_version": 99},
        "Stored folder was written by a newer version of sankey-studio",
    ),
    Broken("bad schema", {"schema_version": "1"}, "Stored folder has an invalid schema version"),
]


@pytest.mark.parametrize("case", BROKEN, ids=[b.label for b in BROKEN])
def test_a_damaged_record_is_skipped_in_listings_and_get_refuses_it(
    mongo_folders: MongoFolderRepository,
    folders_coll: Collection[Any],
    caplog: pytest.LogCaptureFixture,
    case: Broken,
) -> None:
    healthy = mongo_folders.create_folder(body("healthy"))
    folders_coll.insert_one(_doc(1, **{"name": "bad", **case.changes}))
    with caplog.at_level(logging.WARNING):
        assert [f.id for f in mongo_folders.list_definitions()] == [healthy.id]
        assert [f.id for f in mongo_folders.list_folders()] == [healthy.id]
    assert [r.getMessage() for r in caplog.records] == [
        f"Skipping unreadable stored folder {fid(1)!r}"
    ] * 2
    with pytest.raises(StorageError) as info:
        mongo_folders.get_folder(fid(1))
    assert info.value.message == case.message


def test_a_damaged_record_does_not_stop_new_folders(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    folders_coll.insert_one(_doc(1, "bad", revision=0))
    created = mongo_folders.create_folder(body("fine"))
    assert [f.id for f in mongo_folders.list_definitions()] == [created.id]


# --------------------------------------------------------------------------- the size limit


class Stored(NamedTuple):
    stored: int
    read: int


@pytest.mark.parametrize(
    "case",
    [Stored(5, 5), Stored(FOLDERS_MAX, FOLDERS_MAX), Stored(FOLDERS_MAX + 1, FOLDERS_MAX + 1)],
)
def test_a_store_is_read_up_to_one_more_than_the_cap(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any], case: Stored
) -> None:
    folders_coll.insert_many([_doc(i, f"f{i}") for i in range(case.stored)])
    assert len(mongo_folders.list_definitions()) == case.read
    assert len(mongo_folders.list_folders()) == case.read


def test_a_store_that_is_far_over_the_cap_is_not_read_whole(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    folders_coll.insert_many([_doc(i, f"f{i}") for i in range(FOLDERS_MAX + 20)])
    assert len(mongo_folders.list_definitions()) == FOLDERS_MAX + 1


def test_the_real_cap_refuses_the_next_folder(
    mongo_folders: MongoFolderRepository, folders_coll: Collection[Any]
) -> None:
    folders_coll.insert_many([_doc(i, f"f{i}") for i in range(FOLDERS_MAX - 1)])
    mongo_folders.create_folder(body("the last one"))
    with pytest.raises(FolderRuleError) as info:
        mongo_folders.create_folder(body("one too many"))
    assert info.value.message == "At most 1000 collections are allowed"
    assert folders_coll.count_documents({}) == FOLDERS_MAX


# --------------------------------------------------------------------------- graph membership


def test_graphs_without_the_field_or_with_null_are_at_the_top_level(
    mongo_folders: MongoFolderRepository,
    mongo_repo: MongoGraphRepository,
    graphs_coll: Collection[Any],
) -> None:
    mongo_repo.put(definition(ID_A, "old"))
    mongo_repo.put(definition(ID_B, "null"))
    graphs_coll.update_one({"_id": ID_A}, {"$unset": {"folder_id": ""}})
    assert "folder_id" not in _raw(graphs_coll, ID_A)
    assert _raw(graphs_coll, ID_B)["folder_id"] is None
    assert sorted(r.id for r in mongo_folders.list_in("root")) == [ID_A, ID_B]
    assert mongo_folders.count_in("root") == 2


def test_a_graph_in_a_missing_folder_is_top_level_and_counts_for_no_folder(
    mongo_folders: MongoFolderRepository, mongo_repo: MongoGraphRepository
) -> None:
    box = mongo_folders.create_folder(body("box"))
    mongo_repo.put(definition(ID_A, "dangling").model_copy(update={"folder_id": fid(9)}))
    mongo_repo.put(definition(ID_B, "inside").model_copy(update={"folder_id": box.id}))
    assert [r.id for r in mongo_folders.list_in("root")] == [ID_A]
    assert [r.id for r in mongo_folders.list_in(box.id)] == [ID_B]
    assert [(r.graph_count, r.child_count) for r in mongo_folders.list_folders()] == [(1, 0)]


def test_a_graph_whose_summary_is_unreadable_is_left_out_of_a_listing(
    mongo_folders: MongoFolderRepository,
    mongo_repo: MongoGraphRepository,
    graphs_coll: Collection[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mongo_repo.put(definition(ID_A, "fine"))
    mongo_repo.put(definition(ID_C, "bad"))
    graphs_coll.update_one({"_id": ID_C}, {"$set": {"revision": "x"}})
    with caplog.at_level(logging.WARNING):
        assert [r.id for r in mongo_folders.list_in("root")] == [ID_A]
    assert [r.getMessage() for r in caplog.records] == [
        f"Skipping unreadable stored graph {ID_C!r}"
    ]
