"""``mongo``: driver options, cache hits, invalidation, ``ping`` and default databases."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from pymongo import ReadPreference

import sankey_studio.mongo as mongo_module
from sankey_studio.errors import SourceNotFoundError
from sankey_studio.models import AppSettings, MongoConnection
from sankey_studio.mongo import MongoClients, default_factory


class FakeClient:
    """Records ``close()``, the ``admin.command`` calls and their keyword options."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.closed = 0
        self.commands: list[tuple[Any, ...]] = []
        self.command_options: list[dict[str, Any]] = []
        self.admin = SimpleNamespace(command=self._command)

    def _command(self, *args: Any, **options: Any) -> None:
        self.commands.append(args)
        self.command_options.append(options)

    def close(self) -> None:
        self.closed += 1


def settings_with(*names: str, timeout_ms: int = 1_500) -> AppSettings:
    connections = [
        MongoConnection(
            name=name, uri=SecretStr(f"mongodb://{name}.invalid/"), default_database=f"{name}_db"
        )
        for name in names
    ]
    return AppSettings(mongo_connections=connections, mongo_timeout_ms=timeout_ms)


class Registry:
    """A ``MongoClients`` over fake clients that remembers every factory call."""

    def __init__(self, *names: str, timeout_ms: int = 1_500) -> None:
        self.settings = settings_with(*names, timeout_ms=timeout_ms)
        self.calls: list[tuple[str, int]] = []
        self.made: list[FakeClient] = []
        self.clients = MongoClients(lambda: self.settings, factory=self._factory)

    def _factory(self, uri: str, timeout_ms: int) -> Any:
        self.calls.append((uri, timeout_ms))
        client = FakeClient(uri)
        self.made.append(client)
        return client


# --------------------------------------------------------------------------- driver options


class Recorder:
    def __init__(self) -> None:
        self.args: tuple[Any, ...] = ()
        self.kwargs: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        self.args, self.kwargs = args, kwargs
        return "client"


@pytest.mark.parametrize(
    ("timeout_ms", "socket_ms"),
    [(500, 60_000), (5_000, 60_000), (60_000, 60_000), (60_001, 60_001), (300_000, 300_000)],
)
def test_default_factory_passes_every_option(
    monkeypatch: pytest.MonkeyPatch, timeout_ms: int, socket_ms: int
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(mongo_module, "MongoClient", recorder)
    assert default_factory("mongodb://h/db", timeout_ms) == "client"
    assert recorder.args == ("mongodb://h/db",)
    assert recorder.kwargs == {
        "serverSelectionTimeoutMS": timeout_ms,
        "connectTimeoutMS": timeout_ms,
        "socketTimeoutMS": socket_ms,
        "maxPoolSize": 8,
        "waitQueueTimeoutMS": timeout_ms,
        "maxIdleTimeMS": 60_000,
        "tz_aware": True,
        "appname": "sankey-studio",
    }


def test_module_limits_are_pinned() -> None:
    assert mongo_module.MAX_CONCURRENT_PER_CONNECTION == 4
    assert mongo_module.SOCKET_TIMEOUT_FLOOR_MS == 60_000
    assert {13, 18} == mongo_module.AUTH_FAILED_CODES


# --------------------------------------------------------------------------- get / cache


def test_unknown_connection_message_names_it() -> None:
    registry = Registry("a")
    with pytest.raises(SourceNotFoundError) as info:
        registry.clients.get("nope")
    assert info.value.message == "Unknown MongoDB connection 'nope'"
    assert registry.calls == []


def test_a_second_get_is_a_cache_hit() -> None:
    registry = Registry("a", "b", timeout_ms=2_500)
    first = registry.clients.get("a")
    assert registry.clients.get("a") is first
    assert registry.clients.get("a") is first
    other = registry.clients.get("b")
    assert other is not first
    assert registry.clients.get("b") is other
    assert registry.calls == [("mongodb://a.invalid/", 2_500), ("mongodb://b.invalid/", 2_500)]
    assert [client.closed for client in registry.made] == [0, 0]


def test_the_factory_gets_the_current_timeout_and_uri() -> None:
    registry = Registry("a", timeout_ms=700)
    registry.clients.get("a")
    registry.settings = settings_with("a", timeout_ms=900)
    registry.clients.get("a")  # same URI: still cached, no new call
    assert registry.calls == [("mongodb://a.invalid/", 700)]


def test_default_database_follows_the_live_settings() -> None:
    registry = Registry("a", "b")
    assert registry.clients.default_database("a") == "a_db"
    assert registry.clients.default_database("b") == "b_db"
    assert registry.clients.default_database("nope") is None
    registry.settings = AppSettings(
        mongo_connections=[MongoConnection(name="a", uri=SecretStr("mongodb://a.invalid/"))]
    )
    assert registry.clients.default_database("a") is None
    assert registry.clients.default_database("b") is None


# --------------------------------------------------------------------------- invalidate / close


def test_invalidate_one_connection_closes_only_its_clients() -> None:
    registry = Registry("a", "b")
    a, b = registry.clients.get("a"), registry.clients.get("b")
    registry.clients.invalidate("a")
    assert [client.closed for client in registry.made] == [1, 0]
    assert registry.clients.get("b") is b
    assert registry.clients.get("a") is not a
    assert len(registry.made) == 3


def test_invalidate_matches_the_connection_name_not_the_uri() -> None:
    registry = Registry("a", "b")
    registry.clients.get("a")
    registry.clients.get("b")
    registry.clients.invalidate("mongodb://a.invalid/")
    assert [client.closed for client in registry.made] == [0, 0]
    registry.clients.invalidate("unknown")
    assert [client.closed for client in registry.made] == [0, 0]


def test_invalidate_without_a_name_and_close_drop_everything() -> None:
    registry = Registry("a", "b")
    registry.clients.get("a")
    registry.clients.get("b")
    registry.clients.invalidate()
    assert [client.closed for client in registry.made] == [1, 1]
    registry.clients.get("a")
    registry.clients.close()
    assert [client.closed for client in registry.made] == [1, 1, 1]
    registry.clients.close()  # nothing left: closing again is a no-op
    assert [client.closed for client in registry.made] == [1, 1, 1]
    registry.clients.invalidate("a")
    assert len(registry.made) == 3


# --------------------------------------------------------------------------- ping


class Clock:
    """A ``time`` stand-in whose ``perf_counter`` walks through the given readings."""

    def __init__(self, *readings: float) -> None:
        self._readings = iter(readings)

    def perf_counter(self) -> float:
        return next(self._readings)


def test_ping_returns_the_round_trip_in_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = Registry("a")
    monkeypatch.setattr(mongo_module, "time", Clock(10.0, 10.25))
    assert registry.clients.ping("a") == 250.0
    assert registry.made[0].commands == [("ping",)]


def test_ping_prefers_the_primary_but_a_secondary_may_answer() -> None:
    """During an election no primary exists; a cluster that serves reads is not 'unreachable'."""
    registry = Registry("a")
    registry.clients.ping("a")
    assert registry.made[0].command_options == [
        {"read_preference": ReadPreference.PRIMARY_PREFERRED}
    ]


def test_ping_pings_once_per_call_over_the_cached_client() -> None:
    registry = Registry("a")
    assert registry.clients.ping("a") >= 0
    assert registry.clients.ping("a") >= 0
    assert len(registry.made) == 1
    assert registry.made[0].commands == [("ping",), ("ping",)]
