"""``mongo_inspect``: database/collection listings and document samples."""

from __future__ import annotations

import datetime as dt
import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from bson import Decimal128, ObjectId
from pymongo.errors import ExecutionTimeout, OperationFailure, PyMongoError

from sankey_studio.errors import BusyError, SourceError, SourceNotFoundError, UnsafeSourceError
from sankey_studio.models import AppSettings
from sankey_studio.mongo import MongoClients
from sankey_studio.sources.mongo_inspect import (
    SAMPLE_DEFAULT,
    SAMPLE_MAX,
    SAMPLE_MIN,
    CollectionRef,
    clamp_sample_size,
    list_collections,
    list_databases,
    sample_documents,
    suggest_fields,
)
from tests.sources.test_mongo_fakes import Call, FakeMongo, fake_ctx

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.sources.base import SourceContext
    from tests.sources.conftest import FakeCtxFactory

REF = CollectionRef("test", "flows", "events")
SYSTEM_DB = "MongoDB system databases (admin, local, config) are not allowed"


# mongomock has no ``list_databases`` and its ``list_collection_names`` takes no options, so the
# listings run against ``FakeMongo``, which records the exact arguments the driver would get.

TIMEOUT = {"maxTimeMS": 15_000}  # AppSettings.mongo_timeout_ms default
# nameOnly: the server must not size (and lock) every database just to list their names.
DATABASES = {"nameOnly": True, **TIMEOUT}


# --------------------------------------------------------------------------- list_databases


