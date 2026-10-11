"""The d3-format subset used for labels and the donut total."""

from __future__ import annotations

import math
import random
from decimal import Decimal
from fractions import Fraction
from typing import NamedTuple

import pytest

from sankey_studio.render.numfmt import (
    FALLBACK,
    MAX_PRECISION,
    MAX_WIDTH,
    SI_PREFIXES,
    Spec,
    format_value,
    parse_spec,
)


class Fmt(NamedTuple):
    value: float
    spec: str
    expected: str


FORMATS = [
    Fmt(1234.5678, ",.2~f", "1,234.57"),
    Fmt(1234.5, ",.2~f", "1,234.5"),
    Fmt(1234.0, ",.2~f", "1,234"),
    Fmt(1234.0, ",.2f", "1,234.00"),
    Fmt(1234.0, ",~d", "1,234"),
    Fmt(1000.0, ".0~f", "1000"),
    Fmt(1234.0, ".2f", "1234.00"),
    Fmt(0.5, "f", "0.500000"),
    Fmt(0.5, ".0f", "1"),
    Fmt(1234.56, ",d", "1,235"),
    Fmt(1234.56, "d", "1235"),
    Fmt(0.256, ".1%", "25.6%"),
    Fmt(0.256, ".0%", "26%"),
    Fmt(0.25, ".2~%", "25%"),
    Fmt(0.256, "%", "25.600000%"),
    Fmt(1234.0, ".3s", "1.23k"),
    Fmt(1500000.0, ".2s", "1.5M"),
    Fmt(0.00042, ".2s", "420u"),
    Fmt(0.0, ".2s", "0"),
    Fmt(999999.0, ".3s", "1M"),
    Fmt(420.0, ".2s", "420"),
    Fmt(12345678.9, ".4s", "12.35M"),
    Fmt(5.0, ".3s", "5"),
    Fmt(1234.0, ".1s", "1k"),
    Fmt(1234.0, ".0s", "1k"),
    Fmt(1234.0, "s", "1.234k"),
    Fmt(-0.0, ".2s", "0"),
    Fmt(1e30, ".2s", "1000000Y"),
    Fmt(1e27, ".3s", "1000Y"),
    Fmt(1e-30, ".2s", "0.000001y"),
    Fmt(1234.5, "", "1234.5"),
    Fmt(1234.5, ".1", "1e+03"),
    Fmt(1234.5, ".0", "1e+03"),
    Fmt(0.256, "8.1%", "   25.6%"),
    Fmt(1234.0, "6.3s", " 1.23k"),
    Fmt(1234.5, "09,.1f", "001,234.5"),
    Fmt(1234.5, ",", "1,234.5"),
    Fmt(1234.5, ".2g", "1.2e+03"),
    Fmt(0.1 + 0.2, "", "0.3"),
    Fmt(1234.5, "+,.1f", "+1,234.5"),
    Fmt(1234.5, " ,.1f", " 1,234.5"),
    Fmt(1234.5, "-,.1f", "1,234.5"),
    Fmt(-1234.5, ",.1f", "-1,234.5"),
    Fmt(-1234.5, "+,.1f", "-1,234.5"),
    Fmt(5.0, "$,.2f", "$5.00"),
    Fmt(5.0, "+$.0f", "+$5"),
    Fmt(5.0, "08.2f", "00005.00"),
    Fmt(5.0, "8.2f", "    5.00"),
    Fmt(5.0, "3.2f", "5.00"),
    Fmt(5.0, "05.2f", "05.00"),
    Fmt(-5.0, "07.1f", "-0005.0"),
    Fmt(1234.5, ",.2~z", "1.2e+03"),
    Fmt(1234.5, ",~z", "1,234.5"),
    Fmt(1234.5, "not a spec", "1,234.5"),
]


@pytest.mark.parametrize("case", FORMATS)
def test_format_table(case: Fmt) -> None:
    assert format_value(case.value, case.spec) == case.expected


