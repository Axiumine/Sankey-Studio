"""Rewrite a text source for an edit (add an entry, set a category, reorder rows).

``rewrite_text`` is pure: it takes the text and the spec and returns the new text, never touching
a file. Untouched lines stay byte for byte; the result is accepted only when the REAL parser reads
the new text as the old links plus the intended change (``verify.check_rewrite``), else
``SourceEditRefused`` says why (a ``Reason``). ``manual.rewrite_links`` does the same for
manual links.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import MAX_INLINE_CHARS, AddEntry
from sankey_studio.sources.formats.csv_rows import delimiter_of
from sankey_studio.sources.rewrite.apply import apply_edit
from sankey_studio.sources.rewrite.bootstrap import bootstrap_text
from sankey_studio.sources.rewrite.delimited import build_delimited, with_pin
from sankey_studio.sources.rewrite.jsontext import JsonDoc
from sankey_studio.sources.rewrite.lines import peel_bom
from sankey_studio.sources.rewrite.model import REWRITE_MAX_BYTES, RewriteJob, Rewritten
from sankey_studio.sources.rewrite.parsing import make_job
from sankey_studio.sources.rewrite.sankeymatic import SankeymaticDoc
from sankey_studio.sources.rewrite.verify import check_rewrite

if TYPE_CHECKING:
    from sankey_studio.sources.formats.job import ParseJob
    from sankey_studio.sources.rewrite.model import TextDoc

__all__ = ["REWRITE_MAX_BYTES", "RewriteJob", "Rewritten", "rewrite_text"]


def _check_size(job: RewriteJob, text: str) -> None:
    limit = MAX_INLINE_CHARS if job.spec.origin == "inline" else REWRITE_MAX_BYTES
    if len(text) > limit:
        raise SourceEditRefused("file_too_large")


def _document(job: RewriteJob, parse: ParseJob) -> TextDoc:
    if parse.fmt == "json":
        return JsonDoc(job)
    if parse.fmt == "sankeymatic":
        return SankeymaticDoc(job)
    return build_delimited(job, parse)


def _attempt(job: RewriteJob) -> Rewritten:
    """One rewrite and its self-check."""
    parse = make_job(job.spec, job.text, job.ctx)
    if isinstance(job.edit, AddEntry) and not peel_bom(job.text)[1].strip():
        result = bootstrap_text(job, parse, job.edit)
        _check_size(job, result.text)
        check_rewrite(job, result)
        return result
    doc = _document(job, parse)
    items, changed = apply_edit(doc, job.edit, job.alias)
    if not changed:
        return Rewritten(job.text, doc.spec, 0)
    result = Rewritten(doc.render(items), doc.spec, changed, reformatted=doc.reformatted)
    _check_size(job, result.text)
    check_rewrite(job, result)
    return result


def _pinned(job: RewriteJob) -> RewriteJob:
    """``job`` with the format and delimiter the OLD text resolves to written into the spec."""
    parse = make_job(job.spec, job.text, job.ctx)
    pins: dict[str, object] = {"format": parse.fmt}
    if parse.fmt in ("csv", "tsv"):
        pins["delimiter"] = delimiter_of(parse)
    return replace(job, spec=with_pin(job.spec, **pins))


def rewrite_text(job: RewriteJob) -> Rewritten:
    """``job.text`` with ``job.edit`` applied, or ``SourceEditRefused``.

    The sniffer reads only the first 4096 characters, so an edit can flip the format or the
    delimiter it finds: a failed check is retried once with both pinned to what the old text had.
    """
    _check_size(job, job.text)
    try:
        return _attempt(job)
    except SourceEditRefused as exc:
        if exc.reason != "cannot_verify":
            raise
    pinned = _pinned(job)
    if pinned.spec == job.spec:
        raise SourceEditRefused("cannot_verify")
    return _attempt(pinned)
