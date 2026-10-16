# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""A small d3-format subset for text that Plotly cannot format itself (labels, centre total).

``StyleSpec.value_format`` is validated to the characters ``-+ ,.~$%a-zA-Z0-9`` (no fill or
align). Supported: ``[sign][$][0][width][,][.precision][~][type]`` with the types ``f``, ``d``,
``%``, ``s`` (SI prefixes, significant digits) and ``g``; every other type letter, or none,
formats like ``g`` with 12 significant digits (zeros trimmed).

Rounding of ``f``, ``d``, ``%`` and ``s`` matches JavaScript (``toFixed``/``toExponential``, so
d3): the EXACT binary value of the float is rounded and an exact tie goes up, away from zero
because the sign is split off first (``0.5`` -> ``1``, ``2.5`` -> ``3``; Python itself rounds
ties to even). ``s`` picks the SI prefix AFTER rounding (``999999.5`` -> ``1M``, not ``1000k``).
``g`` keeps Python's own rounding. Precision is capped at 21 (d3 caps it at 20/21) and width at
100, so a hostile format cannot ask for a gigabyte of padding.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Final

SPEC_RE: Final = re.compile(
    r"(?P<sign>[-+ ])?(?P<symbol>[$#])?(?P<zero>0)?(?P<width>[0-9]+)?(?P<comma>,)?"
    r"(?:\.(?P<precision>[0-9]+))?(?P<trim>~)?(?P<type>[a-zA-Z%])?\Z"
)
#: SI prefixes from 10**-24 to 10**24 in steps of 10**3 (``u`` stands for micro); index 8 is "".
SI_PREFIXES: Final = (
    "y",
    "z",
    "a",
    "f",
    "p",
    "n",
    "u",
    "m",
    "",
    "k",
    "M",
    "G",
    "T",
    "P",
    "E",
    "Z",
    "Y",
)
TRAILING_ZEROS: Final = re.compile(r"0+\Z")
DANGLING_POINT: Final = re.compile(r"\.\Z")
SI_ORIGIN: Final = 8
FIXED_DEFAULT_PRECISION: Final = 6
GENERAL_DEFAULT_PRECISION: Final = 12
MAX_PRECISION: Final = 21
MAX_WIDTH: Final = 100
#: Exact rounding of a float: up to 309 integer digits plus ``MAX_PRECISION`` decimals fit easily.
HALF_UP: Final = Context(prec=400, rounding=ROUND_HALF_UP)
#: ``quantize`` reads only the exponent of its unit; ``ONE.scaleb(e)`` is the unit ``1E<e>``.
ONE: Final = Decimal(1)


@dataclass(frozen=True, slots=True)
class Spec:
    """A parsed format specification."""

    sign: str = "-"
    symbol: str = ""
    zero: bool = False
    width: int = 0
    comma: bool = False
    precision: int | None = None
    trim: bool = False
    kind: str = ""


#: Used when the spec does not parse: ``,.2~f``.
FALLBACK: Final = Spec(comma=True, precision=2, trim=True, kind="f")


def parse_spec(text: str) -> Spec:
    """Parse ``text``; anything that does not parse is read as ``,.2~f``."""
    match = SPEC_RE.match(text)
    if match is None:
        return FALLBACK
    precision = match["precision"]
    return Spec(
        sign=match["sign"] or "-",
        symbol="$" if match["symbol"] == "$" else "",
        zero=match["zero"] is not None,
        width=min(int(match["width"] or 0), MAX_WIDTH),
        comma=match["comma"] is not None,
        precision=None if precision is None else min(int(precision), MAX_PRECISION),
        trim=match["trim"] is not None,
        kind=match["type"] or "",
    )


def _trim(digits: str) -> str:
    """Drop insignificant trailing zeros after a decimal point (``1,500.50`` -> ``1,500.5``)."""
    if "." not in digits:
        return digits
    return DANGLING_POINT.sub("", TRAILING_ZEROS.sub("", digits))


def _fixed(value: float, places: int, comma: str) -> str:
    """``value`` (not negative) to ``places`` decimals; an exact tie rounds up like ``toFixed``."""
    if not math.isfinite(value):
        return str(value)
    rounded = Decimal(value).quantize(ONE.scaleb(-places, HALF_UP), context=HALF_UP)
    return format(rounded, f"{comma}.{places}f")


def _si(value: float, precision: int) -> tuple[str, str]:
    """``1234`` with precision 3 gives ``("1.23", "k")``: round first, then pick the prefix."""
    if not math.isfinite(value):
        return str(value), ""
    if value == 0:
        return "0", ""
    exact = Decimal(value)
    digits = max(precision, 1)
    unit = ONE.scaleb(exact.adjusted() - digits + 1, HALF_UP)
    rounded = exact.quantize(unit, context=HALF_UP)  # 999999.5 -> 1.00E+6: the exponent moved on
    step = max(-SI_ORIGIN, min(SI_ORIGIN, rounded.adjusted() // 3))
    scaled = rounded.scaleb(-3 * step, HALF_UP)
    return _trim(f"{scaled:f}"), SI_PREFIXES[SI_ORIGIN + step]


def _number(value: float, spec: Spec) -> tuple[str, str]:
    """Magnitude text and unit suffix (``%`` or an SI prefix) of a non-negative ``value``."""
    comma = "," if spec.comma else ""
    fixed = FIXED_DEFAULT_PRECISION if spec.precision is None else spec.precision
    if spec.kind == "d":
        return _fixed(value, 0, comma), ""
    if spec.kind == "f":
        return _fixed(value, fixed, comma), ""
    if spec.kind == "%":
        return _fixed(value * 100, fixed, comma), "%"
    if spec.kind == "s":
        return _si(value, fixed)
    general = GENERAL_DEFAULT_PRECISION if spec.precision is None else max(spec.precision, 1)
    return format(value, f"{comma}.{general}g"), ""


def _sign(value: float, spec: Spec) -> str:
    """``-`` for negatives; positives show nothing, ``+`` or a space as the spec says."""
    if value < 0:
        return "-"
    return "" if spec.sign == "-" else spec.sign


def format_value(value: float, spec: str) -> str:
    """``value`` formatted with the d3-format subset ``spec`` (see the module docstring)."""
    parsed = parse_spec(spec)
    digits, unit = _number(abs(value), parsed)
    if parsed.trim:
        digits = _trim(digits)
    prefix = _sign(value, parsed) + parsed.symbol
    padding = max(parsed.width - len(prefix) - len(digits) - len(unit), 0)
    if parsed.zero:
        return prefix + "0" * padding + digits + unit
    return " " * padding + prefix + digits + unit
