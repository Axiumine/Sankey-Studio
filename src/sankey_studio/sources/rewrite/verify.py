"""The self-check: read the old and the new text with the real parser and compare.

An edit is accepted only when the new text loads to exactly the old links plus the intended
change. This is the safety net behind every adapter: whatever a format quirk does to the text,
a mismatch is ``cannot_verify`` and the edit stays in the graph instead.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from sankey_studio.errors import SourceEditRefused, SourceError
from sankey_studio.models import AddEntry, SetCategory
from sankey_studio.sources.rewrite.model import canon
from sankey_studio.sources.rewrite.parsing import make_job, parse_links
from sankey_studio.util import category_key

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sankey_studio.models import RawLink
    from sankey_studio.sources.formats.job import ParseJob
    from sankey_studio.sources.rewrite.model import RewriteJob, Rewritten

Key = tuple[str, str, float, str | None]


def _keys(links: list[RawLink], alias: Mapping[str, str]) -> list[Key]:
    """Links as comparable keys: merged names, categories by identity (not by spelling)."""
    return [
        (canon(source, alias), canon(target, alias), value, _category(category))
        for source, target, value, category in links
    ]


def _category(category: str | None) -> str | None:
    return None if category is None else category_key(category)


def expected(before: list[Key], job: RewriteJob) -> list[Key]:
    """What the new text must load to."""
    edit = job.edit
    if isinstance(edit, AddEntry):
        new = (canon(edit.source, job.alias), canon(edit.target, job.alias), edit.value)
        return [*before, (*new, _category(edit.category))]
    if isinstance(edit, SetCategory):
        pair = (canon(edit.source, job.alias), canon(edit.target, job.alias))
        key = _category(edit.category)
        return [(s, t, v, key if (s, t) == pair else c) for s, t, v, c in before]
    return before


def check_encoding(job: RewriteJob, text: str) -> None:
    """A file must be written in its own encoding and read back the same."""
    if job.spec.origin != "file":
        return
    encoding = job.spec.encoding
    try:
        written = text.encode(encoding)
    except UnicodeEncodeError:
        raise SourceEditRefused("unrepresentable") from None
    if written.decode(encoding) != text:
        raise SourceEditRefused("cannot_verify")


def _load(job: ParseJob, text: str, reason: str) -> tuple[list[RawLink], int]:
    try:
        links = parse_links(job, text)
    except SourceError:
        raise SourceEditRefused(reason) from None
    return links, job.diag.skipped + len(job.diag.finish())


def check_rewrite(job: RewriteJob, result: Rewritten) -> None:
    """Raise ``SourceEditRefused`` unless ``result`` is exactly the intended edit of ``job``."""
    check_encoding(job, result.text)
    old = make_job(job.spec, job.text, job.ctx)
    new = make_job(result.spec, result.text, job.ctx)
    before, old_problems = _load(old, job.text, "unreadable")
    after, new_problems = _load(new, result.text, "cannot_verify")
    wanted = Counter(expected(_keys(before, job.alias), job))
    if new_problems > old_problems or Counter(_keys(after, job.alias)) != wanted:
        raise SourceEditRefused("cannot_verify")
