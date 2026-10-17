# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``split_credentials`` / ``join_credentials``: the settings document in two halves and back."""

from __future__ import annotations

import copy
from typing import Any, NamedTuple

import pytest

from sankey_studio.storage.credentials import (
    CREDENTIALS_VERSION,
    Joined,
    join_credentials,
    split_credentials,
)

URIS = {"a": "mongodb://u:pw-a@h1.invalid/", "b": "mongodb://u:pw-b@h2.invalid/"}


def _dumped(*names: str) -> dict[str, Any]:
    """A ``dump_settings`` document: every connection carries its real ``uri``."""
    connections = [{"name": n, "uri": URIS[n], "default_database": None} for n in names]
    return {"theme": "dark", "mongo_connections": connections}


def _doc(connections: object) -> dict[str, Any]:
    return {"theme": "dark", "mongo_connections": connections}


# --------------------------------------------------------------------------- split


def test_the_version_is_one() -> None:
    assert CREDENTIALS_VERSION == 1


def test_split_moves_every_uri_into_the_secrets_document() -> None:
    public, secret = split_credentials(_dumped("a", "b"))
    assert public == _doc(
        [{"name": "a", "default_database": None}, {"name": "b", "default_database": None}]
    )
    assert secret == {
        "version": 1,
        "mongo_connections": {"a": {"uri": URIS["a"]}, "b": {"uri": URIS["b"]}},
    }
    assert list(secret["mongo_connections"]) == ["a", "b"]


def test_split_of_no_connections_still_makes_both_documents() -> None:
    public, secret = split_credentials(_dumped())
    assert public == _doc([])
    assert secret == {"version": 1, "mongo_connections": {}}


def test_split_does_not_change_its_argument() -> None:
    doc = _dumped("a", "b")
    before = copy.deepcopy(doc)
    split_credentials(doc)
    assert doc == before


def test_join_undoes_split() -> None:
    doc = _dumped("a", "b")
    public, secret = split_credentials(doc)
    uris = {name: item["uri"] for name, item in secret["mongo_connections"].items()}
    assert join_credentials(public, uris) == Joined(doc, [])


# --------------------------------------------------------------------------- join


class Join(NamedTuple):
    label: str
    connections: object
    secrets: dict[str, str]
    result: object
    missing: list[str]


JOINS = [
    Join("filled in by name", [{"name": "a"}], {"a": "U"}, [{"name": "a", "uri": "U"}], []),
    Join(
        "a uri in the file wins",
        [{"name": "a", "uri": "OLD"}],
        {"a": "NEW"},
        [{"name": "a", "uri": "OLD"}],
        [],
    ),
    Join(
        "a secret without a connection is ignored",
        [{"name": "a"}],
        {"a": "U", "z": "Z"},
        [{"name": "a", "uri": "U"}],
        [],
    ),
    Join(
        "one connection without a secret",
        [{"name": "a"}, {"name": "b"}],
        {"a": "U"},
        [{"name": "a", "uri": "U"}, {"name": "b"}],
        ["b"],
    ),
    Join(
        "all of them without a secret",
        [{"name": "a"}, {"name": "b"}],
        {},
        [{"name": "a"}, {"name": "b"}],
        ["a", "b"],
    ),
    Join("no connections", [], {"a": "U"}, [], []),
    Join(
        "an invalid name is left to the validator",
        [{"name": "bad name!"}],
        {},
        [{"name": "bad name!"}],
        [],
    ),
    Join(
        "a name that is not text",
        [{"name": 3}, {"name": ["a"]}],
        {"a": "U"},
        [{"name": 3}, {"name": ["a"]}],
        [],
    ),
    Join("a connection without a name", [{}], {"a": "U"}, [{}], []),
    Join("an item that is not an object", ["x", 3, None], {}, ["x", 3, None], []),
]


@pytest.mark.parametrize("case", JOINS, ids=[c.label for c in JOINS])
def test_join_puts_each_string_back_by_name(case: Join) -> None:
    doc = _doc(case.connections)
    before = copy.deepcopy(doc)
    assert join_credentials(doc, case.secrets) == Joined(_doc(case.result), case.missing)
    assert doc == before  # the argument is not changed


@pytest.mark.parametrize(
    "doc",
    [
        [],
        None,
        "text",
        3,
        {"theme": "dark"},
        {"mongo_connections": None},
        {"mongo_connections": "a"},
        {"mongo_connections": {"a": 1}},
    ],
    ids=["list", "null", "text", "number", "no key", "null key", "text key", "object key"],
)
def test_any_other_shape_comes_back_as_it_is(doc: object) -> None:
    joined = join_credentials(doc, {"a": "U"})
    assert joined.doc is doc
    assert joined.missing == []
