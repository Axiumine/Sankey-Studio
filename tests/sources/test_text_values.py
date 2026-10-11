"""Number and name cleaning of the text formats: boundaries and exact messages."""

from __future__ import annotations

import math
from typing import Any, NamedTuple

import pytest

from sankey_studio.models import NAME_MAX
from sankey_studio.sources.formats.values import (
    MAX_NUMBER_CHARS,
    VALUE_MESSAGE,
    RowError,
    clean_name,
    clean_value,
    parse_value,
)
from tests.sources.idtools import safe_id


class ValueCase(NamedTuple):
    text: str
    expected: float | None


PARSE_TABLE = [
    ValueCase("12", 12.0),
    ValueCase("12.5", 12.5),
    ValueCase(".5", 0.5),
    ValueCase("5.", 5.0),
    ValueCase("+7", 7.0),
    ValueCase(" 12 ", 12.0),
    ValueCase("1e3", 1000.0),
    ValueCase("1E3", 1000.0),
    ValueCase("1e+3", 1000.0),
    ValueCase("1.5e-2", 0.015),
    ValueCase("1,234.5", 1234.5),
    ValueCase("+1,234.5", 1234.5),
    ValueCase("1,234,567", 1234567.0),
    ValueCase("12,345,678.9", 12345678.9),
    ValueCase("000000001", 1.0),
    ValueCase("0.001", 0.001),
    # refused
    ValueCase("", None),
    ValueCase("   ", None),
    ValueCase("abc", None),
    ValueCase("nan", None),
    ValueCase("NaN", None),
    ValueCase("inf", None),
    ValueCase("-inf", None),
    ValueCase("Infinity", None),
    ValueCase("-5", None),
    ValueCase("0", None),
    ValueCase("0.0", None),
    ValueCase("-0", None),
    ValueCase("1_000", None),
    ValueCase("1 000", None),
    ValueCase("1,234", None),
    ValueCase("123,456", None),
    ValueCase("1,23", None),
    ValueCase("12,34", None),
    ValueCase("1,5", None),
    ValueCase("1234,567", None),
    ValueCase(",123", None),
    ValueCase("1,234,", None),
    ValueCase("1,234.", None),
    ValueCase("1,234.5,6", None),
    ValueCase("1..2", None),
    ValueCase("1.2.3", None),
    ValueCase("--5", None),
    ValueCase("++5", None),
    ValueCase("1e", None),
    ValueCase("e5", None),
    ValueCase("0x10", None),
    ValueCase("\u0661\u0662\u0663", None),  # Arabic-Indic digits are not ASCII digits
    ValueCase("1e999", None),  # overflows to infinity
    ValueCase("1\n", 1.0),  # surrounding whitespace is stripped first
    ValueCase("1,234\n,5", None),
    # more than one digit after the point, in both number shapes
    ValueCase(".25", 0.25),
    ValueCase(".125", 0.125),
    ValueCase("1,234.56", 1234.56),
    ValueCase("12,345,678.90", 12345678.9),
    # an exponent needs digits; a thousands group needs a digit before the first comma
    ValueCase("1e+", None),
    ValueCase("1e-", None),
    ValueCase("1E+", None),
    ValueCase(",123,456", None),
    ValueCase(",123,456.5", None),
    ValueCase("++1,234,567", None),
    ValueCase("?1,234,567", None),
    # every digit may appear in every position of both shapes
    ValueCase(".05", 0.05),
    ValueCase(".9", 0.9),
    ValueCase(".50", 0.5),
    ValueCase("1e9", 1e9),
    ValueCase("1e19", 1e19),
    ValueCase("1,000,000", 1_000_000.0),
    ValueCase("10,000,000", 10_000_000.0),
    ValueCase("9,999,999", 9_999_999.0),
    # the point of a decimal part is a literal point and needs a digit
    ValueCase(".", None),
    ValueCase("1,234,567x5", None),
    ValueCase("1,234,567e5", None),
    ValueCase("1,234,567-5", None),
]


@pytest.mark.parametrize("case", PARSE_TABLE, ids=[safe_id(repr(c.text)) for c in PARSE_TABLE])
def test_parse_value_table(case: ValueCase) -> None:
    assert parse_value(case.text) == case.expected


def test_parse_value_length_boundary() -> None:
    assert MAX_NUMBER_CHARS == 64
    assert parse_value("1" + "0" * 63) == 1e63  # 64 characters
    assert parse_value("1" + "0" * 64) is None  # 65 characters
    assert parse_value("0" * 63 + "1") == 1.0
    assert parse_value(" " * 10 + "1" + " " * 80) == 1.0  # the limit is on the stripped text


