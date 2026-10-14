"""The MongoDB branch of an edit: count the documents (plan) or change them (write).

Only ``find`` sources are written (an inserted document needs a plain-equality filter, so that
it matches the source; a category update accepts any filter the read checks allow). The planner
(``sources.mongo_write_plan``) builds the filter, the update and the document; the primitives
(``storage.mongo_source_writes``) do the I/O. A definite refusal is a ``SourceEditRefused`` that
the caller turns into a ``graph`` answer; a driver failure is ``SourceWriteError`` (502).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import AddEntry, MongoSource, SetCategory
from sankey_studio.sources.mongo_write_plan import plan_insert, plan_pair_update, resolve_database
from sankey_studio.storage.mongo_source_writes import (
    MONGO_WRITE_MAX_DOCS,
    SourceTarget,
    count_matching,
    insert_document,
    matching_ids,
    update_by_ids,
)

if TYPE_CHECKING:
    from sankey_studio.edits.job import EditJob


def _spec(job: EditJob) -> MongoSource:
    """The source of a job the caller routed here (``is_external`` and not a file)."""
    return cast("MongoSource", job.spec)


def target_of(job: EditJob) -> SourceTarget:
    """Where the edit goes; ``source_incomplete`` when the connection or database is unknown."""
    spec = _spec(job)
    conn = job.settings.connection(spec.connection)
    if conn is None:
        raise SourceEditRefused("source_incomplete")
    database = resolve_database(spec, conn.default_database)
    return SourceTarget(job.services.mongo, spec.connection, database, spec.collection)


def _timeout_ms(job: EditJob) -> int:
    return _spec(job).max_time_ms or job.settings.mongo_timeout_ms


def _check_room(job: EditJob, target: SourceTarget) -> None:
    """A new document in natural order must fall inside the window the source reads."""
    spec = _spec(job)
    seen = count_matching(target, spec.filter, spec.limit, _timeout_ms(job))
    if seen >= spec.limit:
        raise SourceEditRefused("limit_reached")


def count_documents(job: EditJob) -> int:
    """Dry run: how many documents the edit would change or add (nothing is written)."""
    spec, edit, target = _spec(job), job.edit, target_of(job)
    if isinstance(edit, SetCategory):
        planned = plan_pair_update(spec, edit, job.alias)
        found = count_matching(target, planned.filter, MONGO_WRITE_MAX_DOCS + 1, _timeout_ms(job))
        if found == 0:
            raise SourceEditRefused("no_match")
        if found > MONGO_WRITE_MAX_DOCS:
            raise SourceEditRefused("too_many_documents")
        return found
    if isinstance(edit, AddEntry):
        plan_insert(spec, edit)
        _check_room(job, target)
        return 1
    raise SourceEditRefused("order_in_graph")


def apply_edit(job: EditJob) -> int:
    """Change the documents (``_id``-scoped and re-filtered) or add one; the count changed."""
    spec, edit, target = _spec(job), job.edit, target_of(job)
    if isinstance(edit, SetCategory):
        planned = plan_pair_update(spec, edit, job.alias)
        ids = matching_ids(target, planned.filter, MONGO_WRITE_MAX_DOCS + 1, _timeout_ms(job))
        if not ids:
            raise SourceEditRefused("no_match")
        return update_by_ids(target, ids, planned.filter, planned.update)
    if isinstance(edit, AddEntry):
        document = plan_insert(spec, edit).document
        _check_room(job, target)
        return insert_document(target, document)
    raise SourceEditRefused("order_in_graph")
