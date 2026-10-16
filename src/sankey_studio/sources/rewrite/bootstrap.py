# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The first line of an empty text: ``add_entry`` on nothing writes a complete small document."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.sources.formats.csv_rows import CATEGORY_HEADER, CATEGORY_POSITION, delimiter_of
from sankey_studio.sources.rewrite.delimited import emit, with_pin
from sankey_studio.sources.rewrite.jsontext import json_text
from sankey_studio.sources.rewrite.lines import DEFAULT_EOL
from sankey_studio.sources.rewrite.model import NewRow, Rewritten, number_text
from sankey_studio.sources.rewrite.sankeymatic import sankeymatic_text

if TYPE_CHECKING:
    from sankey_studio.models import AddEntry
    from sankey_studio.sources.formats.job import ParseJob
    from sankey_studio.sources.rewrite.model import RewriteJob


def _delimited(job: RewriteJob, parse: ParseJob, row: NewRow) -> tuple[str, dict[str, object]]:
    """Header (when the spec has one) and the row; pins when auto-detection is off."""
    spec, delimiter = job.spec, delimiter_of(parse)
    names = ["source", "target", "value"]
    cells = [row.source, row.target, number_text(row.value)]
    pins: dict[str, object] = {}
    if row.category is not None:
        names.append(CATEGORY_HEADER)
        cells.append(row.category)
        if not spec.detect_category:  # nothing would find the column: name it
            pins["category_column"] = CATEGORY_HEADER if spec.has_header else CATEGORY_POSITION
    header = emit(names, delimiter, DEFAULT_EOL) if spec.has_header else ""
    return header + emit(cells, delimiter, DEFAULT_EOL), pins


def bootstrap_text(job: RewriteJob, parse: ParseJob, edit: AddEntry) -> Rewritten:
    """``job.text`` is empty and ``edit`` an ``add_entry``: the text of a one-entry document."""
    row = NewRow(edit.source, edit.target, edit.value, edit.category)
    pins: dict[str, object] = {"format": parse.fmt}
    if parse.fmt in ("csv", "tsv"):
        text, extra = _delimited(job, parse, row)
        pins.update(extra)
    elif parse.fmt == "sankeymatic":
        text = sankeymatic_text(row, DEFAULT_EOL)
    else:
        text = json_text(row)
    return Rewritten(text, with_pin(job.spec, **pins), 1)
