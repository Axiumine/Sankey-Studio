# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""JSON-safe, size-bounded copies of MongoDB documents for the editor's sample view.

The result goes to the browser, so it must be plain JSON and small whatever the document holds:
ObjectId/UUID/Decimal128 become text (also a UUID the driver left as ``Binary`` subtype 4),
datetimes ISO-8601, other bytes ``"<bytes N>"``, every other driver type ``"<TypeName>"``;
strings, containers, nesting depth and the total number of values are capped (an overflow shows as
``"..."`` or as a "N more" marker).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from itertools import islice
from typing import TYPE_CHECKING, Any
from uuid import UUID

from bson import Decimal128, ObjectId

from sankey_studio.sources.mongo_extract import uuid_from_binary

if TYPE_CHECKING:
    from collections.abc import Sequence

SAMPLE_MAX_DEPTH = 4  # nesting levels kept below the document
SAMPLE_MAX_ITEMS = 20  # keys / array items kept per container
SAMPLE_MAX_TEXT = 200  # characters kept per string or key
SAMPLE_MAX_NODES = 2_000  # values kept across one sanitizer (one sample call)
#: Largest integer a browser parses exactly (``Number.MAX_SAFE_INTEGER``); larger ones become text.
MAX_SAFE_INT = 2**53 - 1
ELLIPSIS = "..."
_INT64_BITS = 64
_TEXT_TYPES = (ObjectId, UUID, Decimal, Decimal128)


def _clip(text: str) -> str:
    """A plain ``str`` of at most ``SAMPLE_MAX_TEXT`` characters (plus the ellipsis)."""
    plain = str(text)  # a bson.Code is a str subclass; the browser gets a plain string
    return plain if len(plain) <= SAMPLE_MAX_TEXT else plain[:SAMPLE_MAX_TEXT] + ELLIPSIS


def _int(value: int) -> int | str:
    if abs(value) <= MAX_SAFE_INT:
        return int(value)  # a bson.Int64 is an int subclass; the browser gets a plain number
    bits = value.bit_length()
    return str(value) if bits <= _INT64_BITS else f"<int, {bits} bits>"


def _number(value: float) -> object:
    if isinstance(value, int):
        return _int(value)
    return value if math.isfinite(value) else str(value)


def _special(value: object) -> object:
    """Dates, binary data, driver text types; anything unknown becomes ``"<TypeName>"``."""
    if isinstance(value, date):  # datetime is a date
        return value.isoformat()
    uuid_value = uuid_from_binary(value)  # an undecoded UUID is text, not "<bytes 16>"
    if isinstance(uuid_value, bytes | bytearray):  # includes bson.Binary
        return f"<bytes {len(uuid_value)}>"
    if isinstance(uuid_value, _TEXT_TYPES):
        return _clip(str(uuid_value))
    return f"<{type(value).__name__}>"


def _scalar(value: object) -> object:
    """A JSON primitive for a value that is not a container."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, int | float):
        return _number(value)
    return _special(value)


class JsonSanitizer:
    """Converts documents one at a time; the value budget is shared by all of them."""

    def __init__(self) -> None:
        self._nodes = 0

    def document(self, doc: Mapping[str, Any]) -> dict[str, object]:
        """``doc`` as a plain ``dict`` (always a dict, even when the budget is spent)."""
        return self._mapping(doc, 0)

    def _convert(self, value: object, depth: int) -> object:
        self._nodes += 1
        if self._nodes > SAMPLE_MAX_NODES:
            return ELLIPSIS
        if isinstance(value, Mapping):
            return (
                self._mapping(value, depth)
                if depth < SAMPLE_MAX_DEPTH
                else f"<object {len(value)}>"
            )
        if isinstance(value, list | tuple):
            return (
                self._sequence(value, depth)
                if depth < SAMPLE_MAX_DEPTH
                else f"<array {len(value)}>"
            )
        return _scalar(value)

    def _mapping(self, value: Mapping[Any, Any], depth: int) -> dict[str, object]:
        kept = islice(value.items(), SAMPLE_MAX_ITEMS)
        out = {_clip(str(key)): self._convert(item, depth + 1) for key, item in kept}
        extra = len(value) - SAMPLE_MAX_ITEMS
        if extra > 0:
            out[ELLIPSIS] = f"{extra} more keys"
        return out

    def _sequence(self, value: Sequence[object], depth: int) -> list[object]:
        out = [self._convert(item, depth + 1) for item in value[:SAMPLE_MAX_ITEMS]]
        extra = len(value) - SAMPLE_MAX_ITEMS
        if extra > 0:
            out.append(f"{ELLIPSIS} {extra} more")
        return out
