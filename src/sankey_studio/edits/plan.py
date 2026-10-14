"""``plan_edit``: where would this edit go, and what must the person agree to first?

Pure: it reads a file or counts documents and writes nothing, so it stays available in read-only
remote mode. The decision table (first match wins):

1. manual links and pasted text: the data lives in the draft (``where="draft"``, no consent);
2. a reorder of MongoDB data, or of a file the person has not allowed to write: ``graph``;
3. the preference of this graph for this target is ``graph``: ``graph`` (``preference``);
4. the operator gates (``gates``);
5. a dry run (file: rewrite in memory; MongoDB: count) and ``where="file"|"mongo"`` with the
   consent state (``ask`` or ``granted``), the display ``target`` and the opaque ``target_key``.

``add_entry`` is validated first against the graph it would produce: a cycle is a 422
``graph_build_error``, nothing is written and no dialog is shown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.edits import files, mongo
from sankey_studio.edits.draft import plan_draft
from sankey_studio.edits.gates import check_gates
from sankey_studio.edits.job import (
    graph_outcome,
    make_job,
    refusal_outcome,
    with_extra_link,
    with_source,
)
from sankey_studio.edits.target import display_target, effective_write_back, write_target
from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import AddEntry, EditOutcome, MongoSource, ReorderNodes
from sankey_studio.pipeline import build_graph_from_draft

if TYPE_CHECKING:
    from sankey_studio.edits.job import EditJob
    from sankey_studio.models import EditRequest
    from sankey_studio.pipeline import ClearableCache
    from sankey_studio.services import Services


def validate_candidate(job: EditJob, outcome: EditOutcome) -> None:
    """Build the graph an ``add_entry`` leads to; a cycle raises ``GraphBuildError`` (422).

    A draft answer is built from the new source (this also warms the cache with exactly what the
    browser posts to ``/preview`` next); anything else is built from the entry as a graph-only
    link, which is what the same data plus one row draws. Only an entry that stays in the graph
    counts against the cap of those links (``too_many``): a row for a file or a collection does
    not.
    """
    if not isinstance(job.edit, AddEntry):
        return
    if outcome.where == "draft" and outcome.source is not None:
        candidate = with_source(job.draft, outcome.source)
    else:
        candidate = with_extra_link(job.draft, job.edit, capped=outcome.where == "graph")
    build_graph_from_draft(job.services, candidate, job.cache)


def _dry_run(job: EditJob) -> int:
    """Rows or documents the edit would change; ``SourceEditRefused`` when it cannot."""
    if isinstance(job.spec, MongoSource):
        return mongo.count_documents(job)
    return files.dry_run(job).changed


def _plan_external(job: EditJob) -> EditOutcome:
    preference = effective_write_back(job.spec, job.settings)
    if isinstance(job.edit, ReorderNodes) and (
        isinstance(job.spec, MongoSource) or preference == "ask"
    ):
        return graph_outcome("order_in_graph")  # a drag never asks
    if preference == "graph":
        return graph_outcome("preference")
    if (blocked := check_gates(job, writing=False)) is not None:
        return blocked
    try:
        changed = _dry_run(job)
    except SourceEditRefused as refused:
        return refusal_outcome(refused)
    return EditOutcome(
        where="mongo" if isinstance(job.spec, MongoSource) else "file",
        consent="ask" if preference == "ask" else "granted",
        target=display_target(job.spec, job.settings),
        target_key=write_target(job.spec, job.settings),
        changed=changed,
    )


def plan_edit(services: Services, request: EditRequest, cache: ClearableCache) -> EditOutcome:
    """Where ``request.edit`` would go, without changing anything."""
    job = make_job(services, request, cache)
    outcome = _plan_external(job) if job.is_external else plan_draft(job)
    validate_candidate(job, outcome)
    return outcome
