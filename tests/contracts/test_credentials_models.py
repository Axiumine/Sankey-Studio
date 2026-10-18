# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests: the shape of ``credentials.json`` and the one rule for a connection string."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from sankey_studio.models import MongoConnection
from sankey_studio.models.credentials import MAX_SECRETS, ConnectionSecret, StoredCredentials
from sankey_studio.models.settings import checked_uri

URI = "mongodb://tester:hunter2@mongo.invalid:27017/?appName=tests"


def _stored(**fields: Any) -> StoredCredentials:
    return StoredCredentials.model_validate(fields)


def test_the_defaults_are_version_one_and_no_connections() -> None:
    stored = StoredCredentials()
    assert (stored.version, stored.mongo_connections) == (1, {})
    assert MAX_SECRETS == 20


def test_a_connection_secret_holds_a_secret_string_and_nothing_else() -> None:
    assert list(ConnectionSecret.model_fields) == ["uri"]
    item = ConnectionSecret(uri=SecretStr(URI))
    assert item.uri.get_secret_value() == URI
    for text in (repr(item), str(item), item.model_dump_json(), str(item.model_dump())):
        assert "hunter2" not in text
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ConnectionSecret.model_validate({"uri": URI, "token": "x"})


@pytest.mark.parametrize("name", ["a", "A-b_c.1", "x" * 64, "0"])
def test_a_valid_connection_name_is_a_key(name: str) -> None:
    stored = _stored(mongo_connections={name: {"uri": URI}})
    assert list(stored.mongo_connections) == [name]


@pytest.mark.parametrize("name", ["", "x" * 65, "bad name", "a/b", "a:b", "é"])
def test_an_invalid_connection_name_is_refused_without_echoing_it(name: str) -> None:
    with pytest.raises(ValidationError) as info:
        _stored(mongo_connections={name: {"uri": URI}})
    assert "connection name: 1-64 chars" in str(info.value)
    assert "hunter2" not in str(info.value)


@pytest.mark.parametrize(("count", "ok"), [(19, True), (20, True), (21, False)])
def test_at_most_twenty_entries(count: int, ok: bool) -> None:
    entries = {f"c{i}": {"uri": URI} for i in range(count)}
    if ok:
        assert len(_stored(mongo_connections=entries).mongo_connections) == count
        return
    with pytest.raises(ValidationError, match="at most 20 items"):
        _stored(mongo_connections=entries)


@pytest.mark.parametrize("version", [0, 2, "1", "one", None, 1.5])
def test_only_version_one_is_understood(version: object) -> None:
    with pytest.raises(ValidationError):
        _stored(version=version)


def test_a_name_is_stripped_like_every_other_text_of_the_models() -> None:
    stored = _stored(mongo_connections={" a ": {"uri": URI}})
    assert list(stored.mongo_connections) == ["a"]


def test_the_file_form_round_trips() -> None:
    doc = {"version": 1, "mongo_connections": {"a": {"uri": URI}}}
    stored = StoredCredentials.model_validate_json(json.dumps(doc))
    assert stored.mongo_connections["a"].uri.get_secret_value() == URI


# --------------------------------------------------------------------------- one rule for a URI

REFUSED = [
    "",
    "   ",
    "**********",
    "mongodb://u:***@h/",
    "http://u:pw@h/",
    "mongodb://u:pw@h/?tlsCAFile=/etc/ca",
]


@pytest.mark.parametrize("uri", [URI, "  " + URI + "\n", "mongodb+srv://u:pw@cluster.example.com/"])
def test_a_usable_string_is_accepted_stripped_and_alike_everywhere(uri: str) -> None:
    expected = uri.strip()
    assert checked_uri(SecretStr(uri)).get_secret_value() == expected
    assert ConnectionSecret(uri=SecretStr(uri)).uri.get_secret_value() == expected
    assert MongoConnection(name="a", uri=SecretStr(uri)).uri.get_secret_value() == expected


@pytest.mark.parametrize("uri", REFUSED)
def test_an_unusable_string_is_refused_alike_everywhere(uri: str) -> None:
    builds = (
        lambda: checked_uri(SecretStr(uri)),
        lambda: ConnectionSecret(uri=SecretStr(uri)),
        lambda: MongoConnection(name="a", uri=SecretStr(uri)),
    )
    for build in builds:
        with pytest.raises(ValueError, match="uri") as info:
            build()
        assert "hunter2" not in str(info.value)


def test_the_two_refusals_have_their_own_exact_wording() -> None:
    with pytest.raises(ValueError, match="uri is a masked placeholder; enter the real connection"):
        checked_uri(SecretStr("**********"))
    with pytest.raises(ValueError, match="uri option 'tlsCAFile' is not allowed") as info:
        checked_uri(SecretStr(URI + "&tlsCAFile=/etc/hunter2"))
    assert "hunter2" not in str(info.value)
    assert "/etc/" not in str(info.value)
