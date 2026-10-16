# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``mongo_source_writes``: the only code that writes to a MongoDB source (mongomock).

Namespace refusals, the ``_id`` scoping, the 1000-document limit, driver failures that never leak
their text, permission and rejection answers, the slot and the log line.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

import mongomock.collection
import pytest
from bson import ObjectId
from pymongo.errors import (
    DuplicateKeyError,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
    WriteError,
)

from sankey_studio.errors import BusyError, SourceNotFoundError, SourceWriteError
from sankey_studio.storage import mongo_source_writes as writes
from sankey_studio.storage.base import MONGO_FOLDERS_COLLECTION, MONGO_GRAPHS_COLLECTION
from sankey_studio.storage.mongo_source_writes import (
    MONGO_WRITE_MAX_DOCS,
    SourceTarget,
    check_target,
    count_matching,
    insert_document,
    matching_ids,
    update_by_ids,
)
from tests.storage.mongo_fakes import Recorder, SlotLog, broken_clients
from tests.storage.source_write_support import (
    COLLECTION,
    DATABASE,
    SECRET,
    Fun,
    refusal,
    target,
)

if TYPE_CHECKING:
    from pymongo import MongoClient

    from sankey_studio.models import AppSettings
    from sankey_studio.mongo import MongoClients


def fill(client: MongoClient[Any], count: int, **fields: Any) -> list[Any]:
    """``count`` documents ``{"n": i, "source": "a", "target": "b", ...}``; their ids."""
    docs = [{"n": index, "source": "a", "target": "b", **fields} for index in range(count)]
    coll = client[DATABASE][COLLECTION]
    return list(coll.insert_many(docs).inserted_ids)


def stored(client: MongoClient[Any]) -> list[dict[str, Any]]:
    return sorted(client[DATABASE][COLLECTION].find({}), key=lambda doc: doc.get("n", -1))


