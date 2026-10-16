# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests for ``mongo.MongoClients``: no global lock around client construction,
error mapping without leaking details, bounded concurrency, pool/timeout options."""

from __future__ import annotations

import threading
from contextlib import ExitStack
from typing import Any

import mongomock
import pytest
from pydantic import SecretStr
from pymongo.errors import (
    ConfigurationError,
    ExecutionTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
)

import sankey_studio.mongo as mongo_module
from sankey_studio.errors import BusyError, SourceError, SourceNotFoundError, StorageError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.mongo import MongoClients, default_factory, mongo_errors


class _FakeClient:
    """Stand-in client that records ``close()``."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _settings(timeout_ms: int = 500) -> AppSettings:
    return AppSettings(
        mongo_connections=[
            MongoConnection(name="slow", uri=SecretStr("mongodb://slow.invalid/")),
            MongoConnection(name="fast", uri=SecretStr("mongodb://fast.invalid/")),
        ],
        mongo_timeout_ms=timeout_ms,
    )


def test_slow_client_construction_does_not_block_other_connections() -> None:
    release = threading.Event()
    started = threading.Event()

    def factory(uri: str, _timeout: int) -> Any:
        if "slow" in uri:
            started.set()
            assert release.wait(10)
        return mongomock.MongoClient()

    settings = _settings()
    clients = MongoClients(lambda: settings, factory=factory)
    slow = threading.Thread(target=lambda: clients.get("slow"))
    slow.start()
    try:
        assert started.wait(5)
        done: list[Any] = []
        fast = threading.Thread(target=lambda: done.append(clients.get("fast")))
        fast.start()
        fast.join(timeout=3)
        assert not fast.is_alive(), "get('fast') was blocked behind the slow factory"
        assert done
    finally:
        release.set()
        slow.join(timeout=5)
    clients.close()


def test_construction_race_keeps_one_client_and_closes_the_loser() -> None:
    created: list[Any] = []
    gate = threading.Barrier(2)

    def factory(_uri: str, _timeout: int) -> Any:
        client = _FakeClient()
        created.append(client)
        gate.wait(5)  # both threads are inside the factory at the same time
        return client

    settings = _settings()
    clients = MongoClients(lambda: settings, factory=factory)
    results: list[Any] = []
    threads = [
        threading.Thread(target=lambda: results.append(clients.get("fast"))) for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert len(created) == 2
    assert results[0] is results[1]
    assert sum(c.closed for c in created) == 1
    assert not results[0].closed


def test_editing_a_uri_replaces_and_closes_the_stale_client() -> None:
    clients_made: list[Any] = []

    def factory(_uri: str, _timeout: int) -> Any:
        clients_made.append(_FakeClient())
        return clients_made[-1]

    box = {"s": _settings()}
    clients = MongoClients(lambda: box["s"], factory=factory)
    first = clients.get("fast")
    box["s"] = AppSettings(
        mongo_connections=[MongoConnection(name="fast", uri=SecretStr("mongodb://other.invalid/"))],
    )
    second = clients.get("fast")
    assert first is not second
    assert clients_made[0].closed


def test_unknown_connection_is_not_found() -> None:
    clients = MongoClients(_settings)
    with pytest.raises(SourceNotFoundError):
        clients.get("nope")


def test_factory_failures_are_mapped_without_leaking() -> None:
    def factory(uri: str, _timeout: int) -> Any:
        raise ValueError(f"bad uri {uri} password=hunter2")

    clients = MongoClients(_settings, factory=factory)
    with pytest.raises(StorageError) as info:
        clients.get("fast")
    assert "hunter2" not in info.value.message
    assert "fast.invalid" not in info.value.message
    assert "ValueError" in info.value.message
    assert info.value.__cause__ is None


def test_ping_maps_driver_errors_to_storage_error_with_name_only() -> None:
    class Broken:
        class admin:  # noqa: N801 - mimics the `admin` attribute of a client
            @staticmethod
            def command(_name: str) -> None:
                raise ServerSelectionTimeoutError("mongodb://u:hunter2@fast.invalid unreachable")

    clients = MongoClients(_settings, factory=lambda _u, _t: Broken())  # type: ignore[arg-type,return-value]
    with pytest.raises(StorageError) as info:
        clients.ping("fast")
    assert "hunter2" not in info.value.message
    assert "'fast'" in info.value.message


@pytest.mark.parametrize(
    ("exc", "fragment"),
    [
        (ServerSelectionTimeoutError("mongodb://u:hunter2@h"), "unreachable"),
        (ExecutionTimeout("operation exceeded time limit"), "time limit"),
        (OperationFailure("not authorized on db hunter2", code=13), "not authorised"),
        (OperationFailure("boom hunter2", code=2), "OperationFailure"),
        (ConfigurationError("hunter2"), "ConfigurationError"),
        (OverflowError("hunter2"), "OverflowError"),
        (TypeError("hunter2"), "TypeError"),
    ],
)
def test_mongo_errors_maps_driver_failures(exc: Exception, fragment: str) -> None:
    with pytest.raises(SourceError) as info, mongo_errors("conn"):
        raise exc
    assert fragment in info.value.message
    assert "hunter2" not in info.value.message
    assert "'conn'" in info.value.message


def test_mongo_errors_lets_domain_errors_through_and_honours_error_type() -> None:
    with pytest.raises(SourceNotFoundError), mongo_errors("conn"):
        raise SourceNotFoundError("x")
    with pytest.raises(StorageError), mongo_errors("conn", StorageError):
        raise TypeError("x")


def _use_slot(clients: MongoClients, connection: str) -> None:
    with clients.slot(connection):
        pass


def test_slot_bounds_concurrency_and_reports_busy() -> None:
    settings = _settings(timeout_ms=500)  # 0.5 s wait for a slot
    clients = MongoClients(lambda: settings)
    with ExitStack() as stack:
        for _ in range(mongo_module.MAX_CONCURRENT_PER_CONNECTION):
            stack.enter_context(clients.slot("fast"))
        with pytest.raises(BusyError):
            _use_slot(clients, "fast")
        _use_slot(clients, "slow")  # other connections are unaffected
    _use_slot(clients, "fast")  # released slots are reusable


def test_default_factory_options(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(uri: str, **kwargs: Any) -> str:
        seen.update(kwargs, uri=uri)
        return "client"

    monkeypatch.setattr(mongo_module, "MongoClient", fake)
    assert default_factory("mongodb://h/", 5_000) == "client"
    assert seen["serverSelectionTimeoutMS"] == 5_000
    assert seen["socketTimeoutMS"] >= 60_000
    assert seen["maxPoolSize"] <= 8
    assert seen["waitQueueTimeoutMS"] == 5_000
    assert seen["tz_aware"] is True


def test_real_client_construction_is_blocked_in_tests() -> None:
    """conftest's tripwire: nothing in the suite may open a real MongoClient."""
    with pytest.raises(AssertionError, match="mongomock"):
        default_factory("mongodb://127.0.0.1:27017/", 500)
