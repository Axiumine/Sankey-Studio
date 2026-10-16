# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``sources``: exact category warnings, manual rows and the ``open_source`` dispatch."""

from __future__ import annotations

import decimal
from typing import TYPE_CHECKING, Any

import pytest
from bson import Decimal128

from sankey_studio.models import CATEGORY_MAX, ManualSource, MongoSource, TextSource
from sankey_studio.sources import open_source
from sankey_studio.sources.base import MAX_WARNINGS, CategoryCleaner, Diagnostics
from sankey_studio.sources.manual import ManualDataSource

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext

PREFIX = "Categories ignored (entries kept uncategorised): "
UNUSABLE = "not a single text/number value"
TOO_LONG = f"longer than {CATEGORY_MAX} characters"
CONTROL = "containing control characters"
RESERVED = "using the reserved names Uncategorized/Other"

BAD_BY_KIND: dict[str, list[object]] = {
    UNUSABLE: [[1], {"a": 1}, True, float("nan")],
    TOO_LONG: ["x" * (CATEGORY_MAX + 1), "y" * 500],
    CONTROL: ["a\x00b", "a\x1bb"],
    RESERVED: ["Other", "uncategorized", " OTHER "],
}


def run(values: list[object]) -> tuple[list[str | None], Diagnostics]:
    diag = Diagnostics()
    cleaner = CategoryCleaner(diag)
    out = [cleaner.clean(v) for v in values]
    cleaner.finish()
    return out, diag


@pytest.mark.parametrize("kind", sorted(BAD_BY_KIND))
@pytest.mark.parametrize("count", [1, 2])
def test_each_kind_is_counted_and_named_alone(kind: str, count: int) -> None:
    values = BAD_BY_KIND[kind][:count]
    out, diag = run(values)
    assert out == [None] * len(values)
    assert diag.warnings == [f"{PREFIX}{len(values)} {kind}"]
    assert diag.skipped == 0


def test_all_kinds_are_listed_in_a_fixed_order_with_their_counts() -> None:
    values = [
        *BAD_BY_KIND[RESERVED][:2],
        *BAD_BY_KIND[CONTROL],
        *BAD_BY_KIND[TOO_LONG],
        *BAD_BY_KIND[UNUSABLE][:2],
        "fine",
    ]
    out, diag = run(values)
    assert out[-1] == "fine"
    assert diag.warnings == [f"{PREFIX}2 {UNUSABLE}; 2 {TOO_LONG}; 2 {CONTROL}; 2 {RESERVED}"]


def test_kinds_with_no_hits_are_left_out() -> None:
    _, diag = run(["Other", [1], "Other"])
    assert diag.warnings == [f"{PREFIX}1 {UNUSABLE}; 2 {RESERVED}"]


def test_counters_start_at_zero_and_each_kind_is_independent() -> None:
    _, diag = run(["a\x00", "Food", "Other"])
    assert diag.warnings == [f"{PREFIX}1 {CONTROL}; 1 {RESERVED}"]


def test_clean_values_never_warn() -> None:
    out, diag = run(["Food", 7, 1.5, "  spaced   out  ", "", "   ", None])
    assert out == ["Food", "7", "1.5", "spaced out", None, None, None]
    assert diag.warnings == []


def test_category_length_boundary_is_exact() -> None:
    assert run(["x" * CATEGORY_MAX])[0] == ["x" * CATEGORY_MAX]
    assert run(["x" * (CATEGORY_MAX + 1)])[0] == [None]


class _BrokenDecimal128(Decimal128):
    def to_decimal(self) -> decimal.Decimal:
        raise decimal.InvalidOperation


def test_a_decimal128_that_cannot_be_converted_is_unusable() -> None:
    out, diag = run([_BrokenDecimal128("1.5"), Decimal128("1.5"), Decimal128("NaN")])
    assert out == [None, "1.5", None]
    assert diag.warnings == [f"{PREFIX}2 {UNUSABLE}"]


def test_a_huge_integer_is_unusable_instead_of_raising() -> None:
    out, diag = run([10**5000, 10**30])
    assert out == [None, str(10**30)]
    assert diag.warnings == [f"{PREFIX}1 {UNUSABLE}"]


