# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``mongo_extract``: which values are usable names and values, and the exact reasons."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, NamedTuple

import pytest
from bson import Binary, Code, DBRef, Decimal128, Int64, MaxKey, MinKey, ObjectId, Regex, Timestamp
from bson.son import SON

from sankey_studio.models import NAME_MAX
from sankey_studio.sources.mongo_extract import (
    MAX_NUMERIC_CHARS,
    MISSING,
    FieldRejectedError,
    coerce_name,
    coerce_value,
)

OID = ObjectId("0123456789abcdef01234567")
NOT_SINGLE = "is not a single text or number value"
NOT_FINITE = "is not a finite number"


class Accept(NamedTuple):
    value: object
    expected: str


NAMES_ACCEPTED = {
    "text": Accept("Food", "Food"),
    "trimmed": Accept("  Rent \t", "Rent"),
    "inner whitespace is kept": Accept("a  b", "a  b"),
    "unicode": Accept("Café ☕", "Café ☕"),
    "format characters are fine": Accept("a" + chr(0x200D) + "b", "a" + chr(0x200D) + "b"),
    "int": Accept(7, "7"),
    "int64": Accept(Int64(2**40), str(2**40)),
    "float": Accept(2.5, "2.5"),
    "decimal": Accept(Decimal("1.5"), "1.5"),
    "decimal exponent": Accept(Decimal("1E+5"), "1E+5"),
    "decimal128": Accept(Decimal128("3.25"), "3.25"),
    "object id": Accept(OID, "0123456789abcdef01234567"),
    "uuid": Accept(uuid.UUID(int=5), "00000000-0000-0000-0000-000000000005"),
    "datetime": Accept(dt.datetime(2025, 1, 2, tzinfo=dt.UTC), "2025-01-02 00:00:00+00:00"),
    "date": Accept(dt.date(2025, 1, 2), "2025-01-02"),
    "exactly NAME_MAX characters": Accept("x" * NAME_MAX, "x" * NAME_MAX),
    "NAME_MAX after trimming": Accept(" " + "x" * NAME_MAX + " ", "x" * NAME_MAX),
    "a trailing tab is trimmed, not rejected": Accept("x\t", "x"),
}


@pytest.mark.parametrize("case", NAMES_ACCEPTED.values(), ids=NAMES_ACCEPTED)
def test_names_that_are_accepted(case: Accept) -> None:
    assert coerce_name(case.value) == case.expected


class Reject(NamedTuple):
    value: object
    reason: str


