# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``format_value`` rounds with its own decimal context, whatever the caller left installed.

Rounding, scaling and exponents are exact only under the module's context (400 digits, half up).
Python's ambient context is thread-global state: if a library installs a small, trapping one,
a format that leaned on it would raise or round differently. Every case runs under such a
context and has to give the answer printed here.
"""

from __future__ import annotations

import decimal
from decimal import ROUND_DOWN, Context
from typing import NamedTuple

import pytest

from sankey_studio.render.numfmt import format_value
from tests.sources.idtools import safe_id

#: Two digits, rounding down, exponents within +-3, and every signal raises.
HOSTILE = Context(
    prec=2,
    rounding=ROUND_DOWN,
    Emin=-3,
    Emax=3,
    traps=[
        decimal.InvalidOperation,
        decimal.DivisionByZero,
        decimal.Overflow,
        decimal.Underflow,
        decimal.Inexact,
        decimal.Rounded,
        decimal.Clamped,
        decimal.Subnormal,
    ],
)


class Fmt(NamedTuple):
    value: float
    spec: str
    expected: str


FORMATS = [
    Fmt(0.125, ".2f", "0.13"),
    Fmt(0.125, ".2~f", "0.13"),
    Fmt(1e-10, ".12f", "0.000000000100"),
    Fmt(123456789.5, ",.0f", "123,456,790"),
    Fmt(0.005, ".1%", "0.5%"),
    Fmt(1234567.0, ".3s", "1.23M"),
    Fmt(0.000123, ".3s", "123u"),
    Fmt(1.5e24, ".3s", "1.5Y"),
    Fmt(1e30, ".3s", "1000000Y"),
    Fmt(-2.5, ".0f", "-3"),
]


@pytest.mark.parametrize("case", FORMATS, ids=[safe_id(f"{f.value}-{f.spec}") for f in FORMATS])
def test_an_ambient_decimal_context_changes_nothing(case: Fmt) -> None:
    assert format_value(case.value, case.spec) == case.expected
    with decimal.localcontext(HOSTILE):
        assert format_value(case.value, case.spec) == case.expected
