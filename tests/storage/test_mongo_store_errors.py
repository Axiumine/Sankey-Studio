# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Mongo store failure paths: broken driver, unknown connection, busy slots, bad targets."""

from __future__ import annotations

import contextlib
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, NamedTuple

import pytest
from pydantic import SecretStr
from pymongo.errors import OperationFailure, PyMongoError, ServerSelectionTimeoutError

from sankey_studio.errors import BusyError, SankeyError, StorageError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.storage import MongoGraphRepository, MongoStoreTarget
from tests.storage.conftest import STORE_TARGET
from tests.storage.mongo_fakes import SlotLog, broken_clients
from tests.storage.support import ID_A, Spec, create_data, definition, update_data

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.mongo import MongoClients

SECRET = "mongodb://user:hunter2@db.internal:27017/graphs"


def _settings() -> AppSettings:
    conn = MongoConnection(name="test", uri=SecretStr("mongodb://tester:hunter2@mongo.invalid/"))
    return AppSettings(mongo_connections=[conn])


def _repo(clients: MongoClients) -> MongoGraphRepository:
    return MongoGraphRepository(clients, STORE_TARGET)


OPERATIONS: dict[str, Callable[[MongoGraphRepository], object]] = {
    "list": lambda r: r.list_graphs(),
    "count": lambda r: r.count(),
    "all_tags": lambda r: r.all_tags(),
    "get": lambda r: r.get(ID_A),
    "create": lambda r: r.create(create_data("g")),
    "update": lambda r: r.update(ID_A, update_data(1)),
    "put": lambda r: r.put(definition(ID_A, "g")),
    "put-overwrite": lambda r: r.put(definition(ID_A, "g"), overwrite=True),
    "delete": lambda r: r.delete(ID_A),
    "iter": lambda r: list(r.iter_definitions()),
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


class Failure(NamedTuple):
    error: Exception
    message: str


@pytest.mark.parametrize(
    "case",
    [
        Failure(ServerSelectionTimeoutError(SECRET), "MongoDB connection 'test' is unreachable"),
        Failure(OperationFailure(SECRET, 13), "MongoDB connection 'test' is not authorised"),
        Failure(OperationFailure(SECRET, 18), "MongoDB connection 'test' is not authorised"),
        Failure(OperationFailure(SECRET, 8000), "MongoDB query on 'test' failed: OperationFailure"),
    ],
)
def test_the_error_class_picks_the_message(case: Failure) -> None:
    repo = _repo(broken_clients(_settings(), case.error))
    with pytest.raises(StorageError) as info:
        repo.count()
    assert info.value.message == case.message


def test_ping_reports_a_dead_server(mongo_clients: MongoClients) -> None:
    repo = _repo(broken_clients(_settings(), ServerSelectionTimeoutError(SECRET)))
    with pytest.raises(StorageError, match="is unreachable"):
        repo.ping()
    _repo(mongo_clients).ping()  # the healthy fake passes


def test_ping_reports_a_missing_write_permission() -> None:
    """``create_index`` needs write rights: a read-only user fails the ping."""
    repo = _repo(broken_clients(_settings(), OperationFailure("not allowed", 13)))
    with pytest.raises(StorageError, match="is not authorised"):
        repo.ping()


# --------------------------------------------------------------------------- connection and slots


def test_an_unknown_storage_connection_is_a_storage_error(mongo_clients: MongoClients) -> None:
    repo = MongoGraphRepository(mongo_clients, MongoStoreTarget("missing", "sankey_studio"))
    for operation in OPERATIONS.values():
        with pytest.raises(StorageError) as info:
            operation(repo)
        assert info.value.message == "Storage connection 'missing' does not exist"
        assert info.value.status_code == 503


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_every_operation_runs_inside_the_connection_slot(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    log = SlotLog()
    log.install(monkeypatch, mongo_clients)
    repo = _repo(mongo_clients)
    repo.put(definition(ID_A, "seed"))
    log.names.clear()
    with contextlib.suppress(SankeyError):  # a conflict or a missing id still used the slot
        OPERATIONS[operation](repo)
    assert log.names
    assert set(log.names) == {"test"}
    assert log.open == 0  # every slot was released again


def test_the_slot_is_held_only_while_the_driver_is_called(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = SlotLog()
    log.install(monkeypatch, mongo_clients)
    repo = _repo(mongo_clients)
    for i in range(3):
        repo.put(definition(f"{i:032x}", f"g{i}"))
    stream = repo.iter_definitions()
    next(stream)
    assert log.open == 0  # a half-consumed stream does not pin a slot
    assert len(list(stream)) == 2


def test_a_busy_connection_is_reported_as_busy_not_as_a_storage_error(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = SlotLog()
    log.install(monkeypatch, mongo_clients, fail_with=BusyError("busy"))
    repo = _repo(mongo_clients)
    for operation in OPERATIONS.values():
        with pytest.raises(BusyError):
            operation(repo)


# --------------------------------------------------------------------------- the target


def test_the_default_collection_is_the_graph_collection() -> None:
    target = MongoStoreTarget("test", "sankey_studio")
    assert target.collection == "sankey_studio_graphs"
    assert (target.connection, target.database) == ("test", "sankey_studio")


def test_targets_are_values() -> None:
    target = MongoStoreTarget("test", "db")
    assert target == MongoStoreTarget("test", "db", "sankey_studio_graphs")
    assert hash(target) == hash(MongoStoreTarget("test", "db"))
    assert target != MongoStoreTarget("other", "db")
    assert target != MongoStoreTarget("test", "other")
    assert target != MongoStoreTarget("test", "db", "mine")
    with pytest.raises(FrozenInstanceError):
        target.database = "x"  # type: ignore[misc]


class BadTarget(NamedTuple):
    connection: str
    database: str
    collection: str
    message: str


SYSTEM_DB = "MongoDB system databases (admin, local, config) are not allowed"
BAD_DB = "invalid MongoDB database name"
BAD_COLL = "invalid MongoDB collection name"


@pytest.mark.parametrize(
    "case",
    [
        BadTarget("", "db", "c", "No storage connection is selected"),
        BadTarget("test", "admin", "c", SYSTEM_DB),
        BadTarget("test", "LOCAL", "c", SYSTEM_DB),
        BadTarget("test", "config", "c", SYSTEM_DB),
        BadTarget("test", "", "c", BAD_DB),
        BadTarget("test", "a.b", "c", BAD_DB),
        BadTarget("test", "a$b", "c", BAD_DB),
        BadTarget("test", "x" * 65, "c", BAD_DB),
        BadTarget("test", "db", "", BAD_COLL),
        BadTarget("test", "db", "a$b", BAD_COLL),
        BadTarget("test", "db", "x" * 121, BAD_COLL),
        BadTarget("test", "db", "system.profile", "MongoDB system collections are not allowed"),
    ],
)
def test_bad_targets_are_refused_with_a_fixed_message(case: BadTarget) -> None:
    with pytest.raises(StorageError) as info:
        MongoStoreTarget(case.connection, case.database, case.collection)
    assert info.value.message == case.message


@pytest.mark.parametrize(
    ("database", "collection"),
    [("x" * 64, "c"), ("db", "x" * 120), ("a-b_c", "graphs.v2")],
)
def test_the_limits_of_a_target_are_inclusive(database: str, collection: str) -> None:
    target = MongoStoreTarget("test", database, collection)
    assert (target.database, target.collection) == (database, collection)


def test_a_graph_in_another_collection_is_invisible(mongo_clients: MongoClients) -> None:
    mine = MongoGraphRepository(mongo_clients, MongoStoreTarget("test", "sankey_studio"))
    other = MongoGraphRepository(mongo_clients, MongoStoreTarget("test", "sankey_studio", "mine"))
    mine.create(create_data("only here", Spec()))
    assert other.count() == 0
    assert mine.count() == 1
