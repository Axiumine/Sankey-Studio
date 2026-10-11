"""Fake MongoDB pieces for the Mongo store tests (a broken driver, a recording slot)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import mongomock
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from sankey_studio.mongo import MongoClients

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pytest
    from pymongo import MongoClient

    from sankey_studio.models import AppSettings


class _Broken:
    """Every attribute is a callable that raises ``error``; indexing gives another broken object."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "admin":
            return self
        if name == "close":  # a dead server's client can still be closed
            return self._close
        return self._fail

    @staticmethod
    def _close() -> None:
        return None

    def __getitem__(self, _name: str) -> _Broken:
        return self

    def _fail(self, *_args: object, **_kwargs: object) -> None:
        raise self._error


def broken_clients(settings: AppSettings, error: Exception) -> MongoClients:
    """``MongoClients`` whose server raises ``error`` on every single call."""

    def factory(_uri: str, _timeout: int) -> MongoClient[Any]:
        return cast("MongoClient[Any]", _Broken(error))

    return MongoClients(lambda: settings, factory=factory)


class SlotLog:
    """Records the connection names passed to ``clients.slot`` and when each slot is open."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.open = 0
        self.max_open = 0

    def install(
        self, patch: pytest.MonkeyPatch, clients: MongoClients, fail_with: Exception | None = None
    ) -> None:
        @contextmanager
        def slot(name: str) -> Iterator[None]:
            self.names.append(name)
            if fail_with is not None:
                raise fail_with
            self.open += 1
            self.max_open = max(self.max_open, self.open)
            try:
                yield
            finally:
                self.open -= 1

        patch.setattr(clients, "slot", slot)


class Recorder:
    """Records ``(method, args, kwargs)`` of calls made to mongomock collection methods."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def wrap(self, name: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def recorded(coll: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return original(coll, *args, **kwargs)

        return recorded

    def named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(a, k) for n, a, k in self.calls if n == name]


class TrackingClient:
    """A view of the hub's shared in-memory server that remembers whether it was closed."""

    def __init__(self, server: MongoClient[Any], uri: str) -> None:
        self._server = server
        self.uri = uri
        self.closed = False

    @property
    def admin(self) -> Any:
        return self._server.admin

    def __getitem__(self, name: str) -> Any:
        return self._server[name]

    def close(self) -> None:
        self.closed = True  # the shared server stays up for the other clients


class Hub:
    """A client factory in front of ONE in-memory server.

    Every client it builds sees the same data (like clients of one real server) and is recorded;
    URIs containing a ``dead`` marker get a server that never answers, ``refused`` ones fail to
    build at all.
    """

    def __init__(self) -> None:
        self.server: MongoClient[Any] = mongomock.MongoClient(tz_aware=True)
        self.clients: list[TrackingClient] = []
        self.dead: set[str] = set()
        self.refused: set[str] = set()

    def __call__(self, uri: str, _timeout_ms: int) -> MongoClient[Any]:
        if any(marker in uri for marker in self.refused):
            raise PyMongoError("refused")
        if any(marker in uri for marker in self.dead):
            return cast("MongoClient[Any]", _Broken(ServerSelectionTimeoutError(uri)))
        client = TrackingClient(self.server, uri)
        self.clients.append(client)
        return cast("MongoClient[Any]", client)

    def closed(self) -> list[str]:
        return [c.uri for c in self.clients if c.closed]

    def open(self) -> list[str]:
        return [c.uri for c in self.clients if not c.closed]
