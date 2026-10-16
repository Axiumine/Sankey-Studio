"""``mongo``: exact driver-error messages, the slot wait and the client-creation failure text.

The messages reach the UI and the logs, so they are compared whole: they must name the
connection and the exception CLASS and nothing the driver put in ``str(exc)`` (URIs, passwords).
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from bson.errors import BSONError, InvalidDocument
from pydantic import SecretStr
from pymongo.errors import (
    AutoReconnect,
    ConfigurationError,
    ExecutionTimeout,
    NetworkTimeout,
    NotPrimaryError,
    OperationFailure,
    ServerSelectionTimeoutError,
    WriteConcernError,
    WriteError,
    WTimeoutError,
)

import sankey_studio.mongo as mongo_module
from sankey_studio.errors import BusyError, SankeyError, SourceError, StorageError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.mongo import MongoClients, mongo_errors

LEAK = "mongodb://u:hunter2@leak.invalid password=hunter2"

# --------------------------------------------------------------------------- mongo_errors

MESSAGES = [
    (ServerSelectionTimeoutError(LEAK), "MongoDB connection 'conn' is unreachable"),
    (ExecutionTimeout(LEAK, code=50), "MongoDB query on 'conn' exceeded the time limit"),
    (OperationFailure(LEAK, code=13), "MongoDB connection 'conn' is not authorised"),
    (OperationFailure(LEAK, code=18), "MongoDB connection 'conn' is not authorised"),
    (OperationFailure(LEAK, code=2), "MongoDB query on 'conn' failed: OperationFailure"),
    (OperationFailure(LEAK), "MongoDB query on 'conn' failed: OperationFailure"),
    (WriteError(LEAK, code=121), "MongoDB query on 'conn' failed: OperationFailure"),
    # replica-set failover: the person is told to retry, and a maybe-applied write says so
    (
        NotPrimaryError(LEAK),
        "MongoDB connection 'conn' has no primary right now; try again shortly",
    ),
    (
        AutoReconnect(LEAK),
        (
            "MongoDB connection 'conn' was interrupted (AutoReconnect); try again shortly. "
            "A write in flight may have been applied"
        ),
    ),
    (
        NetworkTimeout(LEAK),
        (
            "MongoDB connection 'conn' was interrupted (NetworkTimeout); try again shortly. "
            "A write in flight may have been applied"
        ),
    ),
    (
        WriteConcernError(LEAK, code=100),
        "MongoDB write on 'conn' was not confirmed by enough members; it may have been applied",
    ),
    (
        WTimeoutError(LEAK, code=64),
        "MongoDB write on 'conn' was not confirmed by enough members; it may have been applied",
    ),
    (ConfigurationError(LEAK), "MongoDB operation on 'conn' failed: ConfigurationError"),
    (InvalidDocument(LEAK), "MongoDB operation on 'conn' failed: InvalidDocument"),
    (BSONError(LEAK), "MongoDB operation on 'conn' failed: BSONError"),
    (ValueError(LEAK), "MongoDB operation on 'conn' failed: ValueError"),
    (TypeError(LEAK), "MongoDB operation on 'conn' failed: TypeError"),
    (OverflowError(LEAK), "MongoDB operation on 'conn' failed: OverflowError"),
]


@pytest.mark.parametrize("error", [SourceError, StorageError])
@pytest.mark.parametrize(("exc", "message"), MESSAGES)
def test_every_driver_failure_has_one_exact_message(
    exc: Exception, message: str, error: type[SankeyError]
) -> None:
    with pytest.raises(error) as info, mongo_errors("conn", error):
        raise exc
    assert type(info.value) is error
    assert info.value.message == message
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


def test_the_default_error_type_is_source_error() -> None:
    with pytest.raises(SourceError) as info, mongo_errors("conn"):
        raise ValueError(LEAK)
    assert type(info.value) is SourceError


def test_mongo_errors_passes_a_clean_block_and_domain_errors_through() -> None:
    with mongo_errors("conn"):
        value = 1
    assert value == 1
    boom = BusyError("already mapped")
    with pytest.raises(BusyError) as info, mongo_errors("conn"):
        raise boom
    assert info.value is boom


def test_a_driver_error_that_is_not_listed_is_not_swallowed() -> None:
    with pytest.raises(KeyError), mongo_errors("conn"):
        raise KeyError(LEAK)


# --------------------------------------------------------------------------- client creation


def _settings(timeout_ms: int = 2_500) -> AppSettings:
    return AppSettings(
        mongo_connections=[MongoConnection(name="fast", uri=SecretStr("mongodb://fast.invalid/"))],
        mongo_timeout_ms=timeout_ms,
    )


@pytest.mark.parametrize("exc", [ConfigurationError, ValueError, TypeError, OverflowError])
def test_a_failing_factory_reports_the_class_name_only(exc: type[Exception]) -> None:
    def factory(_uri: str, _timeout: int) -> Any:
        raise exc(LEAK)

    with pytest.raises(StorageError) as info:
        MongoClients(_settings, factory=factory).get("fast")
    assert info.value.message == f"MongoDB connection 'fast' could not be created: {exc.__name__}"


# --------------------------------------------------------------------------- slot wait


class FakeSemaphore:
    """Records the constructor value, every ``acquire`` timeout and the releases."""

    def __init__(self, value: int, *, grant: bool) -> None:
        self.value = value
        self.grant = grant
        self.timeouts: list[float | None] = []
        self.released = 0

    def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
        assert blocking is True
        self.timeouts.append(timeout)
        return self.grant

    def release(self) -> None:
        self.released += 1


class Slots:
    """Swaps ``threading.BoundedSemaphore`` for ``FakeSemaphore`` inside ``sankey_studio.mongo``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, grant: bool) -> None:
        self.made: list[FakeSemaphore] = []
        self.grant = grant
        fake = SimpleNamespace(Lock=threading.Lock, BoundedSemaphore=self._make)
        monkeypatch.setattr(mongo_module, "threading", fake)

    def _make(self, value: int) -> FakeSemaphore:
        self.made.append(FakeSemaphore(value, grant=self.grant))
        return self.made[-1]


