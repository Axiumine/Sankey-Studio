# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Read-only MongoDB introspection that powers the editor's Mongo form.

The web layer passes query parameters straight through, so every function validates its raw
arguments with ``mongo_safety`` BEFORE a client is touched, runs inside the per-connection slot and
``mongo_errors`` (messages carry the connection name and the exception class only), and returns
plain JSON-safe data. Timeouts: every server command carries ``maxTimeMS`` (the settings'
``mongo_timeout_ms``), on top of the client's server-selection, connect and socket timeouts
(``mongo.default_factory``).
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sankey_studio.errors import UnsafeSourceError
from sankey_studio.mongo import mongo_errors
from sankey_studio.mongo_safety import (
    validate_collection_name,
    validate_db_name,
    validate_namespace,
)
from sankey_studio.sources.mongo_sample import JsonSanitizer
from sankey_studio.sources.mongo_source import require_connection
from sankey_studio.sources.mongo_suggest import FieldSuggestion, suggest_fields

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.sources.base import SourceContext

__all__ = [
    "SAMPLE_DEFAULT",
    "SAMPLE_MAX",
    "SAMPLE_MIN",
    "CollectionRef",
    "FieldSuggestion",
    "clamp_sample_size",
    "list_collections",
    "list_databases",
    "sample_documents",
    "suggest_fields",
]

SAMPLE_MIN = 1
SAMPLE_MAX = 20
SAMPLE_DEFAULT = 5
#: One raw document in memory at a time: documents can be 16 MB and are converted as they arrive.
SAMPLE_BATCH_SIZE = 1


@dataclass(frozen=True, slots=True)
class CollectionRef:
    """A collection addressed by its connection name, database and name."""

    connection: str
    database: str
    collection: str


def _usable(check: Callable[[str], str], name: str) -> bool:
    try:
        check(name)
    except UnsafeSourceError:
        return False
    return True


def list_databases(ctx: SourceContext, connection: str) -> list[str]:
    """Readable databases of ``connection`` (``admin``/``local``/``config`` are never listed)."""
    require_connection(ctx, connection)
    with ctx.mongo.slot(connection), mongo_errors(connection):
        client = ctx.mongo.get(connection)
        # list_database_names() takes no options; list_databases() forwards maxTimeMS. nameOnly
        # (what list_database_names sends) spares the server sizing, and locking, every database.
        timeout = ctx.settings.mongo_timeout_ms
        with closing(client.list_databases(nameOnly=True, maxTimeMS=timeout)) as cursor:
            names = [entry["name"] for entry in cursor]
    return sorted(name for name in names if _usable(validate_db_name, name))


def list_collections(ctx: SourceContext, connection: str, database: str) -> list[str]:
    """Readable collections of ``database`` (``system.*`` are never listed)."""
    validate_db_name(database)
    require_connection(ctx, connection)
    with ctx.mongo.slot(connection), mongo_errors(connection):
        client = ctx.mongo.get(connection)
        names = client[database].list_collection_names(maxTimeMS=ctx.settings.mongo_timeout_ms)
    return sorted(name for name in names if _usable(validate_collection_name, name))


def clamp_sample_size(n: int) -> int:
    """``n`` limited to ``SAMPLE_MIN..SAMPLE_MAX``."""
    return max(SAMPLE_MIN, min(n, SAMPLE_MAX))


def sample_documents(
    ctx: SourceContext, target: CollectionRef, n: int = SAMPLE_DEFAULT
) -> list[dict[str, Any]]:
    """Up to ``n`` (1..20) documents of ``target`` as bounded, JSON-safe dicts."""
    validate_namespace(target.database, target.collection)
    require_connection(ctx, target.connection)
    options: dict[str, Any] = {
        "limit": clamp_sample_size(n),
        "max_time_ms": ctx.settings.mongo_timeout_ms,
        "batch_size": SAMPLE_BATCH_SIZE,
    }
    sanitizer = JsonSanitizer()
    with ctx.mongo.slot(target.connection), mongo_errors(target.connection):
        client = ctx.mongo.get(target.connection)
        with closing(client[target.database][target.collection].find({}, **options)) as cursor:
            return [sanitizer.document(doc) for doc in cursor]
