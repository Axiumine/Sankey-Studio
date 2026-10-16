# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``TextDataSource.parse_job``: the per-load state the parsers and the rewriter share."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.models import TextSource
from sankey_studio.sources.base import CategoryCleaner, Diagnostics
from sankey_studio.sources.text import TextDataSource
from tests.sources.text_support import put

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext


def test_an_inline_job_carries_the_resolved_format_and_the_sample(
    source_ctx: SourceContext,
) -> None:
    spec = TextSource(content="a [1] b\n")
    diag = Diagnostics()
    cleaner = CategoryCleaner(diag)
    job = TextDataSource(spec, source_ctx).parse_job(cleaner, diag)
    assert (job.spec, job.diag, job.cleaner) == (spec, diag, cleaner)
    assert (job.label, job.fmt, job.sample) == ("inline", "sankeymatic", "a [1] b\n")
    assert job.ctx is source_ctx


def test_an_explicit_format_wins_over_sniffing(source_ctx: SourceContext) -> None:
    diag = Diagnostics()
    spec = TextSource(content="a [1] b\n", format="csv")
    job = TextDataSource(spec, source_ctx).parse_job(CategoryCleaner(diag), diag)
    assert job.fmt == "csv"


def test_a_file_job_is_labelled_with_its_path(source_ctx: SourceContext) -> None:
    put(source_ctx, "d/f.csv", "a;b;1\n")
    diag = Diagnostics()
    spec = TextSource(origin="file", path="d/f.csv")
    job = TextDataSource(spec, source_ctx).parse_job(CategoryCleaner(diag), diag)
    assert (job.label, job.fmt, job.sample) == ("d/f.csv", "csv", "a;b;1\n")


def test_a_sample_is_cut_at_the_sniff_window(source_ctx: SourceContext) -> None:
    diag = Diagnostics()
    spec = TextSource(content="a,b,1\n" * 2000)
    job = TextDataSource(spec, source_ctx).parse_job(CategoryCleaner(diag), diag)
    assert len(job.sample) == 4096


def test_parse_job_does_not_parse_or_warn(source_ctx: SourceContext) -> None:
    diag = Diagnostics()
    spec = TextSource(content="not,a,number\n")
    TextDataSource(spec, source_ctx).parse_job(CategoryCleaner(diag), diag)
    assert diag.finish() == []
