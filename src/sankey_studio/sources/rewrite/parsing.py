# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Parse a text with the REAL parsers, the text being an argument.

The rewriter and its self-check never go through ``TextSource.content``: that field is capped by
``MAX_INLINE_CHARS`` and a copy of a spec with another ``content`` would skip its validators.
"""

from __future__ import annotations

import io
from dataclasses import replace
from typing import TYPE_CHECKING

from sankey_studio.sources.base import CategoryCleaner, Diagnostics
from sankey_studio.sources.formats import PARSERS, detect_format
from sankey_studio.sources.formats.job import ParseJob
from sankey_studio.sources.formats.sniff import SNIFF_CHARS
from sankey_studio.sources.text import INLINE_LABEL

if TYPE_CHECKING:
    from sankey_studio.models import RawLink, TextSource
    from sankey_studio.sources.base import SourceContext


def make_job(spec: TextSource, text: str, ctx: SourceContext) -> ParseJob:
    """The parse job of ``text`` read with ``spec`` (lenient: a bad row is a warning)."""
    sample = io.StringIO(text, newline=None).read(SNIFF_CHARS)
    diag = Diagnostics()
    return ParseJob(
        spec=spec,
        ctx=replace(ctx, strict=False),
        diag=diag,
        cleaner=CategoryCleaner(diag),
        label=INLINE_LABEL,
        fmt=detect_format(sample) if spec.format == "auto" else spec.format,
        sample=sample,
    )


def parse_links(job: ParseJob, text: str) -> list[RawLink]:
    """Every link of ``text``; a ``SourceError`` when it does not load."""
    links = list(PARSERS[job.fmt](job, io.StringIO(text, newline=None)))
    job.cleaner.finish()
    return links