NAMES_REJECTED = {
    "missing": Reject(MISSING, "is missing"),
    "null": Reject(None, "is null"),
    "empty": Reject("", "is empty"),
    "blank": Reject(" \t\n ", "is empty"),
    "NAME_MAX + 1": Reject("x" * (NAME_MAX + 1), f"is longer than {NAME_MAX} characters"),
    "NAME_MAX + 1 behind blanks": Reject(
        " " + "x" * (NAME_MAX + 1), f"is longer than {NAME_MAX} characters"
    ),
    "NUL": Reject("a\x00b", "contains control characters"),
    "tab inside": Reject("a\tb", "contains control characters"),
    "newline inside": Reject("a\nb", "contains control characters"),
    "escape": Reject("a\x1bb", "contains control characters"),
    "DEL": Reject("a\x7fb", "contains control characters"),
    "C1 control": Reject("a\x85b", "contains control characters"),
    "first C1 control": Reject("a\x80b", "contains control characters"),
    "last C1 control": Reject("a\x9fb", "contains control characters"),
    "lone surrogate": Reject("a\ud800b", "contains control characters"),
    "last surrogate": Reject("a\udfffb", "contains control characters"),
    "bool": Reject(True, NOT_SINGLE),
    "list": Reject(["a"], NOT_SINGLE),
    "dict": Reject({"a": 1}, NOT_SINGLE),
    "bytes": Reject(b"a", NOT_SINGLE),
    "set": Reject({"a"}, NOT_SINGLE),
    "object": Reject(object(), NOT_SINGLE),
    "Binary": Reject(Binary(b"a"), NOT_SINGLE),
    "Code": Reject(Code("x"), NOT_SINGLE),
    "Regex": Reject(Regex("a"), NOT_SINGLE),
    "DBRef": Reject(DBRef("c", 1), NOT_SINGLE),
    "SON": Reject(SON([("a", 1)]), NOT_SINGLE),
    "Timestamp": Reject(Timestamp(1, 1), NOT_SINGLE),
    "MinKey": Reject(MinKey(), NOT_SINGLE),
    "MaxKey": Reject(MaxKey(), NOT_SINGLE),
    "nan": Reject(float("nan"), NOT_FINITE),
    "inf": Reject(float("inf"), NOT_FINITE),
    "-inf": Reject(float("-inf"), NOT_FINITE),
    "Decimal NaN": Reject(Decimal("NaN"), NOT_FINITE),
    "Decimal sNaN": Reject(Decimal("sNaN"), NOT_FINITE),
    "Decimal infinity": Reject(Decimal("-Infinity"), NOT_FINITE),
    "Decimal128 NaN": Reject(Decimal128("NaN"), NOT_FINITE),
    "Decimal128 sNaN": Reject(Decimal128("sNaN"), NOT_FINITE),
    "Decimal128 infinity": Reject(Decimal128("Infinity"), NOT_FINITE),
    "an int with too many digits": Reject(10**5000, "is a number with too many digits"),
}


@pytest.mark.parametrize("case", NAMES_REJECTED.values(), ids=NAMES_REJECTED)
def test_names_that_are_rejected(case: Reject) -> None:
    with pytest.raises(FieldRejectedError) as info:
        coerce_name(case.value)
    assert str(info.value) == case.reason


def test_a_decimal128_that_cannot_be_read_is_not_a_finite_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_self: Decimal128) -> Decimal:
        raise ArithmeticError

    monkeypatch.setattr(Decimal128, "to_decimal", broken)
    with pytest.raises(FieldRejectedError) as info:
        coerce_name(Decimal128("1"))
    assert str(info.value) == NOT_FINITE
    with pytest.raises(FieldRejectedError) as info:
        coerce_value(Decimal128("1"))
    assert str(info.value) == NOT_FINITE


# --------------------------------------------------------------------------- values


class Value(NamedTuple):
    value: object
    expected: float
    text: bool


VALUES_ACCEPTED = {
    "int": Value(1, 1.0, text=False),
    "float": Value(2.5, 2.5, text=False),
    "int64": Value(Int64(7), 7.0, text=False),
    "decimal": Value(Decimal("3.5"), 3.5, text=False),
    "decimal128": Value(Decimal128("3.25"), 3.25, text=False),
    "tiny": Value(1e-300, 1e-300, text=False),
    "subnormal": Value(5e-324, 5e-324, text=False),
    "string": Value("12.5", 12.5, text=True),
    "padded string": Value("  12.5\n", 12.5, text=True),
    "plus sign": Value("+5", 5.0, text=True),
    "exponent": Value("1e3", 1000.0, text=True),
    "capital exponent": Value("2E-1", 0.2, text=True),
    "leading dot": Value(".5", 0.5, text=True),
    "trailing dot": Value("5.", 5.0, text=True),
    "integer string": Value("007", 7.0, text=True),
    "MAX_NUMERIC_CHARS characters": Value("1" * MAX_NUMERIC_CHARS, float("1" * 64), text=True),
}


@pytest.mark.parametrize("case", VALUES_ACCEPTED.values(), ids=VALUES_ACCEPTED)
def test_values_that_are_accepted(case: Value) -> None:
    number, was_text = coerce_value(case.value)
    assert number == case.expected
    assert type(number) is float
    assert was_text is case.text


NOT_NUMBER = "is not a number"
NOT_POSITIVE = "is not greater than zero"

