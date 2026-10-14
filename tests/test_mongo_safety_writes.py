"""``mongo_safety`` write guards: ``check_write_document`` and ``check_write_update``.

Source write-back may insert one small document of plain fields and scalars, or ``$set`` /
``$unset`` one field. Every limit is tabled on both sides, with the exact message.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from sankey_studio.mongo_safety import (
    WRITE_DOCUMENT_MAX_BYTES,
    WRITE_MAX_DEPTH,
    WRITE_TEXT_MAX,
    check_write_document,
    check_write_update,
)
from tests.safety_support import ACCEPTED, outcome_of

PATH = "a written field must be a plain dotted name of at most 4 parts"
NO_ID = "the _id field is never written"
TEXT = "a written text is too long or holds control characters"
FORMULA = "a written text could be read as a spreadsheet formula"
VALUE = "a written value must be text, a finite number, a boolean or null"
DEPTH = "a written document is nested too deeply"
KEYS = "a written document may only use plain field names"
BIG = "a written document is too large"
SHAPE = "a source update must be one $set or $unset of one field"
UNSET = "$unset takes an empty string as its value"
CATEGORY = "a written category must be text"

KEY_CASES = {
    "lower": ("a", ACCEPTED),
    "underscore start": ("_a", ACCEPTED),
    "upper and digits": ("A1", ACCEPTED),
    "hyphen inside": ("a-b", ACCEPTED),
    "empty": ("", KEYS),
    "digit start": ("1a", KEYS),
    "operator": ("$set", KEYS),
    "dollar inside": ("a$b", KEYS),
    "dotted": ("a.b", KEYS),
    "space": ("a b", KEYS),
    "hyphen start": ("-a", KEYS),
    "non ascii": ("é", KEYS),
    "newline": ("a\n", KEYS),
}


@pytest.mark.parametrize(("key", "expected"), KEY_CASES.values(), ids=KEY_CASES)
def test_document_keys(key: str, expected: str) -> None:
    assert outcome_of(check_write_document, {key: "x"}) == expected


def nested(depth: int) -> dict[str, Any]:
    doc: dict[str, Any] = {"leaf": 1}
    for _ in range(depth - 1):
        doc = {"k": doc}
    return doc


def test_the_depth_limit_is_four() -> None:
    assert WRITE_MAX_DEPTH == 4
    assert outcome_of(check_write_document, nested(1)) == ACCEPTED
    assert outcome_of(check_write_document, nested(4)) == ACCEPTED
    assert outcome_of(check_write_document, nested(5)) == DEPTH


def test_a_nested_key_is_checked_like_a_top_level_one() -> None:
    assert outcome_of(check_write_document, {"a": {"$bad": 1}}) == KEYS


def test_the_id_field_is_never_written_at_the_top_but_may_be_nested() -> None:
    assert outcome_of(check_write_document, {"_id": "x"}) == NO_ID
    assert outcome_of(check_write_document, {"a": {"_id": "x"}}) == ACCEPTED


TEXT_CASES = {
    "empty": ("", ACCEPTED),
    "plain": ("Groceries", ACCEPTED),
    "unicode": ("Café \U0001f600", ACCEPTED),
    "space": ("a b", ACCEPTED),
    "1000 characters": ("a" * WRITE_TEXT_MAX, ACCEPTED),
    "1001 characters": ("a" * (WRITE_TEXT_MAX + 1), TEXT),
    "NUL": ("a\x00b", TEXT),
    "newline": ("a\nb", TEXT),
    "tab": ("a\tb", TEXT),
    "unit separator": ("a\x1fb", TEXT),
    "DEL": ("a\x7fb", TEXT),
    "C1 control": ("a\x9fb", TEXT),
    "first printable after C1": ("a" + chr(0xA0) + "b", ACCEPTED),
    "lone surrogate": ("a\ud800b", TEXT),
    "equals": ("=SUM(A1)", FORMULA),
    "plus": ("+1", FORMULA),
    "minus": ("-1", FORMULA),
    "at": ("@x", FORMULA),
    "blank then equals": (" =x", FORMULA),
    "CR then text": ("\rx", TEXT),
    "formula marks inside": ("a=b+c-d@e", ACCEPTED),
}


@pytest.mark.parametrize(("text", "expected"), TEXT_CASES.values(), ids=TEXT_CASES)
def test_document_text_values(text: str, expected: str) -> None:
    assert outcome_of(check_write_document, {"a": text}) == expected


SCALARS = {
    "true": (True, ACCEPTED),
    "false": (False, ACCEPTED),
    "null": (None, ACCEPTED),
    "zero": (0, ACCEPTED),
    "negative int": (-5, ACCEPTED),
    "float": (1.5, ACCEPTED),
    "negative float": (-1.5e300, ACCEPTED),
    "int64 max": (2**63 - 1, ACCEPTED),
    "int64 max + 1": (2**63, VALUE),
    "int64 min": (-(2**63), ACCEPTED),
    "int64 min - 1": (-(2**63) - 1, VALUE),
    "nan": (math.nan, VALUE),
    "inf": (math.inf, VALUE),
    "-inf": (-math.inf, VALUE),
    "bytes": (b"x", VALUE),
    "list": ([1], VALUE),
    "tuple": ((1,), VALUE),
    "set": ({1}, VALUE),
    "object": (object(), VALUE),
}


@pytest.mark.parametrize(("value", "expected"), SCALARS.values(), ids=SCALARS)
def test_document_scalar_values(value: object, expected: str) -> None:
    assert outcome_of(check_write_document, {"a": value}) == expected


def doc_of_size(size: int) -> dict[str, Any]:
    """A valid document whose JSON text is exactly ``size`` characters."""
    doc: dict[str, Any] = {f"k{index:02d}": "x" * WRITE_TEXT_MAX for index in range(16)}
    filler = size - len(json.dumps({**doc, "z": ""}))
    assert 0 <= filler <= WRITE_TEXT_MAX
    return {**doc, "z": "x" * filler}


def test_the_size_limit_is_16_kb_on_both_sides() -> None:
    assert WRITE_DOCUMENT_MAX_BYTES == 16 * 1024
    assert len(json.dumps(doc_of_size(WRITE_DOCUMENT_MAX_BYTES))) == WRITE_DOCUMENT_MAX_BYTES
    assert outcome_of(check_write_document, doc_of_size(WRITE_DOCUMENT_MAX_BYTES)) == ACCEPTED
    assert outcome_of(check_write_document, doc_of_size(WRITE_DOCUMENT_MAX_BYTES + 1)) == BIG


def test_a_realistic_document_is_accepted() -> None:
    doc = {"meta": {"from": "Budget", "to": "Gifts"}, "amount": 50, "cat": "Fun", "year": 2025}
    assert outcome_of(check_write_document, doc) == ACCEPTED


# --------------------------------------------------------------------------- updates

PATHS = {
    "plain": ("cat", ACCEPTED),
    "dotted": ("meta.category", ACCEPTED),
    "four parts": ("a.b.c.d", ACCEPTED),
    "five parts": ("a.b.c.d.e", PATH),
    "empty": ("", PATH),
    "empty segment": ("a..b", PATH),
    "trailing dot": ("a.", PATH),
    "operator": ("$set", PATH),
    "operator segment": ("a.$b", PATH),
    "digit segment": ("a.0", PATH),
    "space": ("a b", PATH),
    "id": ("_id", NO_ID),
    "id inside": ("_id.x", NO_ID),
    "id lookalike": ("_idx", ACCEPTED),
    "id nested deeper": ("a._id", ACCEPTED),
}


@pytest.mark.parametrize(("path", "expected"), PATHS.values(), ids=PATHS)
def test_update_paths(path: str, expected: str) -> None:
    assert outcome_of(check_write_update, {"$set": {path: "Food"}}) == expected
    assert outcome_of(check_write_update, {"$unset": {path: ""}}) == expected


UPDATES = {
    "set": ({"$set": {"cat": "Food"}}, ACCEPTED),
    "unset": ({"$unset": {"cat": ""}}, ACCEPTED),
    "set empty text": ({"$set": {"cat": ""}}, ACCEPTED),
    "empty update": ({}, SHAPE),
    "two operators": ({"$set": {"a": "x"}, "$unset": {"b": ""}}, SHAPE),
    "other operator": ({"$inc": {"a": "x"}}, SHAPE),
    "operator without dollar": ({"set": {"a": "x"}}, SHAPE),
    "fields not a mapping": ({"$set": "cat"}, SHAPE),
    "no field": ({"$set": {}}, SHAPE),
    "two fields": ({"$set": {"a": "x", "b": "y"}}, SHAPE),
    "set to a number": ({"$set": {"cat": 5}}, CATEGORY),
    "set to null": ({"$set": {"cat": None}}, CATEGORY),
    "set to a list": ({"$set": {"cat": ["x"]}}, CATEGORY),
    "set to a long text": ({"$set": {"cat": "a" * 1001}}, TEXT),
    "set to 1000 characters": ({"$set": {"cat": "a" * 1000}}, ACCEPTED),
    "set to a control": ({"$set": {"cat": "a\x00"}}, TEXT),
    "set to a formula": ({"$set": {"cat": "=1+1"}}, FORMULA),
    "unset with text": ({"$unset": {"cat": "x"}}, UNSET),
    "unset with null": ({"$unset": {"cat": None}}, UNSET),
    "unset with one": ({"$unset": {"cat": 1}}, UNSET),
    "unset with true": ({"$unset": {"cat": True}}, UNSET),
}


@pytest.mark.parametrize(("update", "expected"), UPDATES.values(), ids=UPDATES)
def test_update_shapes(update: dict[str, Any], expected: str) -> None:
    assert outcome_of(check_write_update, update) == expected


def test_a_field_that_is_not_text_is_refused() -> None:
    assert outcome_of(check_write_update, {"$set": {5: "x"}}) == SHAPE
