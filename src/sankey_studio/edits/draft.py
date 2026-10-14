"""The draft-held branch: manual links and pasted text live in the graph, so they need no consent.

``plan`` rewrites the data and answers the whole new source (``where="draft"``); the browser
replaces ``draft.source`` with it. A reorder also rewrites the rows; when the new row order
would paint a node or category in another colour, the answer carries ``pins`` that keep the
colours (``would_recolour`` only when they would not fit in the style).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.edits.job import graph_outcome, refusal_outcome, reordering, with_source
from sankey_studio.edits.override import override_for
from sankey_studio.edits.reasons import REFORMATTED_NOTICE
from sankey_studio.edits.recolour import pins_for
from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import EditOutcome, ManualSource, TextSource
from sankey_studio.pipeline import build_graph_from_draft
from sankey_studio.sources.rewrite import RewriteJob, rewrite_text
from sankey_studio.sources.rewrite.manual import rewrite_links

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sankey_studio.edits.job import EditJob
    from sankey_studio.models import Link, SourceSpec, StylePins


def _links_changed(old: Sequence[Link], new: Sequence[Link]) -> int:
    """Links added, or whose data differs at the same position."""
    return (
        len(new) - len(old)
        if len(new) != len(old)
        else sum(a != b for a, b in zip(old, new, strict=True))
    )


def _rewrite_manual(job: EditJob, spec: ManualSource) -> tuple[SourceSpec, int, bool]:
    links = rewrite_links(spec.links, job.edit, job.alias)
    return ManualSource(links=links), _links_changed(spec.links, links), False


def _rewrite_text(job: EditJob, spec: TextSource) -> tuple[SourceSpec, int, bool]:
    ctx = job.services.source_context()
    rewritten = rewrite_text(RewriteJob(spec, spec.content or "", job.edit, job.alias, ctx))
    fields = {**rewritten.spec.model_dump(), "content": rewritten.text}
    return TextSource.model_validate(fields), rewritten.changed, rewritten.reformatted


def _rewrite(job: EditJob) -> tuple[SourceSpec, int, bool]:
    """``(new source, rows or links changed, json re-formatted)`` or ``SourceEditRefused``."""
    spec = job.spec
    if isinstance(spec, ManualSource):
        return _rewrite_manual(job, spec)
    return _rewrite_text(job, spec) if isinstance(spec, TextSource) else (spec, 0, False)


def _pins(job: EditJob, source: SourceSpec) -> StylePins | None:
    """The pins that keep the colours when a reorder moves the rows (needs both graphs)."""
    if reordering(job.edit) is None:
        return None
    services, cache, draft = job.services, job.cache, job.draft
    before = build_graph_from_draft(services, draft, cache)
    after = build_graph_from_draft(services, with_source(draft, source), cache)
    return pins_for(before, after, draft.style)


def plan_draft(job: EditJob) -> EditOutcome:
    """The edit applied to the data in the draft, or ``graph`` when it cannot be."""
    try:
        source, changed, reformatted = _rewrite(job)
        pins = _pins(job, source) if changed else None
    except SourceEditRefused as refused:
        return refusal_outcome(refused)
    if changed == 0:
        return graph_outcome("order_in_graph")
    notice = REFORMATTED_NOTICE if reformatted else None
    return EditOutcome(
        where="draft",
        changed=changed,
        source=source,
        notice=notice,
        override=override_for(job),
        pins=pins,
    )
