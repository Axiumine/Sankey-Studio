# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Number and name cleaning shared by every text format.

A row problem is reported with ``RowError``; its message says WHAT is wrong, never the cell
content (error messages reach API clients and must not echo file contents).
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

from sankey_studio.models import NAME_MAX

#: Longest numeric text parsed (guards the regexes and ``float``).
MAX_NUMBER_CHARS = 64
VALUE_MESSAGE = "value must be a positive number"

_PLAIN_NUMBER_RE = re.compile(r"[+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_THOUSANDS_RE = re.compile(r"[+]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?")


class RowError(ValueError):
    """A row cannot become a link. The message names the problem, never the content."""


class Row(NamedTuple):
    """One entry as a format parser saw it, before cleaning. ``None`` = absent."""

    line: int
    source: object
    target: object
    value: object
    category: object


def _positive(number: float) -> float | None:
    return number if math.isfinite(number) and number > 0 else None


def _thousands_are_unambiguous(text: str) -> bool:
    """``1,234.5`` and ``1,234,567`` are thousands; a lone ``1,234`` could be 1.234."""
    return text.count(",") >= 2 or "." in text  # noqa: PLR2004 - two groups cannot be a decimal comma


def parse_value(text: str) -> float | None:
    """A positive finite number from ``text`` or ``None``.

    Plain decimals (``12``, ``.5``, ``1e3``, ``+7``) and thousands separators when they cannot be
    a decimal comma (``1,234.5``, ``1,234,567``). Underscores, non-ASCII digits, ``nan``, ``inf``,
    signs other than ``+``, zero and negatives are refused.
    """
    cleaned = text.strip()
    if not cleaned or len(cleaned) > MAX_NUMBER_CHARS:
        return None
    if _THOUSANDS_RE.fullmatch(cleaned):
        if not _thousands_are_unambiguous(cleaned):
            return None
        cleaned = cleaned.replace(",", "")
    elif not _PLAIN_NUMBER_RE.fullmatch(cleaned):
        return None
    return _positive(float(cleaned))


def clean_name(raw: object, role: str) -> str:
    """A stripped node name (``role`` is 'source' or 'target', used in messages)."""
    if raw is None:
        raise RowError(f"{role} is missing")
    if isinstance(raw, bool) or not isinstance(raw, str | int):
        raise RowError(f"{role} is not text")
    text = str(raw).strip()
    if not text:
        raise RowError(f"{role} is empty")
    if len(text) > NAME_MAX:
        raise RowError(f"{role} is longer than {NAME_MAX} characters")
    if "\0" in text:
        raise RowError(f"{role} contains a NUL character")
    try:
        text.encode()
    except UnicodeEncodeError:
        raise RowError(f"{role} contains an invalid character") from None
    return text


def _as_number(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        return parse_value(raw)
    if isinstance(raw, int | float):
        try:
            return _positive(float(raw))
        except OverflowError:  # an int beyond the float range
            return None
    return None


def clean_value(raw: object) -> float:
    """A positive finite float from a cell or a JSON value."""
    if raw is None:
        raise RowError("value is missing")
    if isinstance(raw, str) and not raw.strip():
        raise RowError("value is empty")
    number = _as_number(raw)
    if number is None:
        raise RowError(VALUE_MESSAGE)
    return number