def test_the_target_is_a_frozen_value(mongo_clients: MongoClients) -> None:
    where = target(mongo_clients)
    assert (where.clients, where.connection, where.database, where.collection) == (
        mongo_clients,
        "test",
        DATABASE,
        COLLECTION,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        where.collection = "other"  # type: ignore[misc]


def test_the_limit_is_a_thousand_documents() -> None:
    assert MONGO_WRITE_MAX_DOCS == 1_000
    assert writes.RESERVED_PREFIX == "sankey_studio_"


# --------------------------------------------------------------------------- the namespace

ALLOWED = [
    COLLECTION,
    "sankey_studio",
    "sankey",
    "my_sankey_studio_x",
    "sankey-studio_x",
    "sankey_studi_x",
]
REFUSED = [
    MONGO_GRAPHS_COLLECTION,
    MONGO_FOLDERS_COLLECTION,
    "sankey_studio_x",
    "sankey_studio_",
    "SANKEY_STUDIO_x",
    "Sankey_Studio_Graphs",
    chr(0x17F) + "ankey_studio_x",  # the long s casefolds to s
    "system.users",
    "has$dollar",
    "",
]


@pytest.mark.parametrize("collection", ALLOWED)
def test_a_collection_that_is_not_ours_is_a_target(
    mongo_clients: MongoClients, collection: str
) -> None:
    check_target(target(mongo_clients, collection))


@pytest.mark.parametrize("collection", REFUSED)
@pytest.mark.parametrize("database", [DATABASE, "other", "sankey_studio"])
def test_an_application_or_system_collection_is_never_a_target(
    mongo_clients: MongoClients, collection: str, database: str
) -> None:
    assert (
        refusal(check_target, target(mongo_clients, collection, database)) == "reserved_collection"
    )


@pytest.mark.parametrize("database", ["admin", "local", "config", "ADMIN", "", "a/b", "a.b"])
def test_system_and_malformed_databases_are_refused(
    mongo_clients: MongoClients, database: str
) -> None:
    assert refusal(check_target, target(mongo_clients, database=database)) == "reserved_collection"


def test_every_primitive_checks_the_namespace_before_any_driver_call(
    app_settings: AppSettings,
) -> None:
    reserved = target(broken_clients(app_settings, PyMongoError(SECRET)), MONGO_GRAPHS_COLLECTION)
    calls = [
        (count_matching, (reserved, {}, 2)),
        (matching_ids, (reserved, {}, 2)),
        (update_by_ids, (reserved, [1], {}, Fun)),
        (insert_document, (reserved, {"a": 1})),
    ]
    for call, args in calls:
        assert refusal(call, *args) == "reserved_collection"


# --------------------------------------------------------------------------- reads


def test_count_matching_counts_up_to_the_limit(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    fill(mongo_client, 5)
    fill(mongo_client, 2, source="z")
    where = target(mongo_clients)
    assert count_matching(where, {"source": "a"}, 100) == 5
    assert count_matching(where, {"source": "a"}, 5) == 5
    assert count_matching(where, {"source": "a"}, 3) == 3
    assert count_matching(where, {"source": "nobody"}, 3) == 0
    assert count_matching(where, {}, 100) == 7


def test_matching_ids_returns_the_ids_of_the_matching_documents(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    ids = fill(mongo_client, 3)
    fill(mongo_client, 2, source="z")
    where = target(mongo_clients)
    assert sorted(matching_ids(where, {"source": "a"}, 100)) == sorted(ids)
    assert len(matching_ids(where, {"source": "a"}, 2)) == 2
    assert matching_ids(where, {"source": "none"}, 2) == []


def test_the_server_time_limit_is_passed_only_when_given(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = Recorder()
    for name in ("count_documents", "find"):
        original = getattr(mongomock.collection.Collection, name)
        monkeypatch.setattr(mongomock.collection.Collection, name, recorder.wrap(name, original))
    where = target(mongo_clients)
    count_matching(where, {}, 2)
    count_matching(where, {}, 2, 250)
    matching_ids(where, {}, 2)
    matching_ids(where, {}, 2, 250)
    counts = recorder.named("count_documents")
    assert [kwargs for _, kwargs in counts] == [{"limit": 2}, {"limit": 2, "maxTimeMS": 250}]
    finds = recorder.named("find")
    assert [args[1] for args, _ in finds] == [{"_id": 1}, {"_id": 1}]
    assert [kwargs for _, kwargs in finds] == [{"limit": 2}, {"limit": 2, "max_time_ms": 250}]


UNSAFE_FILTERS = [
    {"$where": "1"},
    {"a": "$$USER_ROLES"},
    {"$and": [{"a": {"$function": {}}}]},
]


@pytest.mark.parametrize("flt", UNSAFE_FILTERS)
def test_an_unsafe_selection_filter_is_refused_before_the_driver(
    app_settings: AppSettings, flt: dict[str, Any]
) -> None:
    where = target(broken_clients(app_settings, PyMongoError(SECRET)))
    assert refusal(count_matching, where, flt, 2) == "unsafe_value"
    assert refusal(matching_ids, where, flt, 2) == "unsafe_value"
    assert refusal(update_by_ids, where, [1], flt, Fun) == "unsafe_value"


# --------------------------------------------------------------------------- update_by_ids


def test_only_the_listed_documents_that_still_match_are_updated(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    ids = fill(mongo_client, 4)
    others = fill(mongo_client, 2, source="z")
    coll = mongo_client[DATABASE][COLLECTION]
    coll.update_one({"_id": ids[3]}, {"$set": {"source": "changed"}})  # edited after the lookup
    flt = {"source": "a"}
    modified = update_by_ids(target(mongo_clients), [*ids, *others[:1]], flt, Fun)
    assert modified == 3
    by_id = {doc["_id"]: doc for doc in stored(mongo_client)}
    assert [by_id[one].get("cat") for one in ids[:3]] == ["Fun", "Fun", "Fun"]
    assert "cat" not in by_id[ids[3]]  # no longer matches the pair
    assert coll.count_documents({"cat": "Fun"}) == 3
    assert coll.count_documents({"source": "z", "cat": {"$exists": True}}) == 0


def test_the_count_is_what_the_server_changed(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    ids = fill(mongo_client, 3)
    mongo_client[DATABASE][COLLECTION].update_one({"_id": ids[0]}, {"$set": {"cat": "Fun"}})
    assert update_by_ids(target(mongo_clients), ids, {"source": "a"}, Fun) == 2


def test_unset_removes_the_field_only_where_it_is(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    ids = fill(mongo_client, 3, cat="Fun", keep="yes")
    assert update_by_ids(target(mongo_clients), ids, {}, {"$unset": {"cat": ""}}) == 3
    assert all("cat" not in doc and doc["keep"] == "yes" for doc in stored(mongo_client))


def test_object_ids_are_matched_as_ids(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    ids = fill(mongo_client, 2)
    assert all(isinstance(one, ObjectId) for one in ids)
    assert update_by_ids(target(mongo_clients), ids[:1], {}, Fun) == 1
    assert [doc.get("cat") for doc in stored(mongo_client)] == ["Fun", None]


@pytest.mark.parametrize(("count", "allowed"), [(0, True), (1, True), (1000, True), (1001, False)])
def test_the_document_limit_has_a_sharp_edge(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any], count: int, allowed: bool
) -> None:
    ids = [ObjectId() for _ in range(count)]
    if allowed:
        assert update_by_ids(target(mongo_clients), ids, {}, Fun) == 0
        return
    assert refusal(update_by_ids, target(mongo_clients), ids, {}, Fun) == "too_many_documents"
    assert stored(mongo_client) == []


def test_a_thousand_long_string_ids_are_updated(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    """The 64 KiB filter cap must not apply to the list of ids the database itself gave."""
    ids = [f"{index:064x}" for index in range(1000)]
    mongo_client[DATABASE][COLLECTION].insert_many(
        [{"_id": one, "source": "a", "target": "b"} for one in ids]
    )
    assert update_by_ids(target(mongo_clients), ids, {"source": "a"}, Fun) == 1000
    assert mongo_client[DATABASE][COLLECTION].count_documents({"cat": "Fun"}) == 1000


def test_an_unsafe_id_in_a_late_chunk_is_still_refused(mongo_clients: MongoClients) -> None:
    ids = [ObjectId() for _ in range(450)]
    assert refusal(update_by_ids, target(mongo_clients), [*ids, "$$USER_ROLES"], {}, Fun) == (
        "unsafe_value"
    )


BAD_UPDATES = [
    {"$inc": {"cat": 1}},
    {"$set": {"a": "x", "b": "y"}},
    {"$set": {"_id": "x"}},
    {"$set": {"cat": "=HYPERLINK()"}},
    {"$unset": {"cat": "x"}},
    {},
]


@pytest.mark.parametrize("update", BAD_UPDATES)
def test_an_update_that_is_not_one_plain_field_is_refused(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any], update: dict[str, Any]
) -> None:
    ids = fill(mongo_client, 1)
    assert refusal(update_by_ids, target(mongo_clients), ids, {}, update) == "unsafe_value"
    assert "cat" not in stored(mongo_client)[0]


def test_an_id_that_reads_as_a_server_variable_is_refused(mongo_clients: MongoClients) -> None:
    where = target(mongo_clients)
    assert refusal(update_by_ids, where, ["$$USER_ROLES"], {}, Fun) == "unsafe_value"


# --------------------------------------------------------------------------- insert_document


def test_a_document_is_inserted_as_given(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any]
) -> None:
    document = {"meta": {"from": "a", "to": "b"}, "amount": 50, "cat": "Fun", "year": 2025}
    assert insert_document(target(mongo_clients), document) == 1
    (row,) = stored(mongo_client)
    assert {key: value for key, value in row.items() if key != "_id"} == document
    assert isinstance(row["_id"], ObjectId)
    assert "_id" not in document  # the driver added it to a copy


BAD_DOCUMENTS = [
    {"_id": 1},
    {"$set": 1},
    {"a.b": 1},
    {"a": {"b": {"c": {"d": {"e": 1}}}}},
    {"a": [1]},
    {"a": float("nan")},
    {"a": "x" * 1001},
    {"a": "+1"},
    {"a": "\x00"},
]


@pytest.mark.parametrize("document", BAD_DOCUMENTS)
def test_a_document_that_is_not_plain_is_refused_and_nothing_is_stored(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any], document: dict[str, Any]
) -> None:
    assert refusal(insert_document, target(mongo_clients), document) == "unsafe_value"
    assert stored(mongo_client) == []


# --------------------------------------------------------------------------- failures


def operation_calls(where: SourceTarget) -> dict[str, Any]:
    return {
        "count": lambda: count_matching(where, {}, 2),
        "ids": lambda: matching_ids(where, {}, 2),
        "update": lambda: update_by_ids(where, [1], {}, Fun),
        "insert": lambda: insert_document(where, {"a": 1}),
    }


OPERATIONS = ["count", "ids", "update", "insert"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("code", [13, 18])
def test_a_missing_permission_is_an_expected_refusal(
    app_settings: AppSettings, operation: str, code: int
) -> None:
    clients = broken_clients(app_settings, OperationFailure(f"denied {SECRET}", code=code))
    assert refusal(operation_calls(target(clients))[operation]) == "permission_denied"


@pytest.mark.parametrize("operation", OPERATIONS)
def test_another_server_error_names_the_connection_and_the_class_only(
    app_settings: AppSettings, operation: str
) -> None:
    clients = broken_clients(app_settings, OperationFailure(f"boom {SECRET}", code=2))
    with pytest.raises(SourceWriteError) as info:
        operation_calls(target(clients))[operation]()
    assert info.value.message == "MongoDB query on 'test' failed: OperationFailure"
    assert "hunter2" not in repr(info.value)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_a_driver_failure_never_carries_its_text(app_settings: AppSettings, operation: str) -> None:
    clients = broken_clients(app_settings, PyMongoError(f"boom {SECRET}"))
    with pytest.raises(SourceWriteError) as info:
        operation_calls(target(clients))[operation]()
    assert info.value.message == "MongoDB operation on 'test' failed: PyMongoError"
    assert "hunter2" not in repr(info.value)
    assert info.value.status_code == 502


def test_an_unreachable_server_is_named_by_the_connection(app_settings: AppSettings) -> None:
    clients = broken_clients(app_settings, ServerSelectionTimeoutError(SECRET))
    with pytest.raises(SourceWriteError) as info:
        insert_document(target(clients), {"a": 1})
    assert info.value.message == "MongoDB connection 'test' is unreachable"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (WriteError(f"invalid {SECRET}", code=121), "write_rejected"),
        (WriteError("anything", code=None), "write_rejected"),
        (DuplicateKeyError("dup", code=11000), "write_rejected"),
        (WriteError("denied", code=13), "permission_denied"),
        (WriteError("denied", code=18), "permission_denied"),
    ],
    ids=["validation", "no code", "duplicate", "denied 13", "denied 18"],
)
def test_a_rejected_insert_is_an_expected_refusal(
    app_settings: AppSettings, error: WriteError, reason: str
) -> None:
    clients = broken_clients(app_settings, error)
    assert refusal(insert_document, target(clients), {"a": 1}) == reason


def test_an_unknown_connection_is_not_found(mongo_clients: MongoClients) -> None:
    where = SourceTarget(mongo_clients, "nope", DATABASE, COLLECTION)
    with pytest.raises(SourceNotFoundError):
        insert_document(where, {"a": 1})


# --------------------------------------------------------------------------- slot and log


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_call_runs_inside_the_connection_slot(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    log = SlotLog()
    log.install(monkeypatch, mongo_clients)
    operation_calls(target(mongo_clients))[operation]()
    assert log.names == ["test"]
    assert log.open == 0
    assert log.max_open == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_a_busy_connection_is_reported_as_busy(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    SlotLog().install(monkeypatch, mongo_clients, fail_with=BusyError("busy"))
    with pytest.raises(BusyError):
        operation_calls(target(mongo_clients))[operation]()


def test_each_write_logs_names_and_counts_only(
    mongo_clients: MongoClients, mongo_client: MongoClient[Any], caplog: pytest.LogCaptureFixture
) -> None:
    ids = fill(mongo_client, 2)
    where = target(mongo_clients)
    with caplog.at_level(logging.INFO, logger=writes.logger.name):
        update_by_ids(where, ids, {}, {"$set": {"cat": "Secret-Category"}})
        insert_document(where, {"note": "Secret-Value"})
        count_matching(where, {}, 5)
        matching_ids(where, {}, 5)
    assert [record.getMessage() for record in caplog.records] == [
        "source write: connection=test database=flows collection=events op=update documents=2",
        "source write: connection=test database=flows collection=events op=insert documents=1",
    ]
    assert "Secret" not in caplog.text