def test_parse_spec_reads_every_part() -> None:
    assert parse_spec("+$8,.3~f") == Spec(
        sign="+", symbol="$", zero=False, width=8, comma=True, precision=3, trim=True, kind="f"
    )
    assert parse_spec("+$08,.3~f") == Spec(
        sign="+", symbol="$", zero=True, width=8, comma=True, precision=3, trim=True, kind="f"
    )
    assert parse_spec("") == Spec()
    assert parse_spec("%").kind == "%"


def test_unparseable_specs_read_as_the_fallback() -> None:
    assert parse_spec("!!") is FALLBACK
    assert Spec(comma=True, precision=2, trim=True, kind="f") == FALLBACK


def test_the_hash_symbol_is_accepted_and_ignored() -> None:
    assert parse_spec("#.2f").symbol == ""
    assert format_value(5.0, "#.2f") == "5.00"


#: Exact ties (the float is EXACTLY halfway) round up, away from zero: JavaScript's toFixed and
#: Math.round, so d3 and Plotly in the browser. Python's own format rounds them to even.
FIXED_TIES = [
    Fmt(0.5, ".0f", "1"),
    Fmt(1.5, ".0f", "2"),
    Fmt(2.5, ".0f", "3"),
    Fmt(3.5, ".0f", "4"),
    Fmt(2.5, ",.0f", "3"),
    Fmt(1234.5, ",.0f", "1,235"),
    Fmt(999999.5, ".0f", "1000000"),
    Fmt(0.125, ".2f", "0.13"),
    Fmt(0.375, ".2f", "0.38"),
    Fmt(0.25, ".1f", "0.3"),
    Fmt(0.75, ".1f", "0.8"),
    Fmt(0.0625, ".3f", "0.063"),
    Fmt(0.125, ".2~f", "0.13"),
    Fmt(0.5, "d", "1"),
    Fmt(2.5, "d", "3"),
    Fmt(1234.5, ",d", "1,235"),
    Fmt(0.025, ".0%", "3%"),  # 0.025 * 100 is exactly 2.5
    Fmt(0.005, ".0%", "1%"),
    Fmt(0.125, ".1%", "12.5%"),
    Fmt(0.00125, ".1%", "0.1%"),
    # the negative sign is split off first, so a tie goes away from zero
    Fmt(-0.5, ".0f", "-1"),
    Fmt(-2.5, ".0f", "-3"),
    Fmt(-2.5, ",.0f", "-3"),
    Fmt(-1234.5, ",.0f", "-1,235"),
    Fmt(-0.125, ".2f", "-0.13"),
    Fmt(-0.375, ".2f", "-0.38"),
    Fmt(-2.5, "d", "-3"),
    Fmt(-0.025, ".0%", "-3%"),
    Fmt(-2.5, "+.0f", "-3"),
    Fmt(2.5, "+.0f", "+3"),
    # NOT ties: the exact binary value decides, never the decimal text
    Fmt(2.675, ".2f", "2.67"),
    Fmt(1.005, ".2f", "1.00"),
    Fmt(0.4999999999999999, ".0f", "0"),
    Fmt(-1.005, ".2f", "-1.00"),
    Fmt(0.49, ".0f", "0"),
    Fmt(0.51, ".0f", "1"),
]


@pytest.mark.parametrize("case", FIXED_TIES, ids=lambda case: f"{case.value}|{case.spec}")
def test_exact_ties_round_up_like_javascript(case: Fmt) -> None:
    assert format_value(case.value, case.spec) == case.expected