@pytest.mark.parametrize(
    ("timeout_ms", "seconds"), [(500, 0.5), (1_000, 1.0), (2_500, 2.5), (300_000, 300.0)]
)
def test_the_slot_wait_is_the_mongo_timeout_in_seconds(
    monkeypatch: pytest.MonkeyPatch, timeout_ms: int, seconds: float
) -> None:
    slots = Slots(monkeypatch, grant=True)
    clients = MongoClients(lambda: _settings(timeout_ms))
    with clients.slot("fast"):
        assert slots.made[0].released == 0  # held for the whole block
    assert slots.made[0].timeouts == [seconds]
    assert slots.made[0].released == 1


def test_a_busy_slot_raises_after_the_wait_and_releases_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slots = Slots(monkeypatch, grant=False)
    clients = MongoClients(lambda: _settings(1_500))
    with pytest.raises(BusyError) as info, clients.slot("fast"):
        pytest.fail("the body must not run when no slot was granted")
    assert info.value.message == "MongoDB connection 'fast' is busy; try again shortly"
    assert slots.made[0].timeouts == [1.5]
    assert slots.made[0].released == 0


def test_the_slot_is_released_when_the_body_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    slots = Slots(monkeypatch, grant=True)
    clients = MongoClients(_settings)
    with pytest.raises(RuntimeError), clients.slot("fast"):
        raise RuntimeError
    assert slots.made[0].released == 1


def test_one_bounded_semaphore_per_connection_sized_by_the_module_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slots = Slots(monkeypatch, grant=True)
    clients = MongoClients(_settings)
    for name in ("fast", "slow", "fast"):
        with clients.slot(name):
            pass
    used = [sem for sem in slots.made if sem.timeouts]  # `setdefault` may build spare ones
    assert [sem.value for sem in used] == [mongo_module.MAX_CONCURRENT_PER_CONNECTION] * 2
    assert [(len(sem.timeouts), sem.released) for sem in used] == [(2, 2), (1, 1)]
