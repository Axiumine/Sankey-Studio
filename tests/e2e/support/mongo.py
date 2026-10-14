"""``E2EMongoClient``: the mongomock client behind every e2e server (``LiveServer.mongo``).

mongomock is a faithful stand-in for ``find``, ``aggregate`` and the ping of the connection test,
but two calls the inspect routes make do not exist or have another signature there:

* ``client.list_databases(nameOnly=True, maxTimeMS=...)`` (``GET /mongo/<name>/databases``),
* ``database.list_collection_names(maxTimeMS=...)`` (``GET /mongo/<name>/collections``).

``E2EMongoClient`` adds both, so the Mongo tab of the editor (connection -> database -> collection
-> sample -> suggested fields) works end to end against it. It also has an outage switch:
``server.mongo.unreachable = True`` makes every operation raise ``ServerSelectionTimeoutError``
at once (the app answers "MongoDB connection 'x' is unreachable"), without waiting for
``mongo_timeout_ms``; set it back to ``False`` and the data is there again.

``E2EMongoClient(read_only=True)`` (or ``client.read_only = True``) is a database user without write
rights: every write call raises ``OperationFailure`` with code 13 ("not authorized"), reads work.
The write-back answers ``permission_denied`` and keeps the edit in the graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, override

import mongomock
from mongomock.database import Database as MongomockDatabase
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from pymongo.client_session import ClientSession
    from pymongo.command_cursor import CommandCursor
    from pymongo.database import Database

OUTAGE = "e2e: the MongoDB server is switched off (E2EMongoClient.unreachable)"
DENIED = "e2e: not authorized on this database (E2EMongoClient.read_only)"
#: The ``OperationFailure`` code of "Unauthorized".
NOT_AUTHORIZED = 13
WRITE_METHODS = (
    "insert_one",
    "insert_many",
    "update_one",
    "update_many",
    "replace_one",
    "delete_one",
    "delete_many",
    "bulk_write",
    "find_one_and_update",
    "find_one_and_replace",
    "find_one_and_delete",
)


def _denied(*_args: Any, **_options: Any) -> Any:
    raise OperationFailure(DENIED, code=NOT_AUTHORIZED)


class NameCursor:
    """What ``list_databases(nameOnly=True)`` returns: ``{"name": ...}`` entries, closable."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    def __iter__(self) -> Iterator[dict[str, str]]:
        return iter({"name": name} for name in self._names)

    def close(self) -> None:
        """Nothing to release; the real driver's cursor needs it."""


class E2EDatabase(MongomockDatabase):
    """A mongomock database whose ``list_collection_names`` accepts the driver's options.

    When its client is ``read_only`` the collections it hands out refuse every write.
    """

    @override
    def get_collection(self, name: str, *args: Any, **kwargs: Any) -> Any:
        collection = cast("Any", super()).get_collection(name, *args, **kwargs)
        if cast("Any", self._client).read_only:
            for method in WRITE_METHODS:
                setattr(collection, method, _denied)
        return collection

    @override
    def list_collection_names(
        self,
        filter: Mapping[str, Any] | None = None,
        session: ClientSession | None = None,
        **kwargs: Any,
    ) -> list[str]:
        base = cast("Any", super())
        return cast("list[str]", base.list_collection_names(filter=filter, session=session))


class E2EMongoClient(mongomock.MongoClient):  # type: ignore[type-arg]
    """``mongomock.MongoClient`` plus the two calls above and two switches (see the module doc)."""

    unreachable: bool = False
    read_only: bool = False

    @override
    def get_database(self, name: str | None = None, *args: Any, **kwargs: Any) -> Database[Any]:
        if self.unreachable:
            raise ServerSelectionTimeoutError(OUTAGE)
        database = super().get_database(name, *args, **kwargs)
        cast("Any", database).__class__ = E2EDatabase
        return database

    def list_databases(self, *_args: Any, **_options: Any) -> CommandCursor[dict[str, Any]]:
        if self.unreachable:
            raise ServerSelectionTimeoutError(OUTAGE)
        names = sorted(self.list_database_names())
        return cast("CommandCursor[dict[str, Any]]", NameCursor(names))
