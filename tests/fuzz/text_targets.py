# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Fuzz targets for pasted text: the format parsers, the sniffer, JSON streaming and the rewriter.

Each ``fuzz_*`` function takes the raw bytes of one input. A ``SourceError`` is the parsers'
documented answer to bad text and is swallowed; any other exception, a hang or a broken contract
(the ``DataSource`` promises of ``sources/base.py``) is a finding.
"""

from __future__ import annotations

import functools
import math
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import ValidationError

from sankey_studio.errors import SourceError
from sankey_studio.models import (
    CATEGORY_MAX,
    MAX_INLINE_CHARS,
    NAME_MAX,
    AddEntry,
    AppSettings,
    ReorderNodes,
    SetCategory,
    TextSource,
)
from sankey_studio.mongo import MongoClients
from sankey_studio.sources import open_source
from sankey_studio.sources.base import MAX_WARNINGS, Diagnostics, SourceContext
from sankey_studio.sources.formats import json_rows
from sankey_studio.sources.rewrite import RewriteJob, rewrite_text
from sankey_studio.util import is_reserved_category, normalize_category
from tests.fuzz.inputs import Reader, pick

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sankey_studio.models import RawLink

#: A pasted text never opens a file: a directory that cannot exist makes any access loud.
NO_SOURCES_DIR = Path("/nonexistent-fuzz-sources")
FORMATS = ("auto", "csv", "tsv", "sankeymatic", "json")
DELIMITERS = (None, ",", "\t", ";")
#: Chunk sizes (characters) the JSON reader is run with; the production size is 65,536.
CHUNK_SIZES = (1, 2, 3, 5, 8, 64)
NAMES = ("A", "B", "C", "Rent")
VALUES = (12.5, 1e-9, 1e15, 0.1)
CATEGORIES = (None, "Fixed", "Cat egory")


@functools.cache
def context(*, strict: bool = False) -> SourceContext:
    """A source context whose MongoDB registry never connects (it is not used for pasted text)."""
    settings = AppSettings()
    return SourceContext(
        settings=settings,
        sources_dir=NO_SOURCES_DIR,
        mongo=MongoClients(lambda: settings),
        strict=strict,
    )


class Outcome(NamedTuple):
    """Everything one load produced: the links read, the warnings and the fatal error, if any."""

    links: list[RawLink]
    warnings: list[str]
    error: str | None


def text_options(flags: int) -> tuple[dict[str, Any], bool]:
    """``TextSource`` fields and the strict switch from one option byte (0 = defaults)."""
    options = {
        "format": pick(FORMATS, flags & 7),
        "has_header": not flags & 8,
        "detect_category": not flags & 32,
        "delimiter": DELIMITERS[flags >> 6],
    }
    return options, bool(flags & 16)


def make_spec(text: str, options: dict[str, Any]) -> TextSource | None:
    """The spec for pasted ``text``, or ``None`` when the model refuses it (also expected)."""
    try:
        return TextSource(content=text, **options)
    except ValidationError:
        return None


def load(spec: TextSource, *, strict: bool) -> Outcome:
    """Read every link of ``spec`` the way the application does."""
    diag = Diagnostics()
    links: list[RawLink] = []
    error = None
    try:
        links.extend(open_source(spec, context(strict=strict)).iter_links(diag))
    except SourceError as exc:
        error = str(exc)
    return Outcome(links, diag.finish(), error)


def check_name(name: object) -> None:
    assert isinstance(name, str), name
    assert name == name.strip(), name
    assert 0 < len(name) <= NAME_MAX, name
    assert "\0" not in name, name
    name.encode()  # a lone surrogate must have been refused


def check_link(link: RawLink) -> None:
    """The promise of ``DataSource.iter_links`` for one yielded link."""
    source, target, value, category = link
    check_name(source)
    check_name(target)
    assert isinstance(value, float), value
    assert math.isfinite(value), value
    assert value > 0, value
    if category is None:
        return
    assert isinstance(category, str), category
    assert 0 < len(category) <= CATEGORY_MAX, category
    assert normalize_category(category) == category, category
    assert not is_reserved_category(category), category


def check_outcome(outcome: Outcome) -> None:
    for link in outcome.links:
        check_link(link)
    assert len(outcome.warnings) <= MAX_WARNINGS + 1
    assert all(isinstance(warning, str) for warning in outcome.warnings)


def fuzz_text_source(data: bytes) -> None:
    """Sniff and parse pasted text in every format, with a fuzzed set of column options."""
    reader = Reader(data)
    options, strict = text_options(reader.option())
    spec = make_spec(reader.text(), options)
    if spec is not None:
        check_outcome(load(spec, strict=strict))


@contextmanager
def chunk_size(size: int) -> Iterator[None]:
    """Run the JSON reader with ``size``-character chunks (restored afterwards)."""
    saved = json_rows.CHUNK_CHARS
    json_rows.CHUNK_CHARS = size
    try:
        yield
    finally:
        json_rows.CHUNK_CHARS = saved


def fuzz_json_stream(data: bytes) -> None:
    """The streaming JSON reader must give the same answer whatever the chunk boundaries are."""
    reader = Reader(data)
    flags = reader.option()
    spec = make_spec(reader.text(), {"format": "json"})
    if spec is None:
        return
    strict = bool(flags & 8)
    whole = load(spec, strict=strict)
    check_outcome(whole)
    size = pick(CHUNK_SIZES, flags & 7)
    with chunk_size(size):
        pieces = load(spec, strict=strict)
    assert pieces == whole, f"chunk size {size} changed the result"


def make_edit(flags: int) -> AddEntry | SetCategory | ReorderNodes:
    """One edit of the rewriter from one option byte (0 = add A -> B)."""
    source = pick(NAMES, flags >> 2)
    target = NAMES[(NAMES.index(source) + 1 + (flags >> 4) % (len(NAMES) - 1)) % len(NAMES)]
    category = pick(CATEGORIES, flags >> 6)
    kind = flags & 3
    if kind == 1:
        return SetCategory(op="set_category", source=source, target=target, category=category)
    if kind == 2:
        return ReorderNodes(op="reorder", order=[target, source])
    value = pick(VALUES, flags >> 2)
    return AddEntry(op="add_entry", source=source, target=target, value=value, category=category)


def fuzz_rewrite(data: bytes) -> None:
    """Rewrite a text for an edit; the rewriter checks itself, so only crashes can be findings."""
    reader = Reader(data)
    options, _ = text_options(reader.option())
    edit = make_edit(reader.option())
    text = reader.text()
    spec = make_spec(text, options)
    if spec is None:
        return
    try:
        result = rewrite_text(RewriteJob(spec, text, edit, {}, context()))
    except SourceError:  # SourceEditRefused is one: the edit was refused, which is allowed
        return
    assert len(result.text) <= MAX_INLINE_CHARS
    assert result.changed >= 0
    assert result.changed or result.text == text
