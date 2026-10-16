# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Fakes for the MongoDB source tests (no tests here; the file name keeps it in MONGO's paths).

``FakeMongo`` plays client, database and collection at once, records every call with its exact
arguments, and can raise a driver error from a call or from the middle of the iteration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, cast

from sankey_studio.mongo import MongoClients
from sankey_studio.sources.base import SourceContext

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from pymongo import MongoClient
    from pymongo.collection import Collection

    from sankey_studio.models import AppSettings


class Call(NamedTuple):
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class FakeCursor:
    """Iterates ``docs``; raises ``error`` after the last one when given; records ``close``."""

    def __init__(self, docs: Iterable[Any], error: BaseException | None = None) -> None:
        self._docs = docs
        self._error = error
        self.closed = False
        self.served = 0

    def __iter__(self) -> Iterator[Any]:
        for doc in self._docs:
            self.served += 1
            yield doc
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        self.closed = True


class FakeMongo:
    """Client, database and collection in one object.

    ``call_error`` is raised by the driver call itself (``find``, ``aggregate``, the listings);
    ``iter_error`` is raised by the cursor after its last document.
    """

    def __init__(
        self,
        docs: Iterable[Any] = (),
        *,
        call_error: BaseException | None = None,
        iter_error: BaseException | None = None,
        names: Iterable[str] = (),
    ) -> None:
        self.docs = list(docs)
        self.call_error = call_error
        self.iter_error = iter_error
        self.names = list(names)
        self.calls: list[Call] = []
        self.path: list[str] = []
        self.cursors: list[FakeCursor] = []

    def __getitem__(self, name: str) -> FakeMongo:
        self.path.append(name)
        return self

    def _call(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.calls.append(Call(method, args, kwargs))
        if self.call_error is not None:
            raise self.call_error

    def _cursor(self) -> FakeCursor:
        cursor = FakeCursor(self.docs, self.iter_error)
        self.cursors.append(cursor)
        return cursor

    def find(self, *args: Any, **kwargs: Any) -> FakeCursor:
        self._call("find", args, kwargs)
        return self._cursor()

    def aggregate(self, *args: Any, **kwargs: Any) -> FakeCursor:
        self._call("aggregate", args, kwargs)
        return self._cursor()

    def list_databases(self, **kwargs: Any) -> FakeCursor:
        """The driver's ``MongoClient.list_databases``: a cursor over ``{"name": ...}`` entries."""
        self._call("list_databases", (), kwargs)
        entries = [{"name": name, "sizeOnDisk": 0} for name in self.names]
        cursor = FakeCursor(entries, self.iter_error)
        self.cursors.append(cursor)
        return cursor

    def list_collection_names(self, **kwargs: Any) -> list[str]:
        self._call("list_collection_names", (), kwargs)
        return list(self.names)


def as_collection(fake: FakeMongo) -> Collection[Any]:
    """``fake`` where the code under test wants a driver collection."""
    return cast("Collection[Any]", fake)


def fake_ctx(
    fake: FakeMongo, settings: AppSettings, sources_dir: Path, *, strict: bool = False
) -> SourceContext:
    """A context whose Mongo clients always hand out ``fake``."""
    client = cast("MongoClient[Any]", fake)
    clients = MongoClients(lambda: settings, factory=lambda _uri, _ms: client)
    return SourceContext(settings=settings, sources_dir=sources_dir, mongo=clients, strict=strict)
