# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""A secondary lags the primary: what the replica-set suite writes waits for every member.

The secondary-read flows seed a collection and the application reads it at once from a secondary.
Without a wait the read can come first and see nothing. ``MongoWorld.insert`` (the test side) and
the ``w=<n>`` of the application's URI (``secondary_reads_uri``) make the write return only when
all ``n`` data-bearing members have it. Mongomock stands in for the server.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import mongomock
import pytest

from sankey_studio.mongo import default_factory
from tests.e2e.support import http_b_world as world_module
from tests.e2e.support import rs_world as rs_world_module
from tests.e2e.support.http_b_world import REPLICATION_WAIT_S, MongoWorld
from tests.e2e.support.mongo import E2EMongoClient
from tests.e2e.support.rs_world import member_count, real_rs_world, secondary_reads_uri

if TYPE_CHECKING:
    from collections.abc import Iterator

URI = "mongodb://u:p@h1:27017,h2:27017/lab?replicaSet=rs0"


def make_world(*, members: int = 0) -> MongoWorld:
    return MongoWorld(
        uri=URI,
        database="lab",
        client=E2EMongoClient(URI, tz_aware=True),
        factory=default_factory,
        secrets=(),
        timeout_ms=1,
        members=members,
    )


class Spy:
    """The write concern ``insert_many`` ran with, and the time limits that were set."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.concerns: list[dict[str, Any]] = []
        self.limits: list[float] = []
        original: Any = mongomock.collection.Collection.insert_many

        def insert_many(collection: Any, documents: Any, *args: Any, **kwargs: Any) -> Any:
            self.concerns.append(dict(collection.write_concern.document))
            return original(collection, documents, *args, **kwargs)

        @contextmanager
        def timeout(seconds: float) -> Iterator[None]:
            self.limits.append(seconds)
            yield

        monkeypatch.setattr(mongomock.collection.Collection, "insert_many", insert_many)
        monkeypatch.setattr(world_module, "timeout", timeout)


@pytest.mark.parametrize(("secondaries", "expected"), [(0, 1), (1, 2), (2, 3)])
def test_the_members_are_the_primary_and_its_secondaries(secondaries: int, expected: int) -> None:
    client = SimpleNamespace(secondaries={(f"h{n}", 27017) for n in range(secondaries)})
    assert member_count(cast("Any", client)) == expected


def test_a_world_with_members_waits_for_all_of_them_within_a_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Spy(monkeypatch)
    world = make_world(members=3)
    world.insert("events", [{"from": "A", "to": "B"}, {"from": "B", "to": "C"}])
    assert spy.concerns == [{"w": 3}]
    assert spy.limits == [REPLICATION_WAIT_S]
    assert world.client["lab"]["events"].count_documents({}) == 2


def test_a_world_without_members_inserts_with_the_default_write_concern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Spy(monkeypatch)
    world = make_world()
    world.insert("events", [{"from": "A", "to": "B"}])
    assert spy.concerns == [{}]
    assert spy.limits == []
    assert world.client["lab"]["events"].count_documents({}) == 1


def test_the_world_of_a_replica_set_knows_its_members(monkeypatch: pytest.MonkeyPatch) -> None:
    world = make_world()
    monkeypatch.setattr(rs_world_module, "real_world", lambda *_args, **_kwargs: world)
    monkeypatch.setattr(rs_world_module, "member_count", lambda _client: 3)
    assert real_rs_world(URI).members == 3


@pytest.mark.parametrize(
    ("uri", "members", "expected"),
    [
        (
            "mongodb://h1,h2/db?replicaSet=rs0",
            3,
            "mongodb://h1,h2/db?replicaSet=rs0&readPreference=secondaryPreferred&w=3",
        ),
        (
            "mongodb://h1/db?w=majority&replicaSet=rs0",
            3,
            "mongodb://h1/db?replicaSet=rs0&readPreference=secondaryPreferred&w=3",
        ),
        (
            "mongodb://h1/db?W=1&wtimeoutMS=500&readPreference=secondary",
            2,
            "mongodb://h1/db?wtimeoutMS=500&readPreference=secondaryPreferred&w=2",
        ),
        ("mongodb://h1/db", 1, "mongodb://h1/db?readPreference=secondaryPreferred&w=1"),
    ],
)
def test_the_uri_of_the_application_asks_every_member_to_acknowledge(
    uri: str, members: int, expected: str
) -> None:
    assert secondary_reads_uri(uri, acknowledged_by=members) == expected


def test_without_a_member_count_the_write_concern_of_the_uri_stays() -> None:
    uri = "mongodb://h1/db?w=majority"
    assert (
        secondary_reads_uri(uri) == "mongodb://h1/db?w=majority&readPreference=secondaryPreferred"
    )
