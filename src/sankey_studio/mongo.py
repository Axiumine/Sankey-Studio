# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Shared, cached ``MongoClient`` registry used by the Mongo source and the Mongo storage.

Clients are keyed by (connection name, URI) so editing a connection in the settings page
transparently yields a fresh client. Tests inject ``mongomock.MongoClient`` via ``factory``.

Rules every caller follows:

* A client is built OUTSIDE the registry lock (``mongodb+srv://`` resolves DNS inside the
  constructor and can block for ``mongo_timeout_ms``); losers of a construction race are closed.
* Driver failures are mapped with ``mongo_errors``: only the connection NAME and the exception
  class name reach messages and logs, never ``str(exc)`` (it may echo the URI or documents).
* Mongo-bound requests run inside ``slot(connection)``: at most ``MAX_CONCURRENT_PER_CONNECTION``
  at a time, so slow previews cannot pin every worker thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from bson.errors import BSONError
from pymongo import MongoClient, ReadPreference
from pymongo.errors import (
    AutoReconnect,
    ExecutionTimeout,
    NotPrimaryError,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
    WriteConcernError,
)

from sankey_studio.errors import (
    BusyError,
    SankeyError,
    SourceError,
    SourceNotFoundError,
    StorageError,
)

if TYPE_CHECKING:
    from pymongo.database import Database

    from sankey_studio.models import AppSettings

#: ``factory(uri, timeout_ms) -> client``
ClientFactory = Callable[[str, int], "MongoClient[Any]"]

#: Everything a driver call can raise that is not already a ``SankeyError``. ``ValueError``,
#: ``TypeError`` and ``OverflowError`` cover bad URIs and unrepresentable filter values.
DRIVER_ERRORS = (PyMongoError, BSONError, ValueError, TypeError, OverflowError)
MAX_CONCURRENT_PER_CONNECTION = 4
SOCKET_TIMEOUT_FLOOR_MS = 60_000
AUTH_FAILED_CODES = frozenset({13, 18})  # Unauthorized, AuthenticationFailed


def default_factory(uri: str, timeout_ms: int) -> MongoClient[Any]:
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=timeout_ms,
        connectTimeoutMS=timeout_ms,
        # A connection that stalls after connect must not pin a worker thread forever.
        socketTimeoutMS=max(timeout_ms, SOCKET_TIMEOUT_FLOOR_MS),
        maxPoolSize=8,
        waitQueueTimeoutMS=timeout_ms,
        maxIdleTimeMS=60_000,
        tz_aware=True,
        appname="sankey-studio",
    )


def primary_database(client: MongoClient[Any], name: str) -> Database[Any]:
    """``name`` read from the primary, whatever ``readPreference`` the saved URI carries.

    The library stores read what they have just written (a save then a load, a delete then an
    import): a secondary may not have replicated it yet. On a standalone node this is a no-op.
    """
    return client.get_database(name, read_preference=ReadPreference.PRIMARY)


@contextmanager
def mongo_errors(connection: str, error: type[SankeyError] = SourceError) -> Iterator[None]:
    """Map driver exceptions to ``error`` (default ``SourceError``) without leaking details.

    Replica-set failover has its own words, so a person sees "try again shortly" and not a bare
    class name: ``NotPrimaryError`` (a primary stepped down under the request), ``AutoReconnect``
    (a connection was cut; ``NetworkTimeout`` is one: a write in flight may have been applied) and
    ``WriteConcernError`` (``WTimeoutError`` is one: the write may be applied even though it was
    not confirmed). Order matters: ``NotPrimaryError`` and ``ServerSelectionTimeoutError`` are
    ``AutoReconnect`` subclasses and ``WriteConcernError`` is an ``OperationFailure``, so each
    subclass is handled before its parent.
    """
    try:
        yield
    except SankeyError:
        raise
    except ServerSelectionTimeoutError:
        raise error(f"MongoDB connection '{connection}' is unreachable") from None
    except ExecutionTimeout:
        raise error(f"MongoDB query on '{connection}' exceeded the time limit") from None
    except NotPrimaryError:
        raise error(
            f"MongoDB connection '{connection}' has no primary right now; try again shortly"
        ) from None
    except AutoReconnect as exc:
        raise error(
            f"MongoDB connection '{connection}' was interrupted ({type(exc).__name__}); "
            "try again shortly. A write in flight may have been applied"
        ) from None
    except WriteConcernError:
        raise error(
            f"MongoDB write on '{connection}' was not confirmed by enough members; "
            "it may have been applied"
        ) from None
    except OperationFailure as exc:
        if exc.code in AUTH_FAILED_CODES:
            raise error(f"MongoDB connection '{connection}' is not authorised") from None
        raise error(f"MongoDB query on '{connection}' failed: OperationFailure") from None
    except DRIVER_ERRORS as exc:
        raise error(f"MongoDB operation on '{connection}' failed: {type(exc).__name__}") from None


