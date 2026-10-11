"""Text data source: wires decoding, format sniffing and the parsers together.

The text is read as a stream and never held whole. Bytes become text only through
``io.TextIOWrapper(..., errors="strict")``; a decode error is a ``SourceError`` naming the line.
Pasted (``inline``) text is already decoded, so ``encoding`` only applies to files.
"""

from __future__ import annotations

import io
from contextlib import contextmanager
from typing import TYPE_CHECKING, TextIO

from sankey_studio.errors import SourceError
from sankey_studio.sources.base import CategoryCleaner
from sankey_studio.sources.files.paths import MIB, open_binary
from sankey_studio.sources.formats import PARSERS, detect_format
from sankey_studio.sources.formats.job import ParseJob
from sankey_studio.sources.formats.sniff import SNIFF_CHARS, ParsedFormat

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from sankey_studio.models import RawLink, TextSource
    from sankey_studio.sources.base import Diagnostics, SourceContext

INLINE_LABEL = "inline"


def _required(value: str | None, what: str) -> str:
    """``value``, or a ``SourceError`` for a ``TextSource`` built without its ``what``."""
    if value is None:
        raise SourceError(f"the text source has no {what}")
    return value


@contextmanager
def _text_file(ctx: SourceContext, rel: str, encoding: str) -> Iterator[TextIO]:
    """The file under the sources dir as a strict text stream (size-capped, symlink-safe)."""
    limit = ctx.settings.max_upload_mb * MIB
    with (
        open_binary(ctx.sources_dir, rel, limit) as raw,
        io.TextIOWrapper(raw, encoding=encoding, errors="strict") as text,
    ):
        yield text


class TextDataSource:
    """Streams ``RawLink`` tuples from pasted text or a managed file."""

    def __init__(self, spec: TextSource, ctx: SourceContext) -> None:
        self._spec = spec
        self._ctx = ctx

    def _label(self) -> str:
        spec = self._spec
        return INLINE_LABEL if spec.origin == "inline" else _required(spec.path, "path")

    def _open(self) -> AbstractContextManager[TextIO]:
        spec = self._spec
        if spec.origin == "inline":
            return io.StringIO(_required(spec.content, "content"), newline=None)
        return _text_file(self._ctx, _required(spec.path, "path"), spec.encoding)

    def _sample(self) -> str:
        """The first characters, for sniffing. A decode error is left to the real parse."""
        try:
            with self._open() as stream:
                return stream.read(SNIFF_CHARS)
        except UnicodeDecodeError:
            return ""

    def _format(self, sample: str) -> ParsedFormat:
        fmt = self._spec.format
        return detect_format(sample) if fmt == "auto" else fmt

    def iter_links(self, diag: Diagnostics) -> Iterator[RawLink]:
        cleaner = CategoryCleaner(diag)
        try:
            sample = self._sample()
            job = ParseJob(
                spec=self._spec,
                ctx=self._ctx,
                diag=diag,
                cleaner=cleaner,
                label=self._label(),
                fmt=self._format(sample),
                sample=sample,
            )
            with self._open() as stream:
                yield from PARSERS[job.fmt](job, stream)
        finally:
            cleaner.finish()