def test_databases_are_listed_sorted_without_the_system_ones(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    fake = FakeMongo(names=["zeta", "admin", "flows", "local", "config", "alpha"])
    assert list_databases(mongo_fake_ctx(fake), "test") == ["alpha", "flows", "zeta"]


def test_databases_the_validator_would_refuse_are_not_offered(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    names = ["ok", "ADMIN", "Local", "a b", "a.b", "", "x" * 65, "bell\x07", "flows"]
    fake = FakeMongo(names=names)
    assert list_databases(mongo_fake_ctx(fake), "test") == ["flows", "ok"]
    assert fake.calls == [Call("list_databases", (), DATABASES)]


def test_an_empty_server_has_no_databases(mongo_fake_ctx: FakeCtxFactory) -> None:
    assert list_databases(mongo_fake_ctx(FakeMongo()), "test") == []


def test_the_database_listing_is_bounded_by_the_settings_timeout(
    app_settings: AppSettings, tmp_path: Path
) -> None:
    settings = AppSettings(mongo_connections=app_settings.mongo_connections, mongo_timeout_ms=2_500)
    fake = FakeMongo(names=["flows"])
    list_databases(fake_ctx(fake, settings, tmp_path), "test")
    assert fake.calls == [Call("list_databases", (), {"nameOnly": True, "maxTimeMS": 2_500})]


def test_the_database_cursor_is_closed_after_the_listing_and_after_a_failure(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    fake = FakeMongo(names=["flows"])
    list_databases(mongo_fake_ctx(fake), "test")
    failing = FakeMongo(names=["flows"], iter_error=PyMongoError("hunter2"))
    with pytest.raises(SourceError):
        list_databases(mongo_fake_ctx(failing), "test")
    assert [cursor.closed for cursor in fake.cursors + failing.cursors] == [True, True]


# --------------------------------------------------------------------------- list_collections


def test_collections_are_listed_sorted_without_system_ones(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    fake = FakeMongo(names=["moves", "events", "system.profile", "System.keep"])
    assert list_collections(mongo_fake_ctx(fake), "test", "flows") == [
        "System.keep",
        "events",
        "moves",
    ]


def test_collections_the_validator_would_refuse_are_not_offered(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    names = ["events", "system.users", "system.", "a$b", "", "x" * 121, "x" * 120, "b\x00c"]
    fake = FakeMongo(names=names)
    assert list_collections(mongo_fake_ctx(fake), "test", "flows") == ["events", "x" * 120]
    assert fake.path == ["flows"]
    assert fake.calls == [Call("list_collection_names", (), TIMEOUT)]


def test_the_collection_listing_is_bounded_by_the_settings_timeout(
    app_settings: AppSettings, tmp_path: Path
) -> None:
    settings = AppSettings(mongo_connections=app_settings.mongo_connections, mongo_timeout_ms=2_500)
    fake = FakeMongo(names=["events"])
    list_collections(fake_ctx(fake, settings, tmp_path), "test", "flows")
    assert fake.calls == [Call("list_collection_names", (), {"maxTimeMS": 2_500})]


class NameCase(NamedTuple):
    database: str
    message: str


BAD_DATABASES = {
    "admin": NameCase("admin", SYSTEM_DB),
    "local in capitals": NameCase("LOCAL", SYSTEM_DB),
    "config": NameCase("config", SYSTEM_DB),
    "empty": NameCase("", "invalid MongoDB database name"),
    "dot": NameCase("a.b", "invalid MongoDB database name"),
    "slash": NameCase("a/b", "invalid MongoDB database name"),
    "line break": NameCase("a\nb", "invalid MongoDB database name"),
    "bidi override": NameCase("a" + chr(0x202E) + "b", "invalid MongoDB database name"),
    "too long": NameCase("x" * 65, "invalid MongoDB database name"),
}


@pytest.mark.parametrize("case", BAD_DATABASES.values(), ids=BAD_DATABASES)
def test_list_collections_validates_the_raw_database_before_touching_a_client(
    case: NameCase, mongo_fake_ctx: FakeCtxFactory
) -> None:
    fake = FakeMongo(names=["events"])
    with pytest.raises(UnsafeSourceError) as info:
        list_collections(mongo_fake_ctx(fake), "test", case.database)
    assert info.value.message == case.message
    assert fake.calls == []
    assert fake.path == []


# --------------------------------------------------------------------------- connections


def test_an_unknown_connection_is_refused_without_creating_a_slot(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    fake = FakeMongo(names=["a"])
    ctx = mongo_fake_ctx(fake)
    calls: list[Callable[[], object]] = [
        lambda: list_databases(ctx, "nope"),
        lambda: list_collections(ctx, "nope", "flows"),
        lambda: sample_documents(ctx, CollectionRef("nope", "flows", "events")),
    ]
    for call in calls:
        with pytest.raises(SourceNotFoundError) as info:
            call()
        assert info.value.message == "Unknown MongoDB connection 'nope'"
    assert ctx.mongo._slots == {}
    assert fake.calls == []


@pytest.mark.parametrize("name", ["bad name", "<script>alert(1)</script>", "x\ny", "a" * 65, ""])
def test_an_odd_connection_name_is_never_echoed(name: str, mongo_fake_ctx: FakeCtxFactory) -> None:
    with pytest.raises(SourceNotFoundError) as info:
        list_databases(mongo_fake_ctx(FakeMongo()), name)
    assert info.value.message == "Unknown MongoDB connection '?'"


def test_a_well_formed_unknown_name_is_echoed(mongo_fake_ctx: FakeCtxFactory) -> None:
    with pytest.raises(SourceNotFoundError) as info:
        list_databases(mongo_fake_ctx(FakeMongo()), "Prod-2.db_1")
    assert info.value.message == "Unknown MongoDB connection 'Prod-2.db_1'"


# --------------------------------------------------------------------------- errors


class FailCase(NamedTuple):
    error: Exception
    message: str


FAILURES = {
    "driver": FailCase(PyMongoError("hunter2"), "MongoDB operation on 'test' failed: PyMongoError"),
    "time limit": FailCase(
        ExecutionTimeout("hunter2"), "MongoDB query on 'test' exceeded the time limit"
    ),
    "not authorised": FailCase(
        OperationFailure("hunter2", code=13), "MongoDB connection 'test' is not authorised"
    ),
}


@pytest.mark.parametrize("case", FAILURES.values(), ids=FAILURES)
def test_driver_failures_become_clean_source_errors(
    case: FailCase, mongo_fake_ctx: FakeCtxFactory
) -> None:
    ctx = mongo_fake_ctx(FakeMongo(call_error=case.error))
    calls: list[Callable[[], object]] = [
        lambda: list_databases(ctx, "test"),
        lambda: list_collections(ctx, "test", "flows"),
        lambda: sample_documents(ctx, REF),
    ]
    for call in calls:
        with pytest.raises(SourceError) as info:
            call()
        assert type(info.value) is SourceError
        assert info.value.message == case.message
        assert "hunter2" not in repr(info.value)


def test_every_call_holds_the_slot_of_its_own_connection(
    monkeypatch: pytest.MonkeyPatch, mongo_fake_ctx: FakeCtxFactory
) -> None:
    held: list[str] = []

    @contextmanager
    def record(connection: str) -> Iterator[None]:
        held.append(f"enter:{connection}")
        yield
        held.append(f"exit:{connection}")

    monkeypatch.setattr(MongoClients, "slot", lambda _self, name: record(name))
    ctx = mongo_fake_ctx(FakeMongo())
    list_databases(ctx, "test")
    list_collections(ctx, "test", "flows")
    sample_documents(ctx, REF)
    assert held == ["enter:test", "exit:test"] * 3


def test_a_busy_connection_stops_every_call_before_a_client_exists(
    monkeypatch: pytest.MonkeyPatch, mongo_fake_ctx: FakeCtxFactory
) -> None:
    def busy(_self: MongoClients, _name: str) -> Iterator[None]:
        raise BusyError("busy")

    monkeypatch.setattr(MongoClients, "slot", busy)
    fake = FakeMongo(names=["a"])
    ctx = mongo_fake_ctx(fake)
    for call in (
        lambda: list_databases(ctx, "test"),
        lambda: list_collections(ctx, "test", "flows"),
        lambda: sample_documents(ctx, REF),
    ):
        with pytest.raises(BusyError):
            call()
    assert fake.path == []
    assert fake.calls == []


# --------------------------------------------------------------------------- sample size


class ClampCase(NamedTuple):
    n: int
    expected: int


CLAMPS = {
    "very negative": ClampCase(-1_000, 1),
    "negative": ClampCase(-1, 1),
    "zero": ClampCase(0, 1),
    "one": ClampCase(1, 1),
    "two": ClampCase(2, 2),
    "the default": ClampCase(5, 5),
    "nineteen": ClampCase(19, 19),
    "twenty": ClampCase(20, 20),
    "twenty-one": ClampCase(21, 20),
    "huge": ClampCase(10**9, 20),
}


@pytest.mark.parametrize("case", CLAMPS.values(), ids=CLAMPS)
def test_the_sample_size_is_clamped_to_one_through_twenty(case: ClampCase) -> None:
    assert clamp_sample_size(case.n) == case.expected


@pytest.mark.parametrize("case", CLAMPS.values(), ids=CLAMPS)
def test_find_is_asked_for_the_clamped_size(
    case: ClampCase, mongo_fake_ctx: FakeCtxFactory
) -> None:
    fake = FakeMongo()
    sample_documents(mongo_fake_ctx(fake), REF, case.n)
    assert fake.calls == [
        Call("find", ({},), {"limit": case.expected, "max_time_ms": 15_000, "batch_size": 1})
    ]
    assert fake.path == ["flows", "events"]


def test_the_defaults_are_the_documented_ones(mongo_fake_ctx: FakeCtxFactory) -> None:
    assert (SAMPLE_MIN, SAMPLE_MAX, SAMPLE_DEFAULT) == (1, 20, 5)
    fake = FakeMongo()
    sample_documents(mongo_fake_ctx(fake), REF)
    assert fake.calls[0].kwargs["limit"] == 5


def test_the_time_cap_is_the_settings_timeout(app_settings: AppSettings, tmp_path: Path) -> None:
    settings = AppSettings(mongo_connections=app_settings.mongo_connections, mongo_timeout_ms=2_500)
    fake = FakeMongo()
    sample_documents(fake_ctx(fake, settings, tmp_path), REF, 3)
    assert fake.calls[0].kwargs["max_time_ms"] == 2_500


# --------------------------------------------------------------------------- sample content


def test_a_sample_is_json_safe_plain_data(
    source_ctx: SourceContext, mongo_client: MongoClient[Any]
) -> None:
    oid = ObjectId("0123456789abcdef01234567")
    mongo_client["flows"]["events"].insert_one(
        {
            "_id": oid,
            "when": dt.datetime(2025, 1, 2, 3, 4, 5, tzinfo=dt.UTC),
            "price": Decimal128("2.50"),
            "blob": b"\x00\x01",
            "nested": {"from": "a", "tags": ["x", "y"]},
            "note": "n" * 300,
        }
    )
    [doc] = sample_documents(source_ctx, REF)
    assert doc == {
        "_id": "0123456789abcdef01234567",
        "when": "2025-01-02T03:04:05+00:00",
        "price": "2.50",
        "blob": "<bytes 2>",
        "nested": {"from": "a", "tags": ["x", "y"]},
        "note": "n" * 200 + "...",
    }
    json.dumps(doc)


def test_a_sample_returns_at_most_the_requested_number(
    source_ctx: SourceContext, mongo_client: MongoClient[Any]
) -> None:
    mongo_client["flows"]["events"].insert_many([{"n": i} for i in range(30)])
    assert [d["n"] for d in sample_documents(source_ctx, REF, 3)] == [0, 1, 2]
    assert len(sample_documents(source_ctx, REF, 100)) == 20
    assert len(sample_documents(source_ctx, REF)) == 5
    assert len(sample_documents(source_ctx, REF, 0)) == 1


def test_an_empty_collection_has_an_empty_sample(source_ctx: SourceContext) -> None:
    assert sample_documents(source_ctx, REF) == []


def test_the_sample_cursor_is_closed_and_documents_are_converted_one_by_one(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    fake = FakeMongo([{"a": 1}, {"a": 2}])
    docs = sample_documents(mongo_fake_ctx(fake), REF)
    assert docs == [{"a": 1}, {"a": 2}]
    assert fake.cursors[0].closed is True


def test_the_cursor_is_closed_when_the_driver_fails_mid_sample(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    fake = FakeMongo([{"a": 1}], iter_error=PyMongoError("x"))
    with pytest.raises(SourceError, match=r"failed: PyMongoError$"):
        sample_documents(mongo_fake_ctx(fake), REF)
    assert fake.cursors[0].closed is True


class SampleAttack(NamedTuple):
    ref: CollectionRef
    message: str


SAMPLE_ATTACKS = {
    "admin": SampleAttack(CollectionRef("test", "admin", "users"), SYSTEM_DB),
    "local": SampleAttack(CollectionRef("test", "local", "oplog.rs"), SYSTEM_DB),
    "system collection": SampleAttack(
        CollectionRef("test", "flows", "system.users"), "MongoDB system collections are not allowed"
    ),
    "dollar collection": SampleAttack(
        CollectionRef("test", "flows", "a$b"), "invalid MongoDB collection name"
    ),
    "empty collection": SampleAttack(
        CollectionRef("test", "flows", ""), "invalid MongoDB collection name"
    ),
    "NUL in the collection": SampleAttack(
        CollectionRef("test", "flows", "a\x00b"), "invalid MongoDB collection name"
    ),
    "line break in the database": SampleAttack(
        CollectionRef("test", "fl\nows", "events"), "invalid MongoDB database name"
    ),
    "empty database": SampleAttack(
        CollectionRef("test", "", "events"), "invalid MongoDB database name"
    ),
    "bad names win over an unknown connection": SampleAttack(
        CollectionRef("nope", "admin", "events"), SYSTEM_DB
    ),
}


@pytest.mark.parametrize("case", SAMPLE_ATTACKS.values(), ids=SAMPLE_ATTACKS)
def test_sampling_validates_the_raw_namespace_first(
    case: SampleAttack, mongo_fake_ctx: FakeCtxFactory
) -> None:
    fake = FakeMongo([{"secret": 1}])
    with pytest.raises(UnsafeSourceError) as info:
        sample_documents(mongo_fake_ctx(fake), case.ref)
    assert info.value.message == case.message
    assert fake.calls == []
    assert fake.path == []


def test_suggest_fields_is_part_of_the_inspect_api() -> None:
    result = suggest_fields([{"from": "a", "to": "b", "amount": 1}])
    assert (result.source, result.target, result.value, result.category) == (
        "from",
        "to",
        "amount",
        None,
    )


def test_collection_ref_is_a_frozen_value() -> None:
    assert CollectionRef("c", "d", "k") == CollectionRef("c", "d", "k")
    assert (REF.connection, REF.database, REF.collection) == ("test", "flows", "events")
