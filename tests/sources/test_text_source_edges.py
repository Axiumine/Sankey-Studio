# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``TextDataSource`` internals: the label of a file source and a sample that cannot decode."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.models import TextSource
from sankey_studio.sources.text import TextDataSource
from tests.sources.text_support import load, message_of, of_file, put, record

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sankey_studio.models import RawLink
    from sankey_studio.sources.base import SourceContext
    from sankey_studio.sources.formats.job import ParseJob


def test_the_label_of_an_inline_source(source_ctx: SourceContext) -> None:
    source = TextDataSource(TextSource(content="a,b,1"), source_ctx)
    assert source._label() == "inline"


def test_the_label_of_a_file_source_is_its_path(source_ctx: SourceContext) -> None:
    source = TextDataSource(TextSource(origin="file", path="sub/f.csv"), source_ctx)
    assert source._label() == "sub/f.csv"


def test_the_label_of_a_file_source_without_a_path_is_a_source_error(
    source_ctx: SourceContext,
) -> None:
    spec = TextSource.model_construct(origin="file", path=None)
    source = TextDataSource(spec, source_ctx)
    assert message_of(source._label, SourceError) == "the text source has no path"


def test_a_sample_that_does_not_decode_is_empty(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(source_ctx, "bad.csv", b"a,b,1\n\xff\n")
    jobs: list[ParseJob] = []

    def fake(job: ParseJob, _stream: Any) -> Iterator[RawLink]:
        jobs.append(job)
        return iter(())

    monkeypatch.setattr("sankey_studio.sources.text.PARSERS", {"csv": fake})
    assert of_file(source_ctx, "bad.csv").rows == []
    assert [(job.fmt, job.sample) for job in jobs] == [("csv", "")]


def test_a_sankeymatic_decode_error_names_the_file_and_the_line(source_ctx: SourceContext) -> None:
    put(source_ctx, "bad.sankey", b"a [1] b\n\xff [2] c\n")
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "bad.sankey", format="sankeymatic")
    assert str(info.value) == "bad.sankey:2: cannot decode the data as utf-8"


def test_a_file_is_decoded_strictly_with_the_declared_encoding(
    source_ctx: SourceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(source_ctx, "f.csv", b"a,b,1\n")
    spec = TextSource(origin="file", path="f.csv", encoding="cp1252", has_header=False)
    calls = record(monkeypatch, io, "TextIOWrapper")
    assert load(source_ctx, spec).rows == [("a", "b", 1.0, None)]
    # one read for the sample, one for the parse
    assert calls == [{"encoding": spec.encoding, "errors": "strict"}] * 2
