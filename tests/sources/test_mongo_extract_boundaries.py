"""``mongo_extract``: edges of the numeric-text grammar and of the control-character class."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.sources.mongo_extract import FieldRejectedError, coerce_name, coerce_value

CONTROL = "contains control characters"
NOT_NUMBER = "is not a number"


class Number(NamedTuple):
    text: str
    expected: float


NUMERIC_TEXT = {
    "positive exponent sign": Number("1e+3", 1000.0),
    "capital E with a plus": Number("1E+3", 1000.0),
    "negative exponent sign": Number("2e-3", 0.002),
    "leading dot and signed exponent": Number(".5e+1", 5.0),
    "trailing dot and signed exponent": Number("5.e+1", 50.0),
    "signed mantissa and exponent": Number("+2.5E+1", 25.0),
}


@pytest.mark.parametrize("case", NUMERIC_TEXT.values(), ids=NUMERIC_TEXT)
def test_numeric_text_with_a_signed_exponent_is_read_as_text(case: Number) -> None:
    assert coerce_value(case.text) == (case.expected, True)


@pytest.mark.parametrize("text", ["1e+", "1e-", "1e++3", "1e+-3", "e+3"])
def test_an_incomplete_exponent_is_not_a_number(text: str) -> None:
    with pytest.raises(FieldRejectedError) as info:
        coerce_value(text)
    assert str(info.value) == NOT_NUMBER


class Edge(NamedTuple):
    code: int
    rejected: bool


# Both sides of every edge of ``[\x00-\x1f\x7f-\x9f\ud800-\udfff]``; the character sits between
# two letters because ``str.strip`` would remove \x1c..\x1f at the ends.
EDGES = {
    "SOH": Edge(0x01, rejected=True),
    "record separator": Edge(0x1E, rejected=True),
    "unit separator": Edge(0x1F, rejected=True),
    "space": Edge(0x20, rejected=False),
    "tilde": Edge(0x7E, rejected=False),
    "DEL": Edge(0x7F, rejected=True),
    "first C1 control": Edge(0x80, rejected=True),
    "next to last C1 control": Edge(0x9E, rejected=True),
    "last C1 control": Edge(0x9F, rejected=True),
    "no-break space": Edge(0xA0, rejected=False),
    "inverted exclamation mark": Edge(0xA1, rejected=False),
    "last char before the surrogates": Edge(0xD7FF, rejected=False),
    "first surrogate": Edge(0xD800, rejected=True),
    "middle surrogate": Edge(0xDBFF, rejected=True),
    "last surrogate": Edge(0xDFFF, rejected=True),
    "first char after the surrogates": Edge(0xE000, rejected=False),
}


@pytest.mark.parametrize("case", EDGES.values(), ids=EDGES)
def test_a_name_is_rejected_exactly_for_control_characters(case: Edge) -> None:
    name = f"a{chr(case.code)}b"
    if case.rejected:
        with pytest.raises(FieldRejectedError) as info:
            coerce_name(name)
        assert str(info.value) == CONTROL
    else:
        assert coerce_name(name) == name
