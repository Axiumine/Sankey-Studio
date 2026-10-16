# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``iter_records``: the physical lines each non-blank record spans, and ``delimiter_of``."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.models import TextSource
from sankey_studio.sources.base import CategoryCleaner, Diagnostics
from sankey_studio.sources.formats.csv_rows import Record, delimiter_of, iter_records
from sankey_studio.sources.formats.lines import LINE_MAX, LineReader
from sankey_studio.sources.text import TextDataSource

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext
    from sankey_studio.sources.formats.job import ParseJob


def job_of(ctx: SourceContext, text: str, **fields: object) -> ParseJob:
    spec = TextSource.model_validate({"content": text, "format": "csv", **fields})
    diag = Diagnostics()
    return TextDataSource(spec, ctx).parse_job(CategoryCleaner(diag), diag)


def records(ctx: SourceContext, text: str, **fields: object) -> list[Record]:
    job = job_of(ctx, text, **fields)
    return list(iter_records(job, LineReader(io.StringIO(text), LINE_MAX, "t")))


class Spans(NamedTuple):
    text: str
    spans: list[tuple[int, int]]


SPANS = [
    Spans("a,b\nc,d\n", [(1, 1), (2, 2)]),
    Spans("a,b\n\n\nc,d\n", [(1, 1), (4, 4)]),  # blank records are skipped
    Spans('a,"x\ny\nz"\nc,d\n', [(1, 3), (4, 4)]),  # a quoted cell spans lines
    Spans("\n,\n a ,b", [(3, 3)]),  # all-blank cells are not records; no final newline
    Spans('"a\nb",c', [(1, 2)]),
    Spans("", []),
]


@pytest.mark.parametrize("case", SPANS, ids=[str(i) for i in range(len(SPANS))])
def test_the_span_of_every_record(source_ctx: SourceContext, case: Spans) -> None:
    got = records(source_ctx, case.text)
    assert [(r.first, r.last) for r in got] == case.spans


def test_the_cells_of_a_record_are_parsed(source_ctx: SourceContext) -> None:
    assert records(source_ctx, 'a,"b,c",d\n') == [Record(1, 1, ["a", "b,c", "d"])]


def test_an_overlong_line_inside_a_record_is_dropped_and_the_span_starts_after_it(
    source_ctx: SourceContext,
) -> None:
    text = "z" * (LINE_MAX + 1) + "\na,b\n"
    got = records(source_ctx, text)
    assert got == [Record(2, 2, ["a", "b"])]


def test_a_record_after_an_overlong_line_in_a_quoted_cell(source_ctx: SourceContext) -> None:
    text = 'a,"x\n' + "z" * (LINE_MAX + 1) + '\ny"\nc,d\n'
    got = records(source_ctx, text)
    assert [(r.first, r.last) for r in got] == [(1, 3), (4, 4)]
    assert got[0].cells == ["a", "x\ny"]


class Delim(NamedTuple):
    text: str
    fields: dict[str, object]
    expected: str


DELIMS = [
    Delim("a;b;c\n1;2;3\n", {}, ";"),
    Delim("a,b\n", {"delimiter": "|"}, "|"),
    Delim("a b\n", {"delimiter": " "}, " "),
    Delim("a,b\n", {"format": "tsv"}, "\t"),
    Delim("a\tb\n", {"format": "auto"}, "\t"),
    Delim("a,b\n", {"format": "tsv", "delimiter": ";"}, ";"),
]


@pytest.mark.parametrize("case", DELIMS, ids=[str(i) for i in range(len(DELIMS))])
def test_the_delimiter_of_a_job(source_ctx: SourceContext, case: Delim) -> None:
    job = job_of(source_ctx, case.text, **case.fields)
    assert delimiter_of(job) == case.expected