#: ``s``: significant digits, an exact tie rounds up, and the SI prefix is picked AFTER
#: rounding (d3: 999999.5 with ``.3s`` is 1.00M, never 1000k). Zeros stay trimmed.
SI_TIES = [
    Fmt(999999.5, ".3s", "1M"),
    Fmt(999999.0, ".3s", "1M"),
    Fmt(999499.0, ".3s", "999k"),
    Fmt(999500.0, ".3s", "1M"),
    Fmt(999.5, ".3s", "1k"),
    Fmt(999.4, ".3s", "999"),
    Fmt(9995.0, ".3s", "10k"),
    Fmt(99500.0, ".2s", "100k"),
    Fmt(99.5, ".2s", "100"),
    Fmt(2.5, ".1s", "3"),
    Fmt(1.5, ".1s", "2"),
    Fmt(1250.0, ".2s", "1.3k"),
    Fmt(1350.0, ".2s", "1.4k"),
    Fmt(12345.0, ".2s", "12k"),
    Fmt(0.0005, ".1s", "500u"),
    Fmt(0.00099995, ".3s", "1m"),
    Fmt(0.00099949, ".3s", "999u"),
    Fmt(9.9999e26, ".2s", "1000Y"),
    Fmt(-999999.5, ".3s", "-1M"),
    Fmt(-1250.0, ".2s", "-1.3k"),
    Fmt(-2.5, ".1s", "-3"),
    Fmt(-999.5, ".3s", "-1k"),
    Fmt(9.995, ".3s", "9.99"),  # 9.995 is below the tie in binary
]


@pytest.mark.parametrize("case", SI_TIES, ids=lambda case: f"{case.value}|{case.spec}")
def test_si_ties_round_up_and_the_prefix_follows_the_rounded_value(case: Fmt) -> None:
    assert format_value(case.value, case.spec) == case.expected


def test_a_carry_moves_the_unit_to_the_next_prefix_at_every_step() -> None:
    for step in range(-8, 8):
        unit = 10.0 ** (3 * step)
        assert format_value(999.99 * unit, ".3s") == "1" + SI_PREFIXES[8 + step + 1]
        assert format_value(999.4 * unit, ".3s") == "999" + SI_PREFIXES[8 + step]


def half_up_text(value: float, places: int) -> str:
    """The oracle: exact rational arithmetic, ``floor(x * 10**places + 1/2)``, comma grouped."""
    scaled = math.floor(Fraction(abs(value)) * 10**places + Fraction(1, 2))
    whole, decimals = divmod(scaled, 10**places)
    return f"{whole:,}.{decimals:0{places}d}" if places else f"{whole:,}"


def test_fixed_notation_is_exact_half_up_and_python_agrees_off_the_ties() -> None:
    rnd = random.Random(11)
    ties = 0
    for _ in range(3000):
        value = rnd.choice([1, 10, 1e3, 1e6, 1e12, 1e25, 1e-3, 1e-9]) * rnd.random()
        if rnd.random() < 0.5:
            value = rnd.randrange(1, 100_000) / 2 ** rnd.randrange(0, 9)  # dyadic: often a tie
        places = rnd.randrange(0, 10)
        expected = half_up_text(value, places)
        assert format_value(value, f",.{places}f") == expected
        assert format_value(-value, f",.{places}f") == "-" + expected
        if Fraction(value) * 10**places % 1 == Fraction(1, 2):
            ties += 1
        else:
            assert expected == format(value, f",.{places}f")
    assert ties > 100


class Oracle(NamedTuple):
    text: str
    tie: bool
    carry: bool


