# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``storage.base``: exact messages, version boundaries and codec edge cases."""

from __future__ import annotations

import json
from typing import Any

import pytest

from sankey_studio.errors import NotFoundError, StorageError
from sankey_studio.models import SCHEMA_VERSION
from sankey_studio.storage.base import (
    check_graph_id,
    decode_mongo_doc,
    encode_mongo_doc,
    upgrade_doc,
)

VALID_ID = "0123456789abcdef" * 2


@pytest.mark.parametrize("bad", ["", "x", "../x", VALID_ID.upper(), VALID_ID + "0", VALID_ID[:-1]])
def test_a_malformed_id_is_not_found_with_a_fixed_message(bad: str) -> None:
    with pytest.raises(NotFoundError) as info:
        check_graph_id(bad)
    assert info.value.message == "Graph not found"
    assert info.value.status_code == 404


def test_a_valid_id_is_returned_unchanged() -> None:
    assert check_graph_id(VALID_ID) == VALID_ID
    assert check_graph_id("0" * 32) == "0" * 32


def test_upgrade_accepts_every_supported_version() -> None:
    assert SCHEMA_VERSION == 1
    for version in range(1, SCHEMA_VERSION + 1):
        assert upgrade_doc({"schema_version": version})["schema_version"] == version
    assert upgrade_doc({})["schema_version"] == 1


@pytest.mark.parametrize("version", [0, -1, None, "1", 1.0, [1]])
def test_upgrade_refuses_unusable_versions_with_a_fixed_message(version: object) -> None:
    with pytest.raises(StorageError) as info:
        upgrade_doc({"schema_version": version})
    assert info.value.message == "Stored graph has an invalid schema version"


def test_upgrade_refuses_a_newer_version_with_a_fixed_message() -> None:
    with pytest.raises(StorageError) as info:
        upgrade_doc({"schema_version": SCHEMA_VERSION + 1})
    assert info.value.message == "Stored graph was written by a newer version of sankey-studio"


def test_upgrade_keeps_everything_but_the_mongo_id() -> None:
    doc = {"_id": 5, "name": "n", "tags": ["a"]}
    assert upgrade_doc(doc) == {"name": "n", "tags": ["a"], "schema_version": 1}
    assert doc == {"_id": 5, "name": "n", "tags": ["a"]}


def test_mongo_filter_and_pipeline_are_stored_as_compact_json_text() -> None:
    source = {
        "type": "mongo",
        "filter": {"a": {"$gt": 1}, "b": [1, 2]},
        "pipeline": [{"$match": {}}],
    }
    stored = encode_mongo_doc({"source": source})["source"]
    assert stored["filter"] == '{"a":{"$gt":1},"b":[1,2]}'
    assert stored["pipeline"] == '[{"$match":{}}]'
    assert json.loads(stored["filter"]) == source["filter"]
    assert source["filter"] == {"a": {"$gt": 1}, "b": [1, 2]}  # the input is untouched


def test_a_mongo_source_without_filter_or_pipeline_is_encoded_as_is() -> None:
    only_filter = {"type": "mongo", "connection": "c", "filter": {"a": 1}}
    assert encode_mongo_doc({"source": only_filter})["source"] == {
        "type": "mongo",
        "connection": "c",
        "filter": '{"a":1}',
    }
    only_pipeline = {"type": "mongo", "pipeline": []}
    assert encode_mongo_doc({"source": only_pipeline})["source"] == {
        "type": "mongo",
        "pipeline": "[]",
    }
    assert encode_mongo_doc({"source": {"type": "mongo"}})["source"] == {"type": "mongo"}


def test_only_the_named_sections_are_rewritten() -> None:
    dump = {
        "source": {"type": "manual", "filter": {"a": 1}},
        "transform": {"merge_nodes": {"a": "b"}, "hide_nodes": ["x"]},
        "style": {"node_colors": {"a": "#112233"}, "category_colors": {}, "title": "t"},
    }
    stored = encode_mongo_doc(dump)
    assert stored["source"] == {"type": "manual", "filter": {"a": 1}}
    assert stored["transform"] == {"merge_nodes": [["a", "b"]], "hide_nodes": ["x"]}
    assert stored["style"] == {
        "node_colors": [["a", "#112233"]],
        "category_colors": [],
        "title": "t",
    }
    assert decode_mongo_doc(stored) == dump


def test_sections_that_are_not_objects_are_left_alone() -> None:
    odd = {"source": None, "transform": "x", "style": 5}
    assert encode_mongo_doc(odd) == odd
    assert decode_mongo_doc(odd) == odd


def test_decode_ignores_fields_that_are_already_plain() -> None:
    plain = {
        "source": {"type": "mongo", "filter": {"a": 1}, "pipeline": [{"$match": {}}]},
        "style": {"node_colors": {"a": "#112233"}},
    }
    assert decode_mongo_doc(plain) == plain


@pytest.mark.parametrize(
    "stored",
    [
        {"style": {"node_colors": [["a", "b", "c"]]}},
        {"style": {"node_colors": [5]}},
        {"source": {"type": "mongo", "filter": "{nope"}},
        {"source": {"type": "mongo", "pipeline": "[" * 100_000}},
    ],
)
def test_malformed_encoded_fields_have_a_fixed_message(stored: dict[str, Any]) -> None:
    with pytest.raises(StorageError) as info:
        decode_mongo_doc(stored)
    assert info.value.message == "Stored graph has an unreadable encoded field"
    assert info.value.status_code == 503