class MongoClients:
    """Thread-safe client cache. ``settings`` is read on every ``get`` so edits apply live."""

    def __init__(
        self,
        settings: Callable[[], AppSettings],
        factory: ClientFactory = default_factory,
    ) -> None:
        self._settings = settings
        self._factory = factory
        self._lock = threading.Lock()
        self._clients: dict[tuple[str, str], MongoClient[Any]] = {}
        self._slots: dict[str, threading.BoundedSemaphore] = {}

    def get(self, connection: str) -> MongoClient[Any]:
        settings = self._settings()
        conn = settings.connection(connection)
        if conn is None:
            raise SourceNotFoundError(f"Unknown MongoDB connection '{connection}'")
        uri = conn.uri.get_secret_value()
        key = (connection, uri)
        with self._lock:
            cached = self._clients.get(key)
        if cached is not None:
            return cached
        try:
            fresh = self._factory(uri, settings.mongo_timeout_ms)  # slow for +srv: no lock held
        except DRIVER_ERRORS as exc:
            raise StorageError(
                f"MongoDB connection '{connection}' could not be created: {type(exc).__name__}"
            ) from None
        stale: list[MongoClient[Any]]  # assigned in both branches below
        with self._lock:
            winner = self._clients.get(key)
            if winner is None:
                # Drop stale clients for the same connection name (URI was edited).
                stale = [
                    self._clients.pop(k) for k in [k for k in self._clients if k[0] == connection]
                ]
                self._clients[key] = winner = fresh
            else:
                stale = [fresh]  # lost the race: use the winner, close ours
        for client in stale:
            client.close()
        return winner

    def default_database(self, connection: str) -> str | None:
        conn = self._settings().connection(connection)
        return conn.default_database if conn else None

    def ping(self, connection: str) -> float:
        """Round-trip ``ping`` in milliseconds; raises ``StorageError`` (name only) on failure.

        ``primaryPreferred``: while a replica set elects a new primary, a secondary still answers,
        so "Test connection" does not report a cluster that serves reads as unreachable.
        """
        start = time.perf_counter()
        with mongo_errors(connection, StorageError):
            self.get(connection).admin.command(
                "ping", read_preference=ReadPreference.PRIMARY_PREFERRED
            )
        return (time.perf_counter() - start) * 1000

    @contextmanager
    def slot(self, connection: str) -> Iterator[None]:
        """Hold one of ``MAX_CONCURRENT_PER_CONNECTION`` slots; ``BusyError`` after the timeout."""
        with self._lock:
            sem = self._slots.setdefault(
                connection, threading.BoundedSemaphore(MAX_CONCURRENT_PER_CONNECTION)
            )
        wait_s = self._settings().mongo_timeout_ms / 1000
        if not sem.acquire(timeout=wait_s):
            raise BusyError(f"MongoDB connection '{connection}' is busy; try again shortly")
        try:
            yield
        finally:
            sem.release()

    def invalidate(self, connection: str | None = None) -> None:
        with self._lock:
            dropped = [
                self._clients.pop(k)
                for k in [k for k in self._clients if connection in (None, k[0])]
            ]
        for client in dropped:
            client.close()

    def close(self) -> None:
        self.invalidate(None)