# --------------------------------------------------------------------------- diagnostics


def test_diagnostics_message_cap_is_exact() -> None:
    diag = Diagnostics()
    for i in range(MAX_WARNINGS):
        diag.warn(f"w{i}")
    assert diag.finish() == [f"w{i}" for i in range(MAX_WARNINGS)]
    diag.warn("one more")
    assert diag.finish()[-1] == "... and 1 more warnings"
    assert len(diag.finish()) == MAX_WARNINGS + 1
    diag.warn("and another")
    assert diag.finish()[-1] == "... and 2 more warnings"
    assert diag.warnings[-1] == f"w{MAX_WARNINGS - 1}"
    assert MAX_WARNINGS == 50


def test_finish_returns_a_copy_and_skip_counts() -> None:
    diag = Diagnostics()
    diag.skip("row 1")
    diag.skip("row 2")
    diag.warn("note")
    assert (diag.skipped, diag.warnings) == (2, ["row 1", "row 2", "note"])
    first = diag.finish()
    first.append("mutated")
    assert diag.finish() == ["row 1", "row 2", "note"]


# --------------------------------------------------------------------------- manual source


def test_manual_source_yields_values_and_categories_in_order() -> None:
    spec = ManualSource.model_validate(
        {
            "links": [
                {"source": "a", "target": "b", "value": 1.5, "category": " Food "},
                {"source": "b", "target": "c", "value": 2},
                {"source": "b", "target": "d", "value": 3, "category": ""},
                {"source": "b", "target": "e", "value": 4, "category": "Fun  stuff"},
            ]
        }
    )
    rows = list(ManualDataSource(spec).iter_links(Diagnostics()))
    assert rows == [
        ("a", "b", 1.5, "Food"),
        ("b", "c", 2.0, None),
        ("b", "d", 3.0, None),
        ("b", "e", 4.0, "Fun stuff"),
    ]
    assert list(ManualDataSource(ManualSource()).iter_links(Diagnostics())) == []


def test_manual_source_never_touches_the_diagnostics() -> None:
    diag = Diagnostics()
    spec = ManualSource.model_validate({"links": [{"source": "a", "target": "b", "value": 1}]})
    list(ManualDataSource(spec).iter_links(diag))
    assert (diag.warnings, diag.skipped) == ([], 0)


# --------------------------------------------------------------------------- open_source


def test_open_source_builds_each_kind_from_the_spec_and_context(source_ctx: SourceContext) -> None:
    manual_spec = ManualSource.model_validate(
        {"links": [{"source": "a", "target": "b", "value": 1, "category": "Food"}]}
    )
    manual = open_source(manual_spec, source_ctx)
    assert list(manual.iter_links(Diagnostics())) == [("a", "b", 1.0, "Food")]

    text = open_source(TextSource(content="a,b,1"), source_ctx)
    assert type(text).__module__ == "sankey_studio.sources.text"
    mongo = open_source(MongoSource(connection="test", collection="flows"), source_ctx)
    assert type(mongo).__module__ == "sankey_studio.sources.mongo_source"


def test_open_source_hands_the_spec_and_the_context_through(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, tuple[Any, ...]]] = []

    def fake(kind: str) -> Any:
        def build(*args: Any) -> str:
            seen.append((kind, args))
            return kind

        return build

    monkeypatch.setattr("sankey_studio.sources.text.TextDataSource", fake("text"))
    monkeypatch.setattr("sankey_studio.sources.mongo_source.MongoDataSource", fake("mongo"))
    text_spec = TextSource(content="a,b,1")
    mongo_spec = MongoSource(connection="test", collection="flows")
    assert open_source(text_spec, source_ctx) == "text"  # type: ignore[comparison-overlap]
    assert open_source(mongo_spec, source_ctx) == "mongo"  # type: ignore[comparison-overlap]
    assert len(seen) == 2
    (text_kind, text_args), (mongo_kind, mongo_args) = seen
    assert (text_kind, len(text_args)) == ("text", 2)
    assert text_args[0] is text_spec
    assert text_args[1] is source_ctx
    assert (mongo_kind, len(mongo_args)) == ("mongo", 2)
    assert mongo_args[0] is mongo_spec
    assert mongo_args[1] is source_ctx