VALUES_REJECTED = {
    "missing": Reject(MISSING, "is missing"),
    "null": Reject(None, "is null"),
    "bool": Reject(True, NOT_NUMBER),
    "list": Reject([1], NOT_NUMBER),
    "dict": Reject({"a": 1}, NOT_NUMBER),
    "bytes": Reject(b"1", NOT_NUMBER),
    "Code": Reject(Code("1"), NOT_NUMBER),
    "ObjectId": Reject(OID, NOT_NUMBER),
    "datetime": Reject(dt.datetime(2025, 1, 2, tzinfo=dt.UTC), NOT_NUMBER),
    "empty string": Reject("", NOT_NUMBER),
    "words": Reject("many", NOT_NUMBER),
    "thousands separator": Reject("1,234", NOT_NUMBER),
    "underscore": Reject("1_000", NOT_NUMBER),
    "nan text": Reject("nan", NOT_NUMBER),
    "inf text": Reject("inf", NOT_NUMBER),
    "infinity text": Reject("-Infinity", NOT_NUMBER),
    "bare exponent": Reject("1e", NOT_NUMBER),
    "exponent only": Reject("e5", NOT_NUMBER),
    "two signs": Reject("--1", NOT_NUMBER),
    "inner space": Reject("1 2", NOT_NUMBER),
    "lone sign": Reject("+", NOT_NUMBER),
    "lone dot": Reject(".", NOT_NUMBER),
    "unicode digits": Reject(chr(0x663), NOT_NUMBER),
    "trailing newline text": Reject("5\nx", NOT_NUMBER),
    "MAX_NUMERIC_CHARS + 1": Reject("1" * (MAX_NUMERIC_CHARS + 1), NOT_NUMBER),
    "a long run of digits ending badly": Reject("1" * 100_000 + "x", NOT_NUMBER),
    "zero": Reject(0, NOT_POSITIVE),
    "float zero": Reject(0.0, NOT_POSITIVE),
    "negative zero": Reject(-0.0, NOT_POSITIVE),
    "negative": Reject(-1, NOT_POSITIVE),
    "negative float": Reject(-0.5, NOT_POSITIVE),
    "zero text": Reject("0", NOT_POSITIVE),
    "negative text": Reject("-5", NOT_POSITIVE),
    "Decimal zero": Reject(Decimal(0), NOT_POSITIVE),
    "Decimal128 negative": Reject(Decimal128("-1"), NOT_POSITIVE),
    "nan": Reject(float("nan"), NOT_FINITE),
    "inf": Reject(float("inf"), NOT_FINITE),
    "Decimal NaN": Reject(Decimal("NaN"), NOT_FINITE),
    "Decimal sNaN": Reject(Decimal("sNaN"), NOT_FINITE),
    "Decimal infinity": Reject(Decimal("Infinity"), NOT_FINITE),
    "Decimal128 NaN": Reject(Decimal128("NaN"), NOT_FINITE),
    "Decimal128 infinity": Reject(Decimal128("-Infinity"), NOT_FINITE),
    "text beyond the float range": Reject("1e999", NOT_FINITE),
    "Decimal beyond the float range": Reject(Decimal("1E+400"), NOT_FINITE),
    "an int beyond the float range": Reject(10**400, "is out of range"),
}


@pytest.mark.parametrize("case", VALUES_REJECTED.values(), ids=VALUES_REJECTED)
def test_values_that_are_rejected(case: Reject) -> None:
    with pytest.raises(FieldRejectedError) as info:
        coerce_value(case.value)
    assert str(info.value) == case.reason


def test_the_numeric_text_limit_is_sixty_four_characters() -> None:
    assert MAX_NUMERIC_CHARS == 64


def test_the_rejection_is_a_value_error_so_callers_may_catch_it_broadly() -> None:
    assert issubclass(FieldRejectedError, ValueError)


def test_coercers_accept_any_object() -> None:
    odd: Any = object()
    for coerce in (coerce_name, coerce_value):
        with pytest.raises(FieldRejectedError):
            coerce(odd)
