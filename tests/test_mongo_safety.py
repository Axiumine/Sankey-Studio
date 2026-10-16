# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``mongo_safety`` hardening added after contract v2 (bypass tables: the contract tests).

* Database and collection names refuse control (Cc), format/bidi (Cf) and surrogate (Cs)
  characters: the inspect endpoints pass raw query parameters straight through.
* The tree walk follows every ``Mapping``, not only ``dict``: the driver encodes any mapping as a
  document, so a ``MappingProxyType`` could otherwise carry ``$where`` past the check.
"""

from __future__ import annotations

import unicodedata
from collections import OrderedDict, UserDict
from types import MappingProxyType
from typing import Any, NamedTuple

import pytest
from bson.son import SON

from sankey_studio.mongo_safety import (
    COLLECTION_NAME_MAX,
    DB_NAME_MAX,
    MAX_DEPTH,
    check_filter,
    check_pipeline,
    validate_collection_name,
    validate_db_name,
    validate_namespace,
)
from tests.safety_support import ACCEPTED, message_of, outcome_of

DB_INVALID = "invalid MongoDB database name"
COLL_INVALID = "invalid MongoDB collection name"
WHERE = "MongoDB operator $where is not allowed (read-only)"
OUT = "MongoDB operator $out is not allowed (read-only)"


class Char(NamedTuple):
    code: int
    category: str

    @property
    def char(self) -> str:
        return chr(self.code)


UNSAFE = {
    "NUL": Char(0x00, "Cc"),
    "start of heading": Char(0x01, "Cc"),
    "tab": Char(0x09, "Cc"),
    "line feed": Char(0x0A, "Cc"),
    "carriage return": Char(0x0D, "Cc"),
    "unit separator": Char(0x1F, "Cc"),
    "DEL": Char(0x7F, "Cc"),
    "first C1 control": Char(0x80, "Cc"),
    "next line": Char(0x85, "Cc"),
    "last C1 control": Char(0x9F, "Cc"),
    "soft hyphen": Char(0xAD, "Cf"),
    "Arabic number sign": Char(0x0600, "Cf"),
    "zero width space": Char(0x200B, "Cf"),
    "zero width joiner": Char(0x200D, "Cf"),
    "left-to-right mark": Char(0x200E, "Cf"),
    "right-to-left override": Char(0x202E, "Cf"),
    "left-to-right isolate": Char(0x2066, "Cf"),
    "byte order mark": Char(0xFEFF, "Cf"),
    "first surrogate": Char(0xD800, "Cs"),
    "last surrogate": Char(0xDFFF, "Cs"),
}

#: Code points that stay legal in names: letters, symbols, other separators, private use.
SAFE = {
    "latin letter": Char(0xE9, "Ll"),
    "CJK": Char(0x65E5, "Lo"),
    "emoji": Char(0x1F600, "So"),
    "hyphen": Char(0x2D, "Pd"),
    "first printable ASCII": Char(0x21, "Po"),
    "no-break space": Char(0xA0, "Zs"),
    "line separator": Char(0x2028, "Zl"),
    "private use": Char(0xE000, "Co"),
}


@pytest.mark.parametrize("case", UNSAFE.values(), ids=UNSAFE)
def test_unsafe_characters_are_refused_in_database_names(case: Char) -> None:
    for name in (f"a{case.char}b", f"{case.char}ab", f"ab{case.char}", case.char):
        assert message_of(validate_db_name, name) == DB_INVALID


@pytest.mark.parametrize("case", UNSAFE.values(), ids=UNSAFE)
def test_unsafe_characters_are_refused_in_collection_names(case: Char) -> None:
    for name in (f"a{case.char}b", f"{case.char}ab", f"ab{case.char}", case.char):
        assert message_of(validate_collection_name, name) == COLL_INVALID


@pytest.mark.parametrize("case", SAFE.values(), ids=SAFE)
def test_other_unicode_is_still_accepted_in_names(case: Char) -> None:
    name = f"a{case.char}b"
    assert validate_collection_name(name) == name
    if case.category not in {"Zs", "Zl"}:  # a database name may not hold separators
        assert validate_db_name(name) == name


def test_the_category_tables_match_the_unicode_database() -> None:
    for case in (*UNSAFE.values(), *SAFE.values()):
        assert unicodedata.category(case.char) == case.category


def test_the_length_limit_and_the_character_rule_are_independent() -> None:
    assert validate_db_name("a" * DB_NAME_MAX) == "a" * DB_NAME_MAX
    assert message_of(validate_db_name, "a" * (DB_NAME_MAX - 1) + "\n") == DB_INVALID
    assert message_of(validate_db_name, "a" * (DB_NAME_MAX + 1)) == DB_INVALID
    long = "a" * COLLECTION_NAME_MAX
    assert validate_collection_name(long) == long
    assert (
        message_of(validate_collection_name, "a" * (COLLECTION_NAME_MAX - 1) + "\n") == COLL_INVALID
    )
    assert message_of(validate_collection_name, long + "a") == COLL_INVALID


def test_a_namespace_with_an_unsafe_part_is_refused() -> None:
    assert message_of(validate_namespace, "fl\nows", "events") == DB_INVALID

    validate_namespace("flows", "events")


def test_the_system_name_messages_are_unchanged() -> None:
    assert message_of(validate_db_name, "admin").startswith("MongoDB system databases")
    assert message_of(validate_collection_name, "system.users") == (
        "MongoDB system collections are not allowed"
    )


# --------------------------------------------------------------------------- mapping walk


def wrap_proxy(body: dict[str, Any]) -> Any:
    return MappingProxyType(body)


def wrap_user_dict(body: dict[str, Any]) -> Any:
    return UserDict(body)


def wrap_ordered(body: dict[str, Any]) -> Any:
    return OrderedDict(body)


def wrap_son(body: dict[str, Any]) -> Any:
    return SON(body)


WRAPPERS = {
    "MappingProxyType": wrap_proxy,
    "UserDict": wrap_user_dict,
    "OrderedDict": wrap_ordered,
    "SON": wrap_son,
}


class Shape(NamedTuple):
    name: str
    build: Any  # (wrap) -> filter


SHAPES = {
    "the filter itself": lambda wrap: wrap({"$where": "1"}),
    "a nested value": lambda wrap: {"a": wrap({"$where": "1"})},
    "inside a list": lambda wrap: {"$or": [{"a": 1}, wrap({"$where": "1"})]},
    "inside a tuple": lambda wrap: {"$or": ({"a": 1}, wrap({"$where": "1"}))},
    "below an expression": lambda wrap: {"$expr": wrap({"$eq": [wrap({"$where": "1"}), 1]})},
}


@pytest.mark.parametrize("wrapper", WRAPPERS.values(), ids=WRAPPERS)
@pytest.mark.parametrize("shape", SHAPES.values(), ids=SHAPES)
def test_server_side_code_is_found_inside_any_mapping_in_a_filter(shape: Any, wrapper: Any) -> None:
    assert message_of(check_filter, shape(wrapper)) == WHERE


@pytest.mark.parametrize("wrapper", WRAPPERS.values(), ids=WRAPPERS)
def test_server_side_code_is_found_inside_any_mapping_in_a_pipeline_stage(wrapper: Any) -> None:
    assert message_of(check_pipeline, [{"$match": wrapper({"$where": "1"})}]) == WHERE
    assert message_of(check_pipeline, [{"$project": {"x": wrapper({"$function": {}})}}]) == (
        "MongoDB operator $function is not allowed (read-only)"
    )
    assert message_of(check_pipeline, [{"$addFields": {"x": [wrapper({"$accumulator": 1})]}}]) == (
        "MongoDB operator $accumulator is not allowed (read-only)"
    )


@pytest.mark.parametrize("wrapper", WRAPPERS.values(), ids=WRAPPERS)
def test_a_mapping_stage_is_refused_whole(wrapper: Any) -> None:
    """A stage that is not a plain ``dict`` never reaches the stage allow-list."""
    expected = "pipeline stage 0 must be an object with one key"
    assert message_of(check_pipeline, [wrapper({"$out": "stolen"})]) in {expected, OUT}


@pytest.mark.parametrize("wrapper", WRAPPERS.values(), ids=WRAPPERS)
def test_harmless_mappings_are_accepted(wrapper: Any) -> None:
    check_filter(wrapper({"a": {"$gt": 1}, "b": wrapper({"$in": [1, 2]})}))
    assert outcome_of(check_filter, wrapper({})) == ACCEPTED


@pytest.mark.parametrize("wrapper", WRAPPERS.values(), ids=WRAPPERS)
def test_the_other_walk_rules_apply_to_mappings_too(wrapper: Any) -> None:
    assert message_of(check_filter, wrapper({"a\0b": 1})) == (
        "filter/pipeline keys must not contain NUL"
    )
    assert message_of(check_filter, {"a": wrapper({"b": 2**63})}) == (
        "filter/pipeline integers must fit in 64 bits"
    )
    assert message_of(check_filter, {"a": wrapper({"b": "$$USER_ROLES"})}) == (
        "MongoDB variable reference is not allowed"
    )


def test_a_mapping_with_a_non_text_key_is_refused() -> None:
    message = "filter/pipeline keys must be strings"
    assert message_of(check_filter, MappingProxyType({1: "a"})) == message
    assert message_of(check_filter, {"a": MappingProxyType({b"k": "a"})}) == message


def test_the_depth_cap_counts_mapping_levels() -> None:
    def nest(levels: int) -> Any:
        node: Any = 1
        for _ in range(levels):
            node = MappingProxyType({"a": node})
        return node

    check_filter(nest(MAX_DEPTH))
    assert message_of(check_filter, nest(MAX_DEPTH + 1)) == "filter/pipeline is nested too deeply"
