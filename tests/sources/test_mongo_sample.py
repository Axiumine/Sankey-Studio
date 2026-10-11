"""``JsonSanitizer``: documents become plain, bounded JSON whatever they hold."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections import OrderedDict
from decimal import Decimal
from types import MappingProxyType
from typing import Any, NamedTuple

import pytest
from bson import Binary, Code, DBRef, Decimal128, Int64, MinKey, ObjectId, Regex, Timestamp
from bson.son import SON

from sankey_studio.sources.mongo_sample import (
    ELLIPSIS,
    MAX_SAFE_INT,
    SAMPLE_MAX_DEPTH,
    SAMPLE_MAX_ITEMS,
    SAMPLE_MAX_NODES,
    SAMPLE_MAX_TEXT,
    JsonSanitizer,
)


def convert(value: object) -> object:
    return JsonSanitizer().document({"v": value})["v"]


class Case(NamedTuple):
    value: object
    expected: object


SCALARS = {
    "null": Case(None, None),
    "true": Case(True, True),
    "false": Case(False, False),
    "zero": Case(0, 0),
    "small int": Case(-17, -17),
    "float": Case(1.5, 1.5),
    "nan": Case(float("nan"), "nan"),
    "inf": Case(float("inf"), "inf"),
    "-inf": Case(float("-inf"), "-inf"),
    "text": Case("Food", "Food"),
    "empty text": Case("", ""),
    "int64 below the safe limit": Case(Int64(MAX_SAFE_INT), MAX_SAFE_INT),
    "the safe limit": Case(MAX_SAFE_INT, MAX_SAFE_INT),
    "just past the safe limit": Case(MAX_SAFE_INT + 1, str(MAX_SAFE_INT + 1)),
    "the negative safe limit": Case(-MAX_SAFE_INT, -MAX_SAFE_INT),
    "just past the negative safe limit": Case(-MAX_SAFE_INT - 1, str(-MAX_SAFE_INT - 1)),
    "int64 max": Case(2**63 - 1, str(2**63 - 1)),
    "int64 min": Case(-(2**63), str(-(2**63))),
    "largest 64-bit magnitude": Case(2**64 - 1, str(2**64 - 1)),
    "a 65-bit int": Case(2**64, "<int, 65 bits>"),
    "a huge int": Case(10**5000, "<int, 16610 bits>"),
    "datetime": Case(dt.datetime(2025, 1, 2, 3, 4, 5, tzinfo=dt.UTC), "2025-01-02T03:04:05+00:00"),
    "naive datetime": Case(dt.datetime(2025, 1, 2, 3, 4, 5), "2025-01-02T03:04:05"),  # noqa: DTZ001 - a naive datetime is the case under test
    "date": Case(dt.date(2025, 1, 2), "2025-01-02"),
    "bytes": Case(b"abc", "<bytes 3>"),
    "empty bytes": Case(b"", "<bytes 0>"),
    "bytearray": Case(bytearray(b"ab"), "<bytes 2>"),
    "binary": Case(Binary(b"abcd"), "<bytes 4>"),
    "object id": Case(ObjectId("0123456789abcdef01234567"), "0123456789abcdef01234567"),
    "uuid": Case(uuid.UUID(int=5), "00000000-0000-0000-0000-000000000005"),
    "decimal": Case(Decimal("1.5"), "1.5"),
    "decimal128": Case(Decimal128("3.25"), "3.25"),
    "decimal128 nan": Case(Decimal128("NaN"), "NaN"),
    "regex": Case(Regex("a"), "<Regex>"),
    "timestamp": Case(Timestamp(1, 1), "<Timestamp>"),
    "min key": Case(MinKey(), "<MinKey>"),
    "dbref": Case(DBRef("c", 1), "<DBRef>"),
    "arbitrary object": Case(object(), "<object>"),
    "set": Case({1}, "<set>"),
}


@pytest.mark.parametrize("case", SCALARS.values(), ids=SCALARS)
def test_scalars(case: Case) -> None:
    out = convert(case.value)
    assert out == case.expected
    assert type(out) is type(case.expected)
    json.dumps(out, allow_nan=False)  # plain JSON, no NaN


def test_code_is_shown_as_a_plain_string() -> None:
    out = convert(Code("x + 1"))
    assert out == "x + 1"
    assert type(out) is str


class TextCase(NamedTuple):
    length: int
    kept: int
    clipped: bool


TEXTS = {
    "one below the cap": TextCase(SAMPLE_MAX_TEXT - 1, SAMPLE_MAX_TEXT - 1, clipped=False),
    "exactly the cap": TextCase(SAMPLE_MAX_TEXT, SAMPLE_MAX_TEXT, clipped=False),
    "one past the cap": TextCase(SAMPLE_MAX_TEXT + 1, SAMPLE_MAX_TEXT, clipped=True),
    "far past the cap": TextCase(5_000, SAMPLE_MAX_TEXT, clipped=True),
}


@pytest.mark.parametrize("case", TEXTS.values(), ids=TEXTS)
def test_long_strings_and_keys_are_clipped(case: TextCase) -> None:
    text = "x" * case.length
    expected = "x" * case.kept + (ELLIPSIS if case.clipped else "")
    assert convert(text) == expected
    assert JsonSanitizer().document({text: 1}) == {expected: 1}
    assert convert(ObjectId()) != ELLIPSIS
    assert convert(Decimal("1E+5")) == "1E+5"


def test_the_clip_limits_are_the_documented_ones() -> None:
    assert (SAMPLE_MAX_TEXT, SAMPLE_MAX_ITEMS, SAMPLE_MAX_DEPTH, SAMPLE_MAX_NODES) == (
        200,
        20,
        4,
        2_000,
    )
    assert MAX_SAFE_INT == 9_007_199_254_740_991


# --------------------------------------------------------------------------- containers


def test_nested_documents_and_arrays_are_copied_as_plain_json() -> None:
    doc = {"a": {"b": [1, {"c": 5}]}, "t": (2, 3), "d": MappingProxyType({"e": None})}
    out = JsonSanitizer().document(doc)
    assert out == {"a": {"b": [1, {"c": 5}]}, "t": [2, 3], "d": {"e": None}}
    assert type(out) is dict
    assert type(out["a"]) is dict
    assert type(out["d"]) is dict
    assert type(out["t"]) is list


@pytest.mark.parametrize("kind", [SON, OrderedDict, dict])
def test_dict_like_documents_become_dicts_in_key_order(kind: Any) -> None:
    out = JsonSanitizer().document(kind([("z", 1), ("a", 2)]))
    assert type(out) is dict
    assert list(out) == ["z", "a"]


def test_non_text_keys_become_text() -> None:
    doc: Any = {1: "a", 2.5: "b"}
    assert JsonSanitizer().document(doc) == {"1": "a", "2.5": "b"}


class CountCase(NamedTuple):
    size: int
    marker: str | None


ITEMS = {
    "below the cap": CountCase(SAMPLE_MAX_ITEMS - 1, None),
    "exactly the cap": CountCase(SAMPLE_MAX_ITEMS, None),
    "one past": CountCase(SAMPLE_MAX_ITEMS + 1, "1 more keys"),
    "five past": CountCase(SAMPLE_MAX_ITEMS + 5, "5 more keys"),
}


@pytest.mark.parametrize("case", ITEMS.values(), ids=ITEMS)
def test_documents_keep_the_first_keys_and_say_how_many_were_left_out(case: CountCase) -> None:
    out = JsonSanitizer().document({f"k{i}": i for i in range(case.size)})
    kept = {k: v for k, v in out.items() if k != ELLIPSIS}
    assert list(kept) == [f"k{i}" for i in range(min(case.size, SAMPLE_MAX_ITEMS))]
    assert out.get(ELLIPSIS) == case.marker
    assert (ELLIPSIS in out) is (case.marker is not None)


ARRAY_ITEMS = {
    "below the cap": CountCase(SAMPLE_MAX_ITEMS - 1, None),
    "exactly the cap": CountCase(SAMPLE_MAX_ITEMS, None),
    "one past": CountCase(SAMPLE_MAX_ITEMS + 1, "... 1 more"),
    "five past": CountCase(SAMPLE_MAX_ITEMS + 5, "... 5 more"),
}


@pytest.mark.parametrize("case", ARRAY_ITEMS.values(), ids=ARRAY_ITEMS)
def test_arrays_keep_the_first_items_and_say_how_many_were_left_out(case: CountCase) -> None:
    out = convert(list(range(case.size)))
    assert isinstance(out, list)
    kept = min(case.size, SAMPLE_MAX_ITEMS)
    assert out[:kept] == list(range(kept))
    assert out[kept:] == ([case.marker] if case.marker else [])


def test_nesting_stops_at_the_depth_cap_with_a_summary() -> None:
    deep = {"a": {"b": {"c": {"d": {"e": 1, "f": 2}}}}}
    assert JsonSanitizer().document(deep) == {"a": {"b": {"c": {"d": "<object 2>"}}}}
    arrays = {"a": [[[[1, 2, 3]]]]}
    assert JsonSanitizer().document(arrays) == {"a": [[["<array 3>"]]]}
    mixed = {"a": [{"b": [{"c": 1}]}]}
    assert JsonSanitizer().document(mixed) == {"a": [{"b": ["<object 1>"]}]}


def test_the_last_level_below_the_cap_is_still_copied() -> None:
    assert JsonSanitizer().document({"a": {"b": {"c": {"d": 1}}}}) == {"a": {"b": {"c": {"d": 1}}}}


def test_the_value_budget_is_spent_across_documents_and_every_document_stays_a_dict() -> None:
    sanitizer = JsonSanitizer()
    wide = {f"k{i}": i for i in range(SAMPLE_MAX_ITEMS)}
    outs = [sanitizer.document(dict(wide)) for _ in range(SAMPLE_MAX_NODES // SAMPLE_MAX_ITEMS + 1)]
    assert outs[-2] == wide  # the 2000th value is the last one kept
    assert outs[-1] == dict.fromkeys(wide, ELLIPSIS)  # the 2001st on is not
    assert all(type(out) is dict for out in outs)


def test_a_document_that_would_explode_stays_small() -> None:
    inner = [list(range(SAMPLE_MAX_ITEMS)) for _ in range(SAMPLE_MAX_ITEMS)]
    doc = {f"k{i}": [list(row) for row in inner] for i in range(SAMPLE_MAX_ITEMS)}
    text = json.dumps(JsonSanitizer().document(doc))
    assert text.count(ELLIPSIS) > 0
    assert len(text) < 50_000
    assert len([c for c in text if c.isdigit()]) < 20_000
