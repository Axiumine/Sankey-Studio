"""``edits.target``: the consent key is built by the server from resolved values (rule 29)."""

from __future__ import annotations

import pytest

from sankey_studio.edits.target import (
    FINGERPRINT_CHARS,
    display_target,
    effective_write_back,
    resolved_database,
    write_target,
)
from sankey_studio.models import AppSettings, WriteBackPref
from tests.conftest import build_connection
from tests.test_edits_support import file_source, inline, manual, mongo_source

SECRET_URI = "mongodb://tester:hunter2@mongo.invalid:27017/?appName=tests"
SETTINGS = AppSettings(mongo_connections=[build_connection("test", SECRET_URI, "flows")])


def key(**fields: object) -> str:
    result = write_target(mongo_source(**fields), SETTINGS)
    assert result is not None
    return result


def test_a_file_key_is_the_path() -> None:
    assert write_target(file_source("budget/2025.csv"), SETTINGS) == "file:budget/2025.csv"


def test_pasted_text_and_manual_links_have_no_key() -> None:
    assert write_target(inline(), SETTINGS) is None
    assert write_target(manual(), SETTINGS) is None


def test_a_mongo_key_names_connection_database_collection_and_a_fingerprint() -> None:
    result = key()
    head, _, tail = result.partition("#")
    assert head == "mongo:test/flows/events"
    assert len(tail) == FINGERPRINT_CHARS
    assert set(tail) <= set("0123456789abcdef")


@pytest.mark.parametrize("secret", ["hunter2", "tester", "mongo.invalid", SECRET_URI])
def test_the_key_never_holds_the_uri_or_a_secret(secret: str) -> None:
    assert secret not in key()


def test_an_unset_database_resolves_to_the_default_of_the_connection() -> None:
    assert key(database=None).startswith("mongo:test/flows/events#")
    other = AppSettings(mongo_connections=[build_connection("test", SECRET_URI, "other")])
    changed = write_target(mongo_source(database=None), other)
    assert changed is not None
    assert changed.startswith("mongo:test/other/events#")
    assert changed != key(database=None)


def test_the_key_changes_with_the_masked_uri_and_the_default_database() -> None:
    same = AppSettings(mongo_connections=[build_connection("test", SECRET_URI, "flows")])
    moved = AppSettings(mongo_connections=[build_connection("test", SECRET_URI + "x", "flows")])
    host = AppSettings(
        mongo_connections=[build_connection("test", "mongodb://t:p@other.invalid/", "flows")]
    )
    default = AppSettings(mongo_connections=[build_connection("test", SECRET_URI, None)])
    spec = mongo_source()
    assert write_target(spec, same) == write_target(spec, SETTINGS)
    assert write_target(spec, host) != write_target(spec, SETTINGS)
    assert write_target(spec, moved) != write_target(spec, host)
    assert write_target(spec, default) != write_target(spec, SETTINGS)


def test_a_password_change_leaves_the_key_alone() -> None:
    """The fingerprint is of the MASKED uri: the secret part never matters."""
    rotated = "mongodb://tester:other-pass@mongo.invalid:27017/?appName=tests"
    settings = AppSettings(mongo_connections=[build_connection("test", rotated, "flows")])
    assert write_target(mongo_source(), settings) == key()


def test_a_missing_connection_still_has_a_stable_key() -> None:
    empty = AppSettings()
    first = write_target(mongo_source(database="x"), empty)
    assert first is not None
    assert first.startswith("mongo:test/x/events#")
    assert first == write_target(mongo_source(database="x"), empty)
    assert first != key(database="x")


@pytest.mark.parametrize(
    ("database", "settings", "expected"),
    [
        ("own", SETTINGS, "own"),
        (None, SETTINGS, "flows"),
        (None, AppSettings(), ""),
        (None, AppSettings(mongo_connections=[build_connection("test", SECRET_URI, None)]), ""),
    ],
)
def test_the_resolved_database(database: str | None, settings: AppSettings, expected: str) -> None:
    assert resolved_database(mongo_source(database=database), settings) == expected


def test_the_effective_preference_needs_the_target_to_match() -> None:
    plain = file_source("a.csv")
    assert effective_write_back(plain, SETTINGS) == "ask"
    pref = WriteBackPref(mode="source", target="file:a.csv")
    granted = file_source("a.csv", write_back=pref)
    assert effective_write_back(granted, SETTINGS) == "source"
    other = file_source("b.csv", write_back=pref)
    assert effective_write_back(other, SETTINGS) == "ask"
    graph = file_source("a.csv", write_back=WriteBackPref(mode="graph", target="file:a.csv"))
    assert effective_write_back(graph, SETTINGS) == "graph"


def test_a_mongo_consent_is_lost_when_the_connection_changes() -> None:
    pref = WriteBackPref(mode="source", target=key())
    spec = mongo_source(write_back=pref)
    assert effective_write_back(spec, SETTINGS) == "source"
    moved = AppSettings(mongo_connections=[build_connection("test", SECRET_URI, "other")])
    assert effective_write_back(mongo_source(database=None, write_back=pref), moved) == "ask"
    assert (
        effective_write_back(mongo_source(collection="other", write_back=pref), SETTINGS) == "ask"
    )


def test_pasted_text_and_manual_links_always_ask() -> None:
    pref = WriteBackPref(mode="source", target="file:a.csv")
    assert effective_write_back(inline(write_back=pref), SETTINGS) == "ask"
    assert effective_write_back(manual(), SETTINGS) == "ask"


def test_the_display_target() -> None:
    assert display_target(file_source("budget/2025.csv"), SETTINGS) == "budget/2025.csv"
    assert display_target(mongo_source(), SETTINGS) == "test / flows.events"
    assert display_target(mongo_source(database=None), AppSettings()) == "test / events"
    assert display_target(inline(), SETTINGS) is None
    assert display_target(manual(), SETTINGS) is None
