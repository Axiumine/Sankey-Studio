"""``MongoDataSource`` against fakes: exact driver calls, error mapping, cursors, slots, safety."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import pytest
from bson.errors import InvalidBSON
from pymongo.errors import (
    ExecutionTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from sankey_studio.errors import BusyError, SourceError, SourceNotFoundError, UnsafeSourceError
from sankey_studio.models import AppSettings, MongoSource
from sankey_studio.mongo import MongoClients
from sankey_studio.sources import open_source
from sankey_studio.sources.base import Diagnostics, SourceContext
from tests.sources.test_mongo_fakes import Call, FakeMongo, fake_ctx

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path

    from sankey_studio.models import RawLink
    from sankey_studio.sources.base import DataSource
    from tests.conftest import ConnectionFactory
    from tests.sources.conftest import FakeCtxFactory, FakeRunner, SpecFactory

PROJECTION = {"source": 1, "target": 1, "value": 1, "_id": 0}
GOOD = {"source": "a", "target": "b", "value": 1}
CATEGORY_WARNING = (
    "Categories ignored (entries kept uncategorised): 1 not a single text/number value"
)


def stream_of(source: DataSource, diag: Diagnostics) -> Generator[RawLink]:
    """``iter_links`` as the generator it is (so a test can ``close`` it)."""
    return cast("Generator[RawLink]", source.iter_links(diag))


def closed(fake: FakeMongo) -> bool:
    return fake.cursors[0].closed


def docs(count: int) -> list[dict[str, Any]]:
    return [{"source": "a", "target": f"t{i}", "value": 1} for i in range(count)]


# --------------------------------------------------------------------------- driver calls


def test_find_receives_exactly_these_arguments(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(docs(2))
    result = mongo_fake_run(fake, mongo_spec())
    assert len(result.rows) == 2
    assert fake.path == ["flows", "events"]
    assert fake.calls == [
        Call(
            "find",
            ({}, PROJECTION),
            {"limit": 10_001, "max_time_ms": 15_000, "batch_size": 1_000},
        )
    ]


def test_find_uses_the_filter_the_fields_and_the_source_time_cap(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo()
    spec = mongo_spec(
        database="other",
        collection="moves",
        filter={"kind": "x"},
        source_field="m.from",
        value_field=None,
        category_field="m.k",
        limit=7,
        max_time_ms=2_500,
    )
    mongo_fake_run(fake, spec)
    assert fake.path == ["other", "moves"]
    projection = {"m.from": 1, "target": 1, "m.k": 1, "_id": 0}
    assert fake.calls == [
        Call(
            "find",
            ({"kind": "x"}, projection),
            {"limit": 8, "max_time_ms": 2_500, "batch_size": 1_000},
        )
    ]


def test_aggregate_receives_exactly_these_arguments(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(docs(1))
    spec = mongo_spec(mode="aggregate", pipeline=[{"$match": {}}], max_time_ms=3_000)
    mongo_fake_run(fake, spec)
    assert fake.path == ["flows", "events"]
    assert fake.calls == [
        Call(
            "aggregate",
            ([{"$match": {}}, {"$limit": 10_001}],),
            {"allowDiskUse": False, "maxTimeMS": 3_000, "batchSize": 1_000},
        )
    ]


def test_the_server_limit_is_the_spec_limit_whatever_max_links_says(
    app_settings: AppSettings, tmp_path: Path, mongo_spec: SpecFactory
) -> None:
    """``max_links`` caps usable rows, not documents: skipped documents must not eat the cap.
    The server is asked for one document past the spec limit (it proves the truncation)."""
    capped = AppSettings(mongo_connections=app_settings.mongo_connections, max_links=100)
    find, aggregate = FakeMongo(), FakeMongo()
    ctx = fake_ctx(find, capped, tmp_path)
    list(open_source(mongo_spec(limit=5_000), ctx).iter_links(Diagnostics()))
    spec = mongo_spec(limit=5_000, mode="aggregate", pipeline=[{"$match": {}}])
    list(open_source(spec, fake_ctx(aggregate, capped, tmp_path)).iter_links(Diagnostics()))
    assert find.calls[0].kwargs["limit"] == 5_001
    assert aggregate.calls[0].args == ([{"$match": {}}, {"$limit": 5_001}],)


# --------------------------------------------------------------------------- error mapping


class ErrorCase(NamedTuple):
    error: Exception
    message: str


ERRORS = {
    "unreachable": ErrorCase(
        ServerSelectionTimeoutError("mongodb://u:hunter2@h"),
        "MongoDB connection 'test' is unreachable",
    ),
    "time limit": ErrorCase(
        ExecutionTimeout("hunter2"), "MongoDB query on 'test' exceeded the time limit"
    ),
    "unauthorised": ErrorCase(
        OperationFailure("hunter2", code=13), "MongoDB connection 'test' is not authorised"
    ),
    "authentication failed": ErrorCase(
        OperationFailure("hunter2", code=18), "MongoDB connection 'test' is not authorised"
    ),
    "other operation failure": ErrorCase(
        OperationFailure("hunter2", code=2), "MongoDB query on 'test' failed: OperationFailure"
    ),
    "driver error": ErrorCase(
        PyMongoError("hunter2"), "MongoDB operation on 'test' failed: PyMongoError"
    ),
    "bad bson": ErrorCase(
        InvalidBSON("hunter2"), "MongoDB operation on 'test' failed: InvalidBSON"
    ),
    "value error": ErrorCase(
        ValueError("hunter2"), "MongoDB operation on 'test' failed: ValueError"
    ),
    "type error": ErrorCase(TypeError("hunter2"), "MongoDB operation on 'test' failed: TypeError"),
    "overflow": ErrorCase(
        OverflowError("hunter2"), "MongoDB operation on 'test' failed: OverflowError"
    ),
}


def assert_clean_source_error(info: pytest.ExceptionInfo[SourceError], message: str) -> None:
    assert type(info.value) is SourceError
    assert info.value.message == message
    assert "hunter2" not in repr(info.value)
    assert info.value.__cause__ is None  # the driver's own text is not chained either
    assert info.value.__suppress_context__ is True


@pytest.mark.parametrize("case", ERRORS.values(), ids=ERRORS)
def test_a_driver_error_from_find_becomes_a_clean_source_error(
    case: ErrorCase, mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    with pytest.raises(SourceError) as info:
        mongo_fake_run(FakeMongo(call_error=case.error), mongo_spec())
    assert_clean_source_error(info, case.message)


@pytest.mark.parametrize("case", ERRORS.values(), ids=ERRORS)
def test_a_driver_error_from_aggregate_becomes_a_clean_source_error(
    case: ErrorCase, mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    spec = mongo_spec(mode="aggregate", pipeline=[{"$match": {}}])
    with pytest.raises(SourceError) as info:
        mongo_fake_run(FakeMongo(call_error=case.error), spec)
    assert_clean_source_error(info, case.message)


@pytest.mark.parametrize("case", ERRORS.values(), ids=ERRORS)
def test_a_driver_error_in_the_middle_of_the_stream_is_mapped_too(
    case: ErrorCase, mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(docs(3), iter_error=case.error)
    with pytest.raises(SourceError) as info:
        mongo_fake_run(fake, mongo_spec())
    assert_clean_source_error(info, case.message)
    assert fake.cursors[0].served == 3
    assert fake.cursors[0].closed is True


def test_the_connection_name_is_in_the_message(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(call_error=PyMongoError("x"))
    with pytest.raises(SourceError, match=r"^MongoDB operation on 'test' failed: PyMongoError$"):
        mongo_fake_run(fake, mongo_spec())


# --------------------------------------------------------------------------- cursors


def test_the_cursor_is_closed_when_the_stream_is_exhausted(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(docs(2))
    mongo_fake_run(fake, mongo_spec())
    assert [cursor.closed for cursor in fake.cursors] == [True]


def test_the_cursor_is_closed_when_the_consumer_gives_up(
    mongo_fake_ctx: FakeCtxFactory, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(docs(5))
    stream = stream_of(open_source(mongo_spec(), mongo_fake_ctx(fake)), Diagnostics())
    assert next(stream) == ("a", "t0", 1.0, None)
    assert closed(fake) is False
    stream.close()
    assert closed(fake) is True
    assert fake.cursors[0].served == 1


def test_the_cursor_is_closed_when_strict_mode_raises(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo([GOOD, {"source": "a", "target": "b"}, GOOD])
    with pytest.raises(SourceError, match="document 2: value field 'value' is missing"):
        mongo_fake_run(fake, mongo_spec(), strict=True)
    assert fake.cursors[0].closed is True
    assert fake.cursors[0].served == 2


def test_nothing_is_touched_before_the_first_row_is_asked_for(
    mongo_fake_ctx: FakeCtxFactory, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(docs(1))
    stream = stream_of(open_source(mongo_spec(), mongo_fake_ctx(fake)), Diagnostics())
    assert fake.calls == []
    assert fake.path == []
    assert list(stream) == [("a", "t0", 1.0, None)]


def test_category_problems_are_reported_even_when_the_stream_ends_early(
    mongo_fake_ctx: FakeCtxFactory, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo([{**GOOD, "category": ["x"]}, {**GOOD, "category": ["y"]}])
    diag = Diagnostics()
    source = open_source(mongo_spec(category_field="category"), mongo_fake_ctx(fake))
    stream = stream_of(source, diag)
    next(stream)
    stream.close()
    assert diag.warnings == [CATEGORY_WARNING]


def test_category_problems_are_reported_when_the_driver_fails_later(
    mongo_fake_ctx: FakeCtxFactory, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo([{**GOOD, "category": [1]}], iter_error=PyMongoError("x"))
    diag = Diagnostics()
    source = open_source(mongo_spec(category_field="category"), mongo_fake_ctx(fake))
    with pytest.raises(SourceError):
        list(source.iter_links(diag))
    assert diag.warnings == [CATEGORY_WARNING]


def test_the_truncation_and_text_warnings_need_a_finished_stream(
    mongo_fake_ctx: FakeCtxFactory, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo([{**GOOD, "value": "2"}, GOOD, GOOD])  # the fake ignores the server limit
    diag = Diagnostics()
    stream = stream_of(open_source(mongo_spec(limit=2), mongo_fake_ctx(fake)), diag)
    next(stream)
    stream.close()
    assert diag.warnings == []
    rows = list(open_source(mongo_spec(limit=2), mongo_fake_ctx(fake)).iter_links(diag))
    assert [row[2] for row in rows] == [2.0, 1.0]
    assert diag.warnings == ["Read 1 text value(s) as numbers", "Result truncated at limit 2"]
    assert fake.cursors[1].served == 3
    assert fake.cursors[1].closed is True


# --------------------------------------------------------------------------- slots


class Recorder:
    """Records the order of slot entry/exit and client construction."""

    def __init__(self) -> None:
        self.events: list[str] = []

    @contextmanager
    def slot(self, connection: str) -> Iterator[None]:
        self.events.append(f"enter:{connection}")
        try:
            yield
        finally:
            self.events.append(f"exit:{connection}")

    def context(self, fake: FakeMongo, settings: AppSettings, sources_dir: Path) -> SourceContext:
        def factory(_uri: str, _timeout_ms: int) -> Any:
            self.events.append("client")
            return fake

        clients = MongoClients(lambda: settings, factory=factory)
        return SourceContext(settings=settings, sources_dir=sources_dir, mongo=clients)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()

    def slot(_clients: MongoClients, connection: str) -> AbstractContextManager[None]:
        return rec.slot(connection)

    monkeypatch.setattr(MongoClients, "slot", slot)
    return rec


def test_the_slot_is_held_around_the_client_and_the_whole_stream(
    recorder: Recorder, app_settings: AppSettings, tmp_path: Path, mongo_spec: SpecFactory
) -> None:
    ctx = recorder.context(FakeMongo(docs(2)), app_settings, tmp_path)
    stream = stream_of(open_source(mongo_spec(), ctx), Diagnostics())
    assert recorder.events == []
    next(stream)
    assert recorder.events == ["enter:test", "client"]
    list(stream)
    assert recorder.events == ["enter:test", "client", "exit:test"]


def test_the_slot_is_released_when_the_consumer_gives_up(
    recorder: Recorder, app_settings: AppSettings, tmp_path: Path, mongo_spec: SpecFactory
) -> None:
    ctx = recorder.context(FakeMongo(docs(2)), app_settings, tmp_path)
    stream = stream_of(open_source(mongo_spec(), ctx), Diagnostics())
    next(stream)
    stream.close()
    assert recorder.events == ["enter:test", "client", "exit:test"]


def test_the_slot_is_released_when_the_driver_fails(
    recorder: Recorder, app_settings: AppSettings, tmp_path: Path, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(call_error=PyMongoError("x"))
    ctx = recorder.context(fake, app_settings, tmp_path)
    with pytest.raises(SourceError):
        list(open_source(mongo_spec(), ctx).iter_links(Diagnostics()))
    assert recorder.events == ["enter:test", "client", "exit:test"]


def test_a_busy_connection_is_reported_as_it_is_and_no_client_is_built(
    monkeypatch: pytest.MonkeyPatch,
    mongo_fake_ctx: FakeCtxFactory,
    mongo_spec: SpecFactory,
) -> None:
    message = "MongoDB connection 'test' is busy; try again shortly"

    def busy(_self: MongoClients, _name: str) -> Iterator[None]:
        raise BusyError(message)

    monkeypatch.setattr(MongoClients, "slot", busy)
    fake = FakeMongo(docs(1))
    with pytest.raises(BusyError) as info:
        list(stream_of(open_source(mongo_spec(), mongo_fake_ctx(fake)), Diagnostics()))
    assert info.value.message == message
    assert fake.path == []
    assert fake.calls == []


# --------------------------------------------------------------------------- safety


class AttackCase(NamedTuple):
    fields: dict[str, Any]
    message: str


ATTACKS = {
    "admin database": AttackCase(
        {"database": "admin"}, "MongoDB system databases (admin, local, config) are not allowed"
    ),
    "local database in other case": AttackCase(
        {"database": "LOCAL"}, "MongoDB system databases (admin, local, config) are not allowed"
    ),
    "config database": AttackCase(
        {"database": "config"}, "MongoDB system databases (admin, local, config) are not allowed"
    ),
    "dotted database": AttackCase({"database": "a.b"}, "invalid MongoDB database name"),
    "database with a line break": AttackCase(
        {"database": "fl\nows"}, "invalid MongoDB database name"
    ),
    "system collection": AttackCase(
        {"collection": "system.users"}, "MongoDB system collections are not allowed"
    ),
    "collection with a dollar": AttackCase(
        {"collection": "a$b"}, "invalid MongoDB collection name"
    ),
    "empty collection": AttackCase({"collection": ""}, "invalid MongoDB collection name"),
    "server-side code in the filter": AttackCase(
        {"filter": {"$where": "sleep(1000)"}}, "MongoDB operator $where is not allowed (read-only)"
    ),
    "a write stage": AttackCase(
        {"mode": "aggregate", "pipeline": [{"$out": "stolen"}]},
        "MongoDB operator $out is not allowed (read-only)",
    ),
    "a system collection through $lookup": AttackCase(
        {
            "mode": "aggregate",
            "pipeline": [{"$lookup": {"from": "system.users", "pipeline": [], "as": "x"}}],
        },
        "MongoDB system collections are not allowed",
    ),
}


@pytest.mark.parametrize("case", ATTACKS.values(), ids=ATTACKS)
def test_unsafe_specs_are_refused_before_any_client_is_touched(
    case: AttackCase, mongo_fake_ctx: FakeCtxFactory, mongo_spec: SpecFactory
) -> None:
    """``model_construct`` skips the model validators, so this is the second lock."""
    base = mongo_spec().model_dump()
    spec = MongoSource.model_construct(**{**base, **case.fields})
    fake = FakeMongo(docs(1))
    with pytest.raises(UnsafeSourceError) as info:
        list(open_source(spec, mongo_fake_ctx(fake)).iter_links(Diagnostics()))
    assert info.value.message == case.message
    assert fake.path == []
    assert fake.calls == []


def test_an_unknown_connection_is_refused_before_a_slot_or_client_exists(
    mongo_fake_ctx: FakeCtxFactory, mongo_spec: SpecFactory
) -> None:
    fake = FakeMongo(docs(1))
    ctx = mongo_fake_ctx(fake)
    with pytest.raises(SourceNotFoundError) as info:
        list(open_source(mongo_spec(connection="nope"), ctx).iter_links(Diagnostics()))
    assert info.value.message == "Unknown MongoDB connection 'nope'"
    assert ctx.mongo._slots == {}
    assert fake.calls == []


def test_a_connection_without_default_database_needs_one_on_the_source(
    make_connection: ConnectionFactory, tmp_path: Path, mongo_spec: SpecFactory
) -> None:
    settings = AppSettings(mongo_connections=[make_connection(default_database=None)])
    fake = FakeMongo(docs(1))
    ctx = fake_ctx(fake, settings, tmp_path)
    with pytest.raises(SourceError) as info:
        list(open_source(mongo_spec(), ctx).iter_links(Diagnostics()))
    assert type(info.value) is SourceError
    assert info.value.message == (
        "MongoDB connection 'test' has no default database; choose a database on the source"
    )
    assert fake.calls == []
    rows = list(open_source(mongo_spec(database="flows"), ctx).iter_links(Diagnostics()))
    assert rows == [("a", "t0", 1.0, None)]
    assert fake.path == ["flows", "events"]


def test_the_default_database_is_used_unless_the_source_names_one(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    default = FakeMongo()
    mongo_fake_run(default, mongo_spec())
    assert default.path == ["flows", "events"]
    named = FakeMongo()
    mongo_fake_run(named, mongo_spec(database="other"))
    assert named.path == ["other", "events"]
