# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``TextDataSource``: format dispatch, inline text, categories and the category tolerance rule."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, cast

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.models import TextSource
from sankey_studio.sources import open_source
from sankey_studio.sources.base import CategoryCleaner, Diagnostics
from sankey_studio.sources.formats import PARSERS
from sankey_studio.sources.text import TextDataSource
from tests.sources.text_support import inline, load, message_of

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

    from sankey_studio.models import RawLink
    from sankey_studio.sources.base import SourceContext
    from sankey_studio.sources.formats.job import ParseJob

    Ctx = Callable[..., SourceContext]


IGNORED = "Categories ignored (entries kept uncategorised): "


def test_open_source_builds_a_text_data_source(source_ctx: SourceContext) -> None:
    assert isinstance(open_source(TextSource(content="a,b,1"), source_ctx), TextDataSource)


def test_the_parser_table() -> None:
    assert set(PARSERS) == {"csv", "tsv", "sankeymatic", "json"}
    assert PARSERS["csv"] is PARSERS["tsv"]
    assert len({id(parser) for parser in PARSERS.values()}) == 3
    with pytest.raises(TypeError):
        PARSERS["csv"] = PARSERS["json"]  # type: ignore[index]


class Auto(NamedTuple):
    content: str
    fmt: str


AUTO = [
    Auto('[{"source":"a","target":"b","value":1}]', "json"),
    Auto('{"source":"a","target":"b","value":1}', "json"),
    Auto("a [1] b", "sankeymatic"),
    Auto("source,target,value\na,b,1", "csv"),
    Auto("source;target;value\na;b;1", "csv"),
    Auto("source\ttarget\tvalue\na\tb\t1", "tsv"),
]


@pytest.mark.parametrize("case", AUTO, ids=[c.fmt + str(i) for i, c in enumerate(AUTO)])
def test_auto_picks_the_parser_by_sniffing(source_ctx: SourceContext, case: Auto) -> None:
    out = inline(source_ctx, case.content)
    assert out.rows == [("a", "b", 1.0, None)]


def test_the_parser_gets_the_job_and_the_stream(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[ParseJob, str]] = []

    def fake(job: ParseJob, stream: Any) -> Iterator[RawLink]:
        seen.append((job, stream.read()))
        yield ("x", "y", 1.0, None)

    monkeypatch.setattr("sankey_studio.sources.text.PARSERS", {"sankeymatic": fake})
    spec = TextSource(content="a [1] b\r\nc [2] d", format="sankeymatic", encoding="cp1252")
    diag = Diagnostics()
    assert list(TextDataSource(spec, source_ctx).iter_links(diag)) == [("x", "y", 1.0, None)]
    ((job, text),) = seen
    assert text == "a [1] b\nc [2] d"  # universal newlines
    assert job.spec is spec
    assert job.ctx is source_ctx
    assert job.diag is diag
    assert isinstance(job.cleaner, CategoryCleaner)
    assert job.label == "inline"
    assert job.fmt == "sankeymatic"
    assert job.sample == "a [1] b\nc [2] d"


def test_the_sniffed_format_and_sample_reach_the_job(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs: list[ParseJob] = []

    def fake(job: ParseJob, _stream: Any) -> Iterator[RawLink]:
        jobs.append(job)
        return iter(())

    monkeypatch.setattr("sankey_studio.sources.text.PARSERS", {"tsv": fake})
    inline(source_ctx, "a\tb\t1\n")
    assert [(job.fmt, job.sample) for job in jobs] == [("tsv", "a\tb\t1\n")]


def test_the_sample_is_the_first_4096_characters(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    samples: list[str] = []

    def fake(job: ParseJob, _stream: Any) -> Iterator[RawLink]:
        samples.append(job.sample)
        return iter(())

    monkeypatch.setattr("sankey_studio.sources.text.PARSERS", {"csv": fake})
    inline(source_ctx, "a," * 5000)
    assert len(samples[0]) == 4096


def test_creating_the_source_reads_nothing(source_ctx: SourceContext) -> None:
    spec = TextSource(origin="file", path="missing.csv")
    source = TextDataSource(spec, source_ctx)  # no file is touched yet
    with pytest.raises(SourceError, match=r"missing\.csv: no such file or directory"):
        list(source.iter_links(Diagnostics()))


def test_an_inline_source_without_content_is_a_source_error(source_ctx: SourceContext) -> None:
    spec = TextSource.model_construct(origin="inline", content=None)
    assert message_of(lambda: load(source_ctx, spec), SourceError) == (
        "the text source has no content"
    )


def test_a_file_source_without_a_path_is_a_source_error(source_ctx: SourceContext) -> None:
    spec = TextSource.model_construct(origin="file", path=None)
    assert message_of(lambda: load(source_ctx, spec), SourceError) == (
        "the text source has no path"
    )


def test_strict_mode_reaches_the_parsers(make_source_ctx: Ctx) -> None:
    ctx = make_source_ctx(strict=True)
    with pytest.raises(SourceError, match=r"^inline:2: value must be a positive number$"):
        inline(ctx, "source,target,value\na,b,x\n")


def test_without_any_category_nothing_is_skipped_or_warned(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "source;target;value\na;b;1\nb;c;2\n")
    assert [row[3] for row in out.rows] == [None, None]
    assert out.skipped == 0
    assert out.warnings == []


def test_the_category_warning_is_emitted_even_when_the_stream_is_abandoned(
    source_ctx: SourceContext,
) -> None:
    spec = TextSource(content="source,target,value,category\na,b,1,Other\nc,d,2,Food\n")
    diag = Diagnostics()
    rows = open_source(spec, source_ctx).iter_links(diag)
    assert next(rows) == ("a", "b", 1.0, None)
    assert diag.warnings == []
    cast("Generator[RawLink]", rows).close()
    assert diag.warnings == [f"{IGNORED}1 using the reserved names Uncategorized/Other"]


def test_one_cleaner_serves_the_whole_load(source_ctx: SourceContext) -> None:
    rows = "".join(f"a{i},b{i},1,Other\n" for i in range(5))
    out = inline(source_ctx, "source,target,value,category\n" + rows)
    assert len(out.rows) == 5
    assert out.warnings == [f"{IGNORED}5 using the reserved names Uncategorized/Other"]


def test_row_problems_are_capped_by_the_diagnostics(source_ctx: SourceContext) -> None:
    text = "source,target,value\n" + "a,b,x\n" * 60
    out = inline(source_ctx, text)
    assert out.skipped == 60
    assert len(out.warnings) == 51
    assert out.warnings[0] == "inline:2: value must be a positive number"
    assert out.warnings[-1] == "... and 10 more warnings"
