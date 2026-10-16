# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Data-source contract. Concrete sources live in ``text.py`` and ``mongo_source.py``;
``sources/__init__.py`` exposes ``open_source``.

Sources are **streaming**: they yield ``(source, target, value, category)`` tuples one at a
time so a 200k-link file never exists as 200k pydantic objects. Row-level problems go to
``Diagnostics`` (skipped + warned) unless ``ctx.strict`` is set, in which case they raise
``SourceError`` (``SourceContext.row_problem`` does both).

CATEGORY TOLERANCE (the same rule in every source): categorising is optional, so the category
column/field never causes a row to be dropped. A missing, empty, non-scalar (bool, list, dict,
bytes), over-long (> ``CATEGORY_MAX``) or reserved (``Uncategorized``/``Other``) value yields
``None``; the row is kept. Scalars are stringified, normalised (``util.normalize_category``).
"Scalar" is an allow-list: str, int (also bson ``Int64``), float, FINITE ``Decimal`` / bson
``Decimal128``, ``ObjectId``, ``UUID``, ``datetime``/``date``. Every other driver type
(``Binary``, ``SON``, ``Regex``, ``DBRef``, ``Timestamp``, ``MinKey``, ``Code``, ...) is
non-scalar: its ``str()`` is a repr, not a name. Control characters and lone surrogates make a
value unusable too. Sources get this behaviour from ``CategoryCleaner`` and call ``finish()``
once at the end, which emits at most ONE aggregated warning. The only hard error is a *named*
``category_column`` / ``category_field`` that cannot exist (header without that column):
``SourceError``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from bson import Code, Decimal128, ObjectId

from sankey_studio.errors import SourceError
from sankey_studio.models import CATEGORY_MAX
from sankey_studio.util import is_reserved_category, normalize_category

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.models import AppSettings, RawLink
    from sankey_studio.mongo import MongoClients

MAX_WARNINGS = 50

#: Scalar types stringified as a category (bson ``Int64`` is an ``int``). An allow-list on purpose:
#: matching "any bson type" would turn ``Binary``/``SON``/``Regex`` reprs into category names.
_SCALARS = (str, int, float, Decimal, UUID, datetime, date, ObjectId, Decimal128)
#: Subclasses of an allowed type that are not names (``bool`` is an ``int``, ``Code`` is a ``str``).
_NOT_SCALARS = (bool, Code)


@dataclass(slots=True)
class Diagnostics:
    """Collects non-fatal problems. Caps the stored messages but keeps counting."""

    warnings: list[str] = field(default_factory=list)
    skipped: int = 0
    _overflow: int = 0

    def warn(self, message: str) -> None:
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)
        else:
            self._overflow += 1

    def skip(self, message: str) -> None:
        self.skipped += 1
        self.warn(message)

    def finish(self) -> list[str]:
        """Warnings plus a trailing '... and N more' line when the cap was hit."""
        if self._overflow:
            return [*self.warnings, f"... and {self._overflow} more warnings"]
        return list(self.warnings)


@dataclass(frozen=True, slots=True)
class SourceContext:
    """Everything a source may touch. Built per request by ``services``.

    ``sources_dir`` comes from ``BootstrapConfig.effective_sources_dir`` (never from settings).
    ``strict`` is wired by ``services.source_context(strict=draft.transform.strict)``.
    """

    settings: AppSettings
    sources_dir: Path
    mongo: MongoClients
    strict: bool = False

    def row_problem(self, diag: Diagnostics, message: str) -> None:
        """A bad row: raise ``SourceError`` when strict, else skip it with a warning."""
        if self.strict:
            raise SourceError(message)
        diag.skip(message)


class CategoryCleaner:
    """Applies the category tolerance rule and counts what it had to discard."""

    def __init__(self, diag: Diagnostics) -> None:
        self._diag = diag
        self._unusable = 0
        self._too_long = 0
        self._reserved = 0
        self._control = 0

    def clean(self, value: object) -> str | None:
        """Return the normalised category, or ``None`` (row stays, uncategorised)."""
        if value is None:
            return None
        text = self._stringify(value)
        if text is None:
            self._unusable += 1
            return None
        try:
            cleaned = normalize_category(text)
        except ValueError:
            self._control += 1
            return None
        return self._accept(cleaned)

    def _accept(self, cleaned: str) -> str | None:
        if not cleaned:
            return None
        if len(cleaned) > CATEGORY_MAX:
            self._too_long += 1
            return None
        if is_reserved_category(cleaned):
            self._reserved += 1
            return None
        return cleaned

    @staticmethod
    def _stringify(value: object) -> str | None:
        if isinstance(value, _NOT_SCALARS) or not isinstance(value, _SCALARS):
            return None  # list, dict, bytes, set, bson containers, arbitrary objects
        number: object = value
        if isinstance(value, Decimal128):
            try:
                number = value.to_decimal()
            except ArithmeticError:
                return None
        if isinstance(number, Decimal):
            if not number.is_finite():  # math.isfinite raises on a signaling NaN
                return None
        elif isinstance(number, float) and not math.isfinite(number):
            return None
        try:
            # `number` is an allow-listed scalar; `object` is only its declared type.
            # noinspection PyStringConversionWithoutDunderMethod
            return str(number)
        except ValueError:  # an int with more digits than Python will print
            return None

    def finish(self) -> None:
        """Emit one aggregated warning (call once, after the last row)."""
        parts = [
            f"{count} {label}"
            for count, label in (
                (self._unusable, "not a single text/number value"),
                (self._too_long, f"longer than {CATEGORY_MAX} characters"),
                (self._control, "containing control characters"),
                (self._reserved, "using the reserved names Uncategorized/Other"),
            )
            if count
        ]
        if parts:
            self._diag.warn("Categories ignored (entries kept uncategorised): " + "; ".join(parts))


class DataSource(Protocol):  # pragma: no mutate block - interface only, never executed
    def iter_links(self, diag: Diagnostics) -> Iterator[RawLink]:
        """Yield entries. Values are finite and > 0; names are non-empty and stripped;
        category is ``None`` or a non-empty normalised string (<= CATEGORY_MAX chars, never a
        reserved name). Open files with ``with`` inside the generator (an abandoned stream must
        not leak a descriptor), and call ``CategoryCleaner.finish()`` before returning."""
        ...
