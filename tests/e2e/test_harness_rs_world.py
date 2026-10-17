# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``support.rs_world`` and ``MongoWorld.drop``: the throwaway database of a shared replica set.

The URI names the database; it must be empty when a test starts and only its collections go at
teardown. Everything runs on mongomock: ``real_world`` (which dials) is replaced by a world on an
in-memory client built from the same made-up URI.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from pymongo.errors import InvalidURI, OperationFailure

from sankey_studio.mongo import default_factory
from tests.e2e.support import http_b_world as world_module
from tests.e2e.support import rs_world as rs_world_module
from tests.e2e.support.http_b_world import MongoWorld, real_world
from tests.e2e.support.mongo import E2EMongoClient
from tests.e2e.support.rs_world import real_rs_world, secondary_reads_uri

URI = "mongodb://u:p@h1:27017,h2:27017/{}?replicaSet=rs0"
NO_DATABASE = "mongodb://u:p@h1:27017,h2:27017/?replicaSet=rs0"


def make_world(uri: str, database: str = "ignored", *, keep: bool = False) -> MongoWorld:
    return MongoWorld(
        uri=uri,
        database=database,
        client=E2EMongoClient(uri, tz_aware=True),
        factory=default_factory,
        secrets=(),
        timeout_ms=1,
        keep_database=keep,
    )


def closes(world: MongoWorld, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace ``world.client.close`` with a recorder; the list gets one entry per call."""
    calls: list[str] = []
    monkeypatch.setattr(world.client, "close", lambda: calls.append("close"))
    return calls


def serve(world: MongoWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_uri: str, env: str = "") -> MongoWorld:
        assert env == "SANKEY_TEST_MONGO_RS_URI"
        return world

    monkeypatch.setattr(rs_world_module, "real_world", fake)
    monkeypatch.setattr(rs_world_module, "member_count", lambda _client: 1)  # mongomock has no set


def test_the_database_is_the_one_in_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    world = make_world(URI.format("lab"))
    serve(world, monkeypatch)
    got = real_rs_world(world.uri)
    assert (got.database, got.keep_database, got.client is world.client) == ("lab", True, True)


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        (NO_DATABASE, "needs a throwaway database in its path"),
        (URI.format("admin"), "names the system database 'admin'"),
        (URI.format("local"), "names the system database 'local'"),
        (URI.format("config"), "names the system database 'config'"),
        (URI.format("lab"), "database 'lab' holds 2 collection(s); use an empty throwaway"),
    ],
)
def test_a_missing_system_or_used_database_is_refused(
    uri: str, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = make_world(uri)
    for collection in ("a", "b"):
        world.client["lab"][collection].insert_one({"keep": "me"})
    serve(world, monkeypatch)
    calls = closes(world, monkeypatch)
    with pytest.raises(pytest.fail.Exception, match=re.escape(message)):
        real_rs_world(uri)
    assert calls == ["close"]  # no client is left open
    assert world.client["lab"]["a"].count_documents({}) == 1  # and nothing was touched


def test_a_database_that_cannot_be_listed_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    world = make_world(URI.format("lab"))
    serve(world, monkeypatch)
    calls = closes(world, monkeypatch)

    def denied(*_args: Any, **_kwargs: Any) -> list[str]:
        raise OperationFailure("not authorized")

    monkeypatch.setattr(type(world.client["lab"]), "list_collection_names", denied)
    with pytest.raises(
        pytest.fail.Exception, match=r"cannot list the collections: OperationFailure"
    ):
        real_rs_world(world.uri)
    assert calls == ["close"]


def test_drop_removes_the_collections_of_a_kept_database_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = make_world(URI.format("lab"), "lab", keep=True)
    for database, collection in (("lab", "a"), ("lab", "b"), ("other", "c")):
        world.client[database][collection].insert_one({"keep": "me"})
    calls = closes(world, monkeypatch)
    world.drop()
    assert world.client["lab"].list_collection_names() == []
    assert world.client["other"].list_collection_names() == ["c"]
    assert calls == ["close"]


@pytest.mark.parametrize(
    ("database", "keep"),
    [("lab", False), ("admin", True), ("local", True), ("config", False)],
)
def test_drop_refuses_what_is_not_a_throwaway_database(
    database: str, keep: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = make_world(URI.format(database), database, keep=keep)
    world.client[database]["a"].insert_one({"keep": "me"})
    calls = closes(world, monkeypatch)
    with pytest.raises(AssertionError, match="refusing to drop"):
        world.drop()
    assert world.client[database]["a"].count_documents({}) == 1
    assert calls == ["close"]


def test_drop_still_drops_an_e2e_database(monkeypatch: pytest.MonkeyPatch) -> None:
    world = make_world(URI.format("sankey_e2e_0123abcd"), "sankey_e2e_0123abcd")
    world.client["sankey_e2e_0123abcd"]["a"].insert_one({})
    calls = closes(world, monkeypatch)
    world.drop()
    assert world.client["sankey_e2e_0123abcd"].list_collection_names() == []
    assert calls == ["close"]


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (
            "mongodb://h1,h2/db?replicaSet=rs0",
            "mongodb://h1,h2/db?replicaSet=rs0&readPreference=secondaryPreferred",
        ),
        ("mongodb://h1,h2/db", "mongodb://h1,h2/db?readPreference=secondaryPreferred"),
    ],
)
def test_the_secondary_read_option_is_appended_to_the_query(uri: str, expected: str) -> None:
    assert secondary_reads_uri(uri) == expected


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (
            "mongodb://h1/db?readPreference=secondary",
            "mongodb://h1/db?readPreference=secondaryPreferred",
        ),
        (
            "mongodb://h1/db?replicaSet=rs0&READPREFERENCE=nearest&w=majority",
            "mongodb://h1/db?replicaSet=rs0&w=majority&readPreference=secondaryPreferred",
        ),
        (
            "mongodb://h1/db?readPreferenceTags=dc:east&readPreference=secondary",
            "mongodb://h1/db?readPreferenceTags=dc:east&readPreference=secondaryPreferred",
        ),
        ("mongodb://h1/db?", "mongodb://h1/db?readPreference=secondaryPreferred"),
        ("mongodb://h1/db?&&", "mongodb://h1/db?readPreference=secondaryPreferred"),
    ],
)
def test_an_existing_read_preference_is_replaced_not_duplicated(uri: str, expected: str) -> None:
    """A duplicate option is a driver warning, an error under ``filterwarnings = error``."""
    assert secondary_reads_uri(uri) == expected


def test_a_failing_assert_never_prints_the_password_of_the_world() -> None:
    password = "s3cr3t-pass-word"
    uri = f"mongodb://user:{password}@h1:27017,h2:27017/lab?replicaSet=rs0"
    world = make_world(uri, "lab")
    object.__setattr__(world, "secrets", (password, f"user:{password}@"))
    text = repr(world)
    assert "MongoWorld(" in text  # still a useful repr...
    assert "database='lab'" in text
    assert password not in text
    assert "user:" not in text


def test_an_unparsable_uri_fails_with_its_type_and_never_its_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise InvalidURI('Bad database name "tail-of-the-password@h1,h2/lab"')

    monkeypatch.setattr(world_module, "MongoClient", refuse)
    with pytest.raises(pytest.fail.Exception) as info:
        real_world("mongodb://u:pa/ss@h1,h2/lab", env="SANKEY_TEST_MONGO_RS_URI")
    assert str(info.value) == "SANKEY_TEST_MONGO_RS_URI is not a usable MongoDB URI: InvalidURI"