def si_oracle(value: float, digits: int) -> Oracle:
    """Exact rational arithmetic: round half up to ``digits`` significant digits, then the prefix.

    ``tie``: ``value`` was exactly halfway; ``carry``: rounding moved up to the next power of 10.
    """
    exact = Fraction(value)
    exponent = 0
    while exact >= 10 ** (exponent + 1):
        exponent += 1
    while exact < 10**exponent:
        exponent -= 1
    scaled = exact / Fraction(10) ** (exponent - digits + 1)
    count = math.floor(scaled + Fraction(1, 2))
    carry = count == 10**digits  # 999.5 -> 1000 at three digits: the exponent moves on
    if carry:
        exponent += 1
        count //= 10
    step = max(-8, min(8, exponent // 3))
    text = format(Decimal(count).scaleb(exponent - digits + 1 - 3 * step), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Oracle(text + SI_PREFIXES[8 + step], scaled % 1 == Fraction(1, 2), carry)


def test_si_notation_is_exact_half_up_with_the_prefix_picked_after_rounding() -> None:
    rnd = random.Random(12)
    ties = carries = 0
    for _ in range(3000):
        value = rnd.choice([1, 10, 1e3, 1e6, 1e12, 1e25, 1e-3, 1e-9]) * rnd.random()
        if rnd.random() < 0.5:
            value = rnd.randrange(1, 100_000) / 2 ** rnd.randrange(0, 9)
        if rnd.random() < 0.2:
            value = 10 ** rnd.randrange(-9, 9) * (1 - rnd.random() / 10 ** rnd.randrange(1, 6))
        digits = rnd.randrange(1, 9)
        expected = si_oracle(value, digits)
        assert format_value(value, f".{digits}s") == expected.text
        assert format_value(-value, f".{digits}s") == "-" + expected.text
        ties += expected.tie
        carries += expected.carry
    assert ties > 50
    assert carries > 100


NON_FINITE = [
    Fmt(float("inf"), ",.2f", "inf"),
    Fmt(float("-inf"), ".2f", "-inf"),
    Fmt(float("nan"), ".2f", "nan"),
    Fmt(float("inf"), "d", "inf"),
    Fmt(float("inf"), ".2s", "inf"),
    Fmt(float("nan"), ".2s", "nan"),
    Fmt(float("inf"), ".1%", "inf%"),
    Fmt(1.7e308, ".0%", "inf%"),  # the percent multiplication overflows
    Fmt(float("inf"), "", "inf"),
]


@pytest.mark.parametrize("case", NON_FINITE, ids=lambda case: f"{case.value}|{case.spec}")
def test_non_finite_numbers_are_written_as_python_writes_them(case: Fmt) -> None:
    assert format_value(case.value, case.spec) == case.expected


def test_the_largest_and_smallest_floats_do_not_overflow_the_exact_arithmetic() -> None:
    assert format_value(1e30, ",.0f") == format(1e30, ",.0f")
    assert format_value(1.7976931348623157e308, ".21f") == format(1.7976931348623157e308, ".21f")
    assert format_value(5e-324, ".21f") == "0." + "0" * 21
    assert format_value(1.7976931348623157e308, ".3s").endswith("Y")
    assert format_value(5e-324, ".3s").startswith("0.")
    assert format_value(5e-324, ".3s").endswith("y")


def test_zero_has_no_digits_and_no_prefix() -> None:
    assert format_value(0.0, ".3s") == "0"
    assert format_value(0.0, ".0f") == "0"
    assert format_value(0.0, ".2f") == "0.00"
    assert format_value(0.0, ".1%") == "0.0%"


class Clamp(NamedTuple):
    asked: str
    used: int


PRECISIONS = [
    Clamp("19", 19),
    Clamp("20", 20),
    Clamp("21", MAX_PRECISION),
    Clamp("22", MAX_PRECISION),
    Clamp("99999999999999999999", MAX_PRECISION),
]


@pytest.mark.parametrize("case", PRECISIONS)
def test_precision_is_capped_at_21(case: Clamp) -> None:
    assert MAX_PRECISION == 21
    assert parse_spec(f".{case.asked}f").precision == case.used
    assert len(format_value(1.0, f".{case.asked}f")) == 2 + case.used
    assert len(format_value(1.0, f".{case.asked}%")) == 5 + case.used  # "100." + digits + "%"


WIDTHS = [
    Clamp("99", 99),
    Clamp("100", MAX_WIDTH),
    Clamp("101", MAX_WIDTH),
    Clamp("9999999999999999999999", MAX_WIDTH),
]


@pytest.mark.parametrize("case", WIDTHS)
def test_width_is_capped_at_100(case: Clamp) -> None:
    assert MAX_WIDTH == 100
    assert parse_spec(case.asked).width == case.used
    assert len(format_value(5.0, f"{case.asked}.1f")) == case.used
    assert len(format_value(5.0, f"0{case.asked}.1f")) == case.used
