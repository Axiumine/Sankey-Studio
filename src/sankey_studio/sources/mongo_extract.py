"""Dotted-path extraction and name/value coercion for MongoDB documents.

Pure functions, no driver calls: ``mongo_source`` streams documents through ``extract_row``.
Every rejection reason is a fixed phrase that names the configured field path (validated by
``MongoSource``): it never echoes document data, so warnings are safe to show.

Names accept str, int, finite float/``Decimal``/``Decimal128``, ObjectId, UUID and
datetime/date (stringified). A UUID that the driver left undecoded (``Binary`` subtype 4, which is
what a client without ``uuidRepresentation`` returns) counts as a UUID. ``bool``, lists,
documents, other bytes and every other driver type are rejected, as are control characters.
Values accept int, float, ``Decimal``/``Decimal128`` and plain numeric strings; they must be
finite and greater than zero.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from bson import Code, Decimal128, ObjectId
from bson.binary import Binary

from sankey_studio.models import NAME_MAX

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.models import MongoSource

#: A path segment that is absent from the document (``None`` is a real, null value).
MISSING: Final[object] = object()
#: Longest numeric string accepted as a value (``float()`` is only called on short text).
MAX_NUMERIC_CHARS = 64
#: Plain decimal notation only: no underscores, no ``nan``/``inf``, ASCII digits, one pass.
_NUMERIC_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
#: Control characters (Cc) and lone surrogates: not usable in a node name.
_UNSAFE_NAME_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_NAME_TYPES = (str, int, float, Decimal, Decimal128, ObjectId, UUID, date)
_NUMBER_TYPES = (int, float, Decimal, Decimal128, str)
#: Subclasses of an allowed type that are not names (``bool`` is an ``int``, ``Code`` a ``str``).
_NOT_VALUES = (bool, Code)


class FieldRejectedError(ValueError):
    """A field of one document cannot be used. The message is a fixed phrase, safe to show."""


# --------------------------------------------------------------------------- paths


def get_path(doc: Mapping[str, Any], path: str) -> object:
    """Follow a dotted ``path`` through nested documents; ``MISSING`` when any step is absent.

    Arrays are not traversed (``a.0`` is a key lookup): a list on the way is "missing".
    """
    node: object = doc
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return MISSING
        node = node[part]
    return node


@dataclass(frozen=True, slots=True)
class FieldMap:
    """The configured field paths of a Mongo source."""

    source: str
    target: str
    value: str | None
    category: str | None

    @classmethod
    def from_spec(cls, spec: MongoSource) -> FieldMap:
        return cls(spec.source_field, spec.target_field, spec.value_field, spec.category_field)

    def projection(self) -> dict[str, int]:
        """Server-side projection of just the needed fields.

        A path that lies below another needed path is dropped (MongoDB refuses a path collision
        such as ``a`` and ``a.b``), and ``_id`` is excluded unless a field is read from it.
        """
        paths = {p for p in (self.source, self.target, self.value, self.category) if p is not None}
        kept = sorted(p for p in paths if not any(p.startswith(f"{q}.") for q in paths))
        projection = dict.fromkeys(kept, 1)
        if not any(p == "_id" or p.startswith("_id.") for p in kept):
            projection["_id"] = 0
        return projection


# --------------------------------------------------------------------------- names


def uuid_from_binary(value: object) -> object:
    """``value``, except that a BSON UUID (``Binary`` subtype 4) becomes a ``uuid.UUID``.

    The driver decodes a UUID as ``Binary`` unless the client sets ``uuidRepresentation``. Legacy
    subtype 3 stays ``Binary`` (its byte order is ambiguous), and so does a subtype 4 value that
    is not 16 bytes long.
    """
    if isinstance(value, Binary):
        try:
            return value.as_uuid()  # standard representation: subtype 4 only, 16 bytes
        except ValueError:  # another subtype, or not 16 bytes
            return value
    return value


def _to_decimal(value: Decimal128) -> Decimal:
    try:
        return value.to_decimal()
    except ArithmeticError:
        raise FieldRejectedError("is not a finite number") from None


def _is_finite(number: object) -> bool:
    if isinstance(number, Decimal):
        return number.is_finite()
    if isinstance(number, float):
        return math.isfinite(number)
    return True


def _scalar_text(value: object) -> str:
    """``str()`` of an allow-listed scalar; ``FieldRejectedError`` for anything else."""
    if isinstance(value, _NOT_VALUES) or not isinstance(value, _NAME_TYPES):
        raise FieldRejectedError("is not a single text or number value")
    number: object = _to_decimal(value) if isinstance(value, Decimal128) else value
    if not _is_finite(number):
        raise FieldRejectedError("is not a finite number")
    try:
        # `number` is an allow-listed scalar; `object` is only its declared type.
        # noinspection PyStringConversionWithoutDunderMethod
        return str(number)
    except ValueError:  # an int with more digits than Python will print
        raise FieldRejectedError("is a number with too many digits") from None


def coerce_name(value: object) -> str:
    """The trimmed node name for ``value``, or ``FieldRejectedError`` with the reason."""
    if value is MISSING:
        raise FieldRejectedError("is missing")
    if value is None:
        raise FieldRejectedError("is null")
    text = _scalar_text(uuid_from_binary(value)).strip()
    if not text:
        raise FieldRejectedError("is empty")
    if len(text) > NAME_MAX:
        raise FieldRejectedError(f"is longer than {NAME_MAX} characters")
    if _UNSAFE_NAME_RE.search(text):
        raise FieldRejectedError("contains control characters")
    return text


# --------------------------------------------------------------------------- values


def _text_to_float(text: str) -> float:
    stripped = text.strip()
    if len(stripped) > MAX_NUMERIC_CHARS or _NUMERIC_RE.match(stripped) is None:
        raise FieldRejectedError("is not a number")
    return float(stripped)


def _to_float(value: object) -> float:
    if isinstance(value, _NOT_VALUES) or not isinstance(value, _NUMBER_TYPES):
        raise FieldRejectedError("is not a number")
    if isinstance(value, str):
        return _text_to_float(value)
    number = _to_decimal(value) if isinstance(value, Decimal128) else value
    if not _is_finite(number):
        raise FieldRejectedError("is not a finite number")
    try:
        return float(number)
    except OverflowError:  # an int beyond the float range
        raise FieldRejectedError("is out of range") from None


def coerce_value(value: object) -> tuple[float, bool]:
    """``(value, was_text)``: a finite number greater than zero, or ``FieldRejectedError``."""
    if value is MISSING:
        raise FieldRejectedError("is missing")
    if value is None:
        raise FieldRejectedError("is null")
    number = _to_float(value)
    if not math.isfinite(number):
        raise FieldRejectedError("is not a finite number")
    if number <= 0:
        raise FieldRejectedError("is not greater than zero")
    return number, isinstance(value, str)


# --------------------------------------------------------------------------- rows


@dataclass(frozen=True, slots=True)
class RowParts:
    """One document, validated. ``category`` is the raw field (``CategoryCleaner`` decides)."""

    source: str
    target: str
    value: float
    category: object
    text_value: bool


def _read[T](doc: Mapping[str, Any], label: str, path: str, coerce: Callable[[object], T]) -> T:
    try:
        return coerce(get_path(doc, path))
    except FieldRejectedError as exc:
        raise FieldRejectedError(f"{label} field '{path}' {exc}") from None


def _read_value(doc: Mapping[str, Any], path: str | None) -> tuple[float, bool]:
    if path is None:
        return 1.0, False  # an event log: every document counts once
    return _read(doc, "value", path, coerce_value)


def extract_row(doc: Mapping[str, Any], fields: FieldMap) -> RowParts | str:
    """Validate one document: ``RowParts``, or the reason text (no document data in it)."""
    try:
        source = _read(doc, "source", fields.source, coerce_name)
        target = _read(doc, "target", fields.target, coerce_name)
        value, text_value = _read_value(doc, fields.value)
    except FieldRejectedError as exc:
        return str(exc)
    category = None if fields.category is None else uuid_from_binary(get_path(doc, fields.category))
    return RowParts(source, target, value, None if category is MISSING else category, text_value)
