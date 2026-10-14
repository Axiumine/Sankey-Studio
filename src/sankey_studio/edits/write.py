"""``write_edit``: write the edit to the file or the collection the person agreed to.

The browser calls ``plan`` first; ``write`` checks everything again, because the request is the
only evidence: the effective preference must be ``source`` (else 422 ``no_consent``), the operator
gates are re-run, and the data is re-read. A definite refusal is an expected answer
(``where="graph"`` with the reason); a failure that leaves the result unknown (driver, OS) is an
error (502 / 503) and nothing falls back. After every MongoDB write the graph cache is cleared.
Pasted text and manual links have nothing to write: they answer like ``plan``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.edits import mongo
from sankey_studio.edits.files import write_file
from sankey_studio.edits.gates import check_gates
from sankey_studio.edits.job import graph_outcome, make_job, refusal_outcome
from sankey_studio.edits.override import override_for
from sankey_studio.edits.plan import plan_edit, validate_candidate
from sankey_studio.edits.target import display_target, effective_write_back, write_target
from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import EditOutcome, MongoSource, ReorderNodes

if TYPE_CHECKING:
    from sankey_studio.edits.job import EditJob
    from sankey_studio.models import EditRequest
    from sankey_studio.pipeline import ClearableCache
    from sankey_studio.services import Services


def _write_mongo(job: EditJob) -> EditOutcome:
    changed = mongo.apply_edit(job)
    job.cache.clear()  # the graphs cached from this collection are stale now
    return EditOutcome(
        where="mongo",
        written=True,
        consent="granted",
        target=display_target(job.spec, job.settings),
        target_key=write_target(job.spec, job.settings),
        changed=changed,
        override=override_for(job),
    )


def _write(job: EditJob) -> EditOutcome:
    if isinstance(job.spec, MongoSource):
        return _write_mongo(job)
    return write_file(job)


def write_edit(services: Services, request: EditRequest, cache: ClearableCache) -> EditOutcome:
    """Write ``request.edit`` to its source; see the module docstring for the answers."""
    job = make_job(services, request, cache)
    if not job.is_external:
        return plan_edit(services, request, cache)
    if isinstance(job.edit, ReorderNodes) and isinstance(job.spec, MongoSource):
        return graph_outcome("order_in_graph")
    if effective_write_back(job.spec, job.settings) != "source":
        raise SourceEditRefused("no_consent")
    if (blocked := check_gates(job, writing=True)) is not None:
        return blocked
    try:
        validate_candidate(job, EditOutcome(where="file"))
        return _write(job)
    except SourceEditRefused as refused:
        return refusal_outcome(refused)
