"""``mongo_safety``: exact limits, counters, error messages and the option scanner.

The messages are part of the contract (the UI shows them), so they are compared whole. Every
boundary is probed on both sides: the last accepted value passes, the first refused one fails.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from sankey_studio import mongo_safety
from sankey_studio.mongo_safety import (
    COLLECTION_NAME_MAX,
    DB_NAME_MAX,
    INT64_MAX,
    INT64_MIN,
    MAX_DEPTH,
    MAX_JSON_BYTES,
    MAX_RANGE_SPAN,
    check_filter,
    check_pipeline,
    validate_collection_name,
    validate_db_name,
    validate_namespace,
)
from tests.safety_support import ACCEPTED, message_of, outcome_of

DB_INVALID = "invalid MongoDB database name"
COLL_INVALID = "invalid MongoDB collection name"
TOO_DEEP = "filter/pipeline is nested too deeply"


def nested(depth: int, leaf: object) -> object:
    for _ in range(depth):
        leaf = {"a": leaf}
    return leaf


# --------------------------------------------------------------------------- names


@pytest.mark.parametrize("char", sorted('/\\. "$*<>:|?\0'))
def test_db_name_forbidden_characters(char: str) -> None:
    assert message_of(validate_db_name, f"a{char}b") == DB_INVALID


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", DB_INVALID),
        ("a" * (DB_NAME_MAX + 1), DB_INVALID),
        ("admin", "MongoDB system databases (admin, local, config) are not allowed"),
        ("LOCAL", "MongoDB system databases (admin, local, config) are not allowed"),
        ("Config", "MongoDB system databases (admin, local, config) are not allowed"),
    ],
)
def test_db_name_refusals_have_stable_messages(name: str, message: str) -> None:
    assert message_of(validate_db_name, name) == message


@pytest.mark.parametrize("name", ["a", "a" * DB_NAME_MAX, "my-db_2", "adminx", "xconfig"])
def test_db_name_accepts_and_returns_the_name(name: str) -> None:
    assert validate_db_name(name) == name


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", COLL_INVALID),
        ("a" * (COLLECTION_NAME_MAX + 1), COLL_INVALID),
        ("a$b", COLL_INVALID),
        ("a\0b", COLL_INVALID),
        ("system.users", "MongoDB system collections are not allowed"),
        ("system.", "MongoDB system collections are not allowed"),
    ],
)
def test_collection_name_refusals_have_stable_messages(name: str, message: str) -> None:
    assert message_of(validate_collection_name, name) == message


@pytest.mark.parametrize(
    "name", ["a", "a" * COLLECTION_NAME_MAX, "systemx", "x.system.y", "my.coll-1", "System.x"]
)
def test_collection_name_accepts_and_returns_the_name(name: str) -> None:
    assert validate_collection_name(name) == name


def test_namespace_checks_the_database_first_then_the_collection() -> None:
    validate_namespace("flows", "events")
    assert message_of(validate_namespace, "", "events") == DB_INVALID
    assert message_of(validate_namespace, "flows", "") == COLL_INVALID


# --------------------------------------------------------------------------- scalar values


@pytest.mark.parametrize("value", [INT64_MAX, INT64_MIN, 0, True, False, 1.5e300, "text"])
def test_values_inside_the_int64_range_pass(value: object) -> None:
    check_filter({"a": value})
    check_pipeline([{"$match": {"a": value}}])


@pytest.mark.parametrize("value", [INT64_MAX + 1, INT64_MIN - 1, 10**30])
def test_integers_outside_int64_are_refused(value: int) -> None:
    expected = "filter/pipeline integers must fit in 64 bits"
    assert message_of(check_filter, {"a": value}) == expected
    assert message_of(check_filter, {"a": [value]}) == expected


@pytest.mark.parametrize(
    "variable",
    ["$$ROOT", "$$ROOT.a.b", "$$CURRENT.a", "$$this", "$$value.x", "$$aB", "$$a\u00e9", "$$a"],
)
def test_allowed_variables_pass(variable: str) -> None:
    check_filter({"$expr": {"$eq": ["$a", variable]}})


@pytest.mark.parametrize(
    "variable",
    ["$$USER_ROLES", "$$SEARCH_META", "$$Foo", "$$", "$$_x", "$$1", "$$\u00e9", "$$USER_ROLES.x"],
)
def test_privileged_or_odd_variables_are_refused(variable: str) -> None:
    message = message_of(check_filter, {"$expr": {"$eq": ["$a", variable]}})
    assert message == "MongoDB variable reference is not allowed"


@pytest.mark.parametrize("value", ["$field", "$", "plain", "$a$$b"])
def test_field_paths_and_text_are_not_variables(value: str) -> None:
    check_filter({"a": value})


# --------------------------------------------------------------------------- $range


@pytest.mark.parametrize(
    "args",
    [
        [0, MAX_RANGE_SPAN],
        [MAX_RANGE_SPAN, 0],
        [50_000, 100_000],
        [0, 2 * MAX_RANGE_SPAN, 2],
        [0, 2 * MAX_RANGE_SPAN, -2],
        [0.0, float(MAX_RANGE_SPAN)],
        [0, 0],
        [0, "$n"],
        ["$n", 10**9],
        [False, 10**9],
        [True, 10**9],
        [0],
        [],
        5,
        "$n",
        None,
        {"a": 1},
    ],
)
def test_range_that_is_small_or_not_literal_passes(args: object) -> None:
    check_filter({"$expr": {"$range": args}})


@pytest.mark.parametrize(
    "args",
    [
        [0, MAX_RANGE_SPAN + 1],
        [MAX_RANGE_SPAN + 1, 0],
        [-60_000, 60_000],
        [0, 2 * MAX_RANGE_SPAN + 2, 2],
        [0, 2 * MAX_RANGE_SPAN + 2, -2],
        [0, MAX_RANGE_SPAN + 1, 0],
        [0.0, 1e9],
        [0, 10**9, 1, 1_000],
    ],
)
def test_range_with_a_huge_literal_span_is_refused(args: list[Any]) -> None:
    expected = f"$range spans more than {MAX_RANGE_SPAN} elements"
    assert message_of(check_filter, {"$expr": {"$range": args}}) == expected
    assert message_of(check_pipeline, [{"$project": {"r": {"$range": args}}}]) == expected


# --------------------------------------------------------------------------- tree walk


def test_depth_limit_is_exact_for_dicts() -> None:
    check_filter(nested(MAX_DEPTH, 1))  # type: ignore[arg-type]
    assert message_of(check_filter, nested(MAX_DEPTH + 1, 1)) == TOO_DEEP
    check_pipeline([{"$match": nested(MAX_DEPTH - 2, 1)}])
    assert message_of(check_pipeline, [{"$match": nested(MAX_DEPTH - 1, 1)}]) == TOO_DEEP


def test_depth_limit_is_exact_for_lists() -> None:
    def lists(depth: int) -> dict[str, Any]:
        leaf: object = 1
        for _ in range(depth):
            leaf = [leaf]
        return {"a": leaf}

    check_filter(lists(MAX_DEPTH - 1))
    assert message_of(check_filter, lists(MAX_DEPTH)) == TOO_DEEP


def test_tuples_count_for_depth_like_lists() -> None:
    leaf: object = 1
    for _ in range(MAX_DEPTH):
        leaf = (leaf,)
    assert message_of(check_filter, {"a": leaf}) == TOO_DEEP


def test_keys_must_be_plain_strings_without_nul() -> None:
    assert message_of(check_filter, {1: "x"}) == "filter/pipeline keys must be strings"
    assert message_of(check_filter, {"a": {None: 1}}) == "filter/pipeline keys must be strings"
    assert message_of(check_filter, {"a\0b": 1}) == "filter/pipeline keys must not contain NUL"
    assert message_of(check_filter, {"a": [{"b\0": 1}]}) == (
        "filter/pipeline keys must not contain NUL"
    )


@pytest.mark.parametrize("operator", ["$where", "$function", "$accumulator", "$out", "$merge"])
def test_forbidden_operators_are_named_in_the_message(operator: str) -> None:
    expected = f"MongoDB operator {operator} is not allowed (read-only)"
    assert message_of(check_filter, {"a": [{operator: 1}]}) == expected
    assert message_of(check_filter, {operator: 1}) == expected


# --------------------------------------------------------------------------- JSON size


def padded(size: int) -> dict[str, str]:
    """A filter whose compact-ish ``json.dumps`` length is exactly ``size`` characters."""
    base = {"a": ""}
    filler = size - len(json.dumps(base))
    return {"a": "x" * filler}


def test_size_limit_is_exact_for_filters_and_pipelines() -> None:
    at_limit = padded(MAX_JSON_BYTES)
    assert len(json.dumps(at_limit)) == MAX_JSON_BYTES
    check_filter(at_limit)
    over = padded(MAX_JSON_BYTES + 1)
    assert message_of(check_filter, over) == "filter/pipeline is too large"
    check_pipeline([{"$match": padded(MAX_JSON_BYTES - len(json.dumps([{"$match": {}}])) + 2)}])
    assert message_of(check_pipeline, [{"$match": over}]) == "filter/pipeline is too large"


def test_size_limit_is_64_kib() -> None:
    assert MAX_JSON_BYTES == 64 * 1024


def test_check_size_maps_encoder_failures_to_plain_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert message_of(mongo_safety._check_size, {(1, 2): 3}) == "filter/pipeline must be plain JSON"
    assert message_of(mongo_safety._check_size, 10**5000) == "filter/pipeline must be plain JSON"

    def deep(*_args: object, **_kwargs: object) -> str:
        raise RecursionError

    monkeypatch.setattr("sankey_studio.mongo_safety.json", SimpleNamespace(dumps=deep))
    assert message_of(mongo_safety._check_size, {}) == TOO_DEEP


class _Wide:
    """An object json cannot encode: ``default=str`` turns it into ``width`` characters."""

    def __init__(self, width: int) -> None:
        self.width = width

    def __str__(self) -> str:
        return "x" * self.width


def test_check_size_stringifies_unknown_objects_instead_of_failing() -> None:
    assert outcome_of(mongo_safety._check_size, {"a": object(), "b": {1, 2}}) == ACCEPTED
    overhead = len(json.dumps({"a": ""}))
    # The str() of the object counts towards the limit: exact fit passes, one more is refused.
    exact = {"a": _Wide(MAX_JSON_BYTES - overhead)}
    assert outcome_of(mongo_safety._check_size, exact) == ACCEPTED
    too_wide = {"a": _Wide(MAX_JSON_BYTES - overhead + 1)}
    assert message_of(mongo_safety._check_size, too_wide) == "filter/pipeline is too large"
