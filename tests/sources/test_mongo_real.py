# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The MongoDB source against a REAL server (what mongomock cannot do).

Skipped unless ``SANKEY_TEST_MONGO_URI`` is set. The test creates a uniquely named database,
fills it, and drops it again; point the variable at a throw-away server (``make mongo-up``
serves 127.0.0.1:27117), never at one that holds data.
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

import pytest
from bson import Binary, Decimal128
from pydantic import SecretStr

from sankey_studio.models import AppSettings, MongoConnection, MongoSource
from sankey_studio.mongo import MongoClients
from sankey_studio.sources import open_source
from sankey_studio.sources.base import Diagnostics, SourceContext
from sankey_studio.sources.mongo_inspect import (
    CollectionRef,
    list_collections,
    list_databases,
    sample_documents,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

URI_ENV = "SANKEY_TEST_MONGO_URI"

pytestmark = [
    pytest.mark.mongo,
    pytest.mark.skipif(not os.environ.get(URI_ENV), reason=f"needs {URI_ENV}"),
]


class Server:
    """A throw-away database on the real server plus a source context for it."""

    def __init__(self, ctx: SourceContext, database: str) -> None:
        self.ctx = ctx
        self.database = database

    def spec(self, **fields: Any) -> MongoSource:
        return MongoSource.model_validate({"connection": "real", "collection": "events", **fields})

    def rows(self, spec: MongoSource) -> list[tuple[str, str, float, str | None]]:
        return list(open_source(spec, self.ctx).iter_links(Diagnostics()))


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    database = f"sankey_test_{uuid.uuid4().hex[:12]}"
    connection = MongoConnection(
        name="real", uri=SecretStr(os.environ[URI_ENV]), default_database=database
    )
    settings = AppSettings(mongo_connections=[connection])
    clients = MongoClients(lambda: settings)
    ctx = SourceContext(settings=settings, sources_dir=tmp_path, mongo=clients)
    db = clients.get("real")[database]
    db["events"].insert_many(
        [
            {"source": "a", "target": "b", "value": 2, "category": "Food"},
            {"source": "a", "target": "b", "value": Decimal128("3.5")},
            {"source": "b", "target": "c", "value": "4"},
        ]
    )
    db["extra"].insert_one({"source": "a", "target": "b", "value": 10})
    try:
        yield Server(ctx, database)
    finally:
        clients.get("real").drop_database(database)
        clients.close()


def test_find_reads_numbers_decimals_and_numeric_text(server: Server) -> None:
    spec = server.spec(category_field="category")
    rows = sorted(server.rows(spec), key=lambda row: (row[0], row[1], row[2]))
    assert rows == [
        ("a", "b", 2.0, "Food"),
        ("a", "b", 3.5, None),
        ("b", "c", 4.0, None),
    ]


def test_aggregate_with_union_and_group_runs_on_the_server(server: Server) -> None:
    pipeline: list[dict[str, Any]] = [
        {"$unionWith": "extra"},
        {
            "$group": {
                "_id": {"s": "$source", "t": "$target"},
                "value": {"$sum": {"$toDouble": "$value"}},
            }
        },
        {"$project": {"_id": 0, "source": "$_id.s", "target": "$_id.t", "value": 1}},
        {"$sort": {"source": 1, "target": 1}},
    ]
    rows = server.rows(server.spec(mode="aggregate", pipeline=pipeline))
    assert rows == [("a", "b", 15.5, None), ("b", "c", 4.0, None)]


def test_aggregate_with_sort_by_count_runs_on_the_server(server: Server) -> None:
    pipeline: list[dict[str, Any]] = [
        {"$sortByCount": "$source"},
        {
            "$project": {
                "_id": 0,
                "source": "$_id",
                "target": {"$literal": "total"},
                "value": "$count",
            }
        },
        {"$sort": {"source": 1}},
    ]
    rows = server.rows(server.spec(mode="aggregate", pipeline=pipeline))
    assert rows == [("a", "total", 2.0, None), ("b", "total", 1.0, None)]


def test_the_limit_is_applied_by_the_server(server: Server) -> None:
    diag = Diagnostics()
    rows = list(open_source(server.spec(limit=2), server.ctx).iter_links(diag))
    assert len(rows) == 2
    assert diag.warnings == ["Result truncated at limit 2"]


@pytest.mark.parametrize("mode", ["find", "aggregate"])
def test_exactly_limit_documents_are_not_truncated(server: Server, mode: str) -> None:
    """The server is asked for one document more than the limit: the three documents here
    are a complete result at limit 3 and a cut one at limit 2."""
    pipeline = [{"$sort": {"source": 1}}] if mode == "aggregate" else []
    text_note = "Read 1 text value(s) as numbers"  # the seeded "4" is in the complete result only
    for limit, expected in ((3, [text_note]), (2, ["Result truncated at limit 2"])):
        diag = Diagnostics()
        spec = server.spec(mode=mode, pipeline=pipeline, limit=limit)
        assert len(list(open_source(spec, server.ctx).iter_links(diag))) == limit
        assert diag.warnings == expected


def test_inspect_lists_and_samples_the_throw_away_database(server: Server) -> None:
    assert server.database in list_databases(server.ctx, "real")
    assert {"admin", "local", "config"}.isdisjoint(list_databases(server.ctx, "real"))
    assert list_collections(server.ctx, "real", server.database) == ["events", "extra"]
    sample = sample_documents(server.ctx, CollectionRef("real", server.database, "events"), 2)
    assert [doc["source"] for doc in sample] == ["a", "a"]
    assert all(isinstance(doc["_id"], str) for doc in sample)


def test_a_uuid_comes_back_as_binary_and_is_still_a_name_a_category_and_a_sample_text(
    server: Server,
) -> None:
    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    document = {
        "source": Binary.from_uuid(first),
        "target": Binary.from_uuid(second),
        "value": 1,
        "kind": Binary.from_uuid(first),
    }
    server.ctx.mongo.get("real")[server.database]["ids"].insert_one(document)
    rows = server.rows(server.spec(collection="ids", category_field="kind"))
    assert rows == [(str(first), str(second), 1.0, str(first))]
    sample = sample_documents(server.ctx, CollectionRef("real", server.database, "ids"), 1)
    assert [doc["source"] for doc in sample] == [str(first)]
