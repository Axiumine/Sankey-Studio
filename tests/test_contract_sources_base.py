"""Contract tests for ``sources.base``: the category tolerance rule and strict/lenient rows."""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from bson import (
    Binary,
    Code,
    DBRef,
    Decimal128,
    Int64,
    MaxKey,
    MinKey,
    ObjectId,
    Regex,
    Timestamp,
)
from bson.son import SON

from sankey_studio.errors import SourceError
from sankey_studio.models import CATEGORY_MAX, ManualSource, TextSource
from sankey_studio.sources import open_source
from sankey_studio.sources.base import CategoryCleaner, Diagnostics
from sankey_studio.sources.manual import ManualDataSource

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.sources.base import SourceContext


def _clean(value: object) -> tuple[str | None, list[str]]:
    diag = Diagnostics()
    cleaner = CategoryCleaner(diag)
    out = cleaner.clean(value)
    cleaner.finish()
    return out, diag.finish()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Food", "Food"),
        ("  Fast   Food ", "Fast Food"),
        ("Café", "Café"),
        (7, "7"),
        (2.5, "2.5"),
        (Decimal("1.5"), "1.5"),
        (Decimal128("3.25"), "3.25"),
        (Int64(2**40), str(2**40)),
        (Decimal("1E+5"), "1E+5"),
        (ObjectId("0123456789abcdef01234567"), "0123456789abcdef01234567"),
        (uuid.UUID(int=5), "00000000-0000-0000-0000-000000000005"),
        (dt.datetime(2025, 1, 2, tzinfo=dt.UTC), "2025-01-02 00:00:00+00:00"),
        (dt.date(2025, 1, 2), "2025-01-02"),
    ],
)
def test_scalar_categories_are_stringified_and_normalised(value: object, expected: str) -> None:
    out, warnings = _clean(value)
    assert out == expected
    assert warnings == []


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_missing_or_empty_category_is_none_without_a_warning(value: object) -> None:
    assert _clean(value) == (None, [])


@pytest.mark.parametrize(
    "value",
    [True, False, ["a"], {"a": 1}, b"bytes", {"a"}, float("nan"), float("inf"), object()],
)
def test_non_scalar_category_is_none_with_a_warning(value: object) -> None:
    out, warnings = _clean(value)
    assert out is None
    assert len(warnings) == 1
    assert "kept uncategorised" in warnings[0]


#: Driver types whose ``str()`` is a repr ("SON([...])", "b'x'"), plus values that are not a name.
UNUSABLE_CATEGORIES = [
    Binary(b"x"),
    SON([("a", 1)]),
    Regex("a"),
    DBRef("c", 1),
    MinKey(),
    MaxKey(),
    Timestamp(1, 1),
    Code("x"),
    Decimal("NaN"),
    Decimal("sNaN"),
    Decimal("Infinity"),
    Decimal("-Infinity"),
    Decimal128("NaN"),
    Decimal128("sNaN"),
    Decimal128("-Infinity"),
    float("-inf"),
    10**5000,  # str() refuses to print this many digits
    (1, 2),
    bytearray(b"x"),
    range(3),
]


@pytest.mark.parametrize("value", UNUSABLE_CATEGORIES, ids=lambda v: type(v).__name__)
def test_driver_reprs_and_non_finite_numbers_are_not_categories(value: object) -> None:
    out, warnings = _clean(value)
    assert out is None
    assert len(warnings) == 1
    assert "not a single text/number value" in warnings[0]


@pytest.mark.parametrize(
    "value", ["\x00x", "a\x00", "a\x1bb", "\x7f", "a\x80b", "\ud800", "ok\x01"]
)
def test_control_characters_make_a_category_unusable(value: str) -> None:
    out, warnings = _clean(value)
    assert out is None
    assert len(warnings) == 1
    assert "control characters" in warnings[0]
    assert "\x00" not in warnings[0]  # the value itself is never echoed


def test_whitespace_controls_collapse_instead_of_rejecting() -> None:
    assert _clean("Fast\x0bFood\x1f") == ("Fast Food", [])


def test_length_is_checked_after_normalisation() -> None:
    """``U+0344`` has a two-character NFC form: 60 of them are 120 characters once normalised."""
    out, warnings = _clean("\u0344" * 60)
    assert out is None
    assert "longer than" in warnings[0]
    assert _clean("\u0344" * 50)[0] == "\u0308\u0301" * 50


def test_too_long_and_reserved_categories_are_none() -> None:
    assert _clean("x" * (CATEGORY_MAX + 1))[0] is None
    assert _clean("x" * CATEGORY_MAX)[0] == "x" * CATEGORY_MAX
    for name in ("Uncategorized", "other", " OTHER "):
        out, warnings = _clean(name)
        assert out is None
        assert "reserved" in warnings[0]


def test_many_bad_categories_produce_exactly_one_warning() -> None:
    diag = Diagnostics()
    cleaner = CategoryCleaner(diag)
    for i in range(1000):
        cleaner.clean([i])
        cleaner.clean("Other")
        cleaner.clean("y" * 500)
    cleaner.finish()
    assert len(diag.warnings) == 1
    assert "1000" in diag.warnings[0]
    assert diag.skipped == 0  # rows are never skipped because of their category


def test_all_rows_uncategorised_is_silent() -> None:
    diag = Diagnostics()
    cleaner = CategoryCleaner(diag)
    assert [cleaner.clean(None) for _ in range(5)] == [None] * 5
    cleaner.finish()
    assert diag.finish() == []


def test_diagnostics_caps_messages_but_keeps_counting() -> None:
    diag = Diagnostics()
    for i in range(80):
        diag.skip(f"row {i}")
    assert diag.skipped == 80
    finished = diag.finish()
    assert len(finished) == 51
    assert finished[-1] == "... and 30 more warnings"


def test_row_problem_skips_when_lenient_and_raises_when_strict(
    make_source_ctx: Callable[..., SourceContext],
) -> None:
    lenient = make_source_ctx()
    diag = Diagnostics()
    lenient.row_problem(diag, "a.csv:3: bad value")
    assert diag.skipped == 1
    assert diag.warnings == ["a.csv:3: bad value"]
    with pytest.raises(SourceError, match=r"a\.csv:4"):
        make_source_ctx(strict=True).row_problem(Diagnostics(), "a.csv:4: bad value")


def test_manual_source_yields_none_for_missing_category() -> None:
    spec = ManualSource.model_validate(
        {
            "links": [
                {"source": "a", "target": "b", "value": 1},
                {"source": "a", "target": "c", "value": 2, "category": "  "},
            ]
        }
    )
    rows = list(ManualDataSource(spec).iter_links(Diagnostics()))
    assert rows == [("a", "b", 1.0, None), ("a", "c", 2.0, None)]


def test_open_source_dispatches_and_imports_lazily(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    manual = open_source(ManualSource(), source_ctx)
    assert isinstance(manual, ManualDataSource)
    text = open_source(TextSource(content="a,b,1"), source_ctx)
    assert type(text).__name__ == "TextDataSource"
    # a broken sibling module must not break the manual path
    monkeypatch.setitem(sys.modules, "sankey_studio.sources.mongo_source", None)
    assert isinstance(open_source(ManualSource(), source_ctx), ManualDataSource)


def test_cleaner_accepts_any_object_type_signature() -> None:
    value: Any = {"nested": 1}
    assert _clean(value)[0] is None