def test_parse_value_never_returns_a_non_finite_or_non_positive_number() -> None:
    for text in ("1e308", "1.7976931348623157e308", "4.9e-324"):
        value = parse_value(text)
        assert value is not None
        assert math.isfinite(value)
        assert value > 0


class NameCase(NamedTuple):
    raw: Any
    role: str
    expected: str


NAME_OK = [
    NameCase("a", "source", "a"),
    NameCase("  a b  ", "target", "a b"),
    NameCase("\tx\n", "source", "x"),
    NameCase(7, "source", "7"),
    NameCase("x" * NAME_MAX, "source", "x" * NAME_MAX),
    NameCase(" " + "x" * NAME_MAX + " ", "target", "x" * NAME_MAX),
    NameCase("caf\u00e9", "source", "caf\u00e9"),
]


@pytest.mark.parametrize("case", NAME_OK, ids=[safe_id(repr(c.raw)[:20]) for c in NAME_OK])
def test_clean_name_accepts(case: NameCase) -> None:
    assert clean_name(case.raw, case.role) == case.expected


class BadName(NamedTuple):
    raw: Any
    role: str
    message: str


NAME_BAD = [
    BadName(None, "source", "source is missing"),
    BadName(None, "target", "target is missing"),
    BadName(True, "source", "source is not text"),
    BadName(1.5, "target", "target is not text"),
    BadName(["a"], "source", "source is not text"),
    BadName({"a": 1}, "target", "target is not text"),
    BadName(b"a", "source", "source is not text"),
    BadName("", "source", "source is empty"),
    BadName("  \t ", "target", "target is empty"),
    BadName("x" * (NAME_MAX + 1), "source", f"source is longer than {NAME_MAX} characters"),
    BadName("x" * (NAME_MAX + 1), "target", f"target is longer than {NAME_MAX} characters"),
    BadName("a\0b", "source", "source contains a NUL character"),
    BadName("\ud800", "target", "target contains an invalid character"),
]


@pytest.mark.parametrize(
    "case", NAME_BAD, ids=[safe_id(repr(c.raw)[:20] + c.role) for c in NAME_BAD]
)
def test_clean_name_refuses_with_the_exact_message(case: BadName) -> None:
    with pytest.raises(RowError) as info:
        clean_name(case.raw, case.role)
    assert str(info.value) == case.message


class ValueRaw(NamedTuple):
    raw: Any
    expected: float


VALUE_OK = [
    ValueRaw("1,234.5", 1234.5),
    ValueRaw(" 3 ", 3.0),
    ValueRaw(5, 5.0),
    ValueRaw(2.5, 2.5),
    ValueRaw(10**30, 1e30),
]


@pytest.mark.parametrize("case", VALUE_OK, ids=[safe_id(repr(c.raw)) for c in VALUE_OK])
def test_clean_value_accepts(case: ValueRaw) -> None:
    assert clean_value(case.raw) == case.expected


class BadValue(NamedTuple):
    raw: Any
    message: str


VALUE_BAD = [
    BadValue(None, "value is missing"),
    BadValue("", "value is empty"),
    BadValue("  ", "value is empty"),
    BadValue("abc", VALUE_MESSAGE),
    BadValue("0", VALUE_MESSAGE),
    BadValue(0, VALUE_MESSAGE),
    BadValue(-1, VALUE_MESSAGE),
    BadValue(0.0, VALUE_MESSAGE),
    BadValue(float("nan"), VALUE_MESSAGE),
    BadValue(float("inf"), VALUE_MESSAGE),
    BadValue(True, VALUE_MESSAGE),
    BadValue(False, VALUE_MESSAGE),
    BadValue(10**400, VALUE_MESSAGE),  # too large for a float
    BadValue([1], VALUE_MESSAGE),
    BadValue({"v": 1}, VALUE_MESSAGE),
]


@pytest.mark.parametrize("case", VALUE_BAD, ids=[safe_id(repr(c.raw)[:20]) for c in VALUE_BAD])
def test_clean_value_refuses_with_the_exact_message(case: BadValue) -> None:
    with pytest.raises(RowError) as info:
        clean_value(case.raw)
    assert str(info.value) == case.message


def test_value_message_is_stable() -> None:
    assert VALUE_MESSAGE == "value must be a positive number"
