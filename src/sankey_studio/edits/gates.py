"""The operator gates every file or MongoDB edit passes before the source is touched.

Evaluated by ``plan`` AND ``write``, first match wins:

1. the server may not write at all (remote mode without ``--allow-remote-writes``);
2. MongoDB and remote mode without ``--allow-source-writes``;
3. the MongoDB namespace rules (system databases, ``sankey_studio_`` collections);
4. a new string that a spreadsheet could read as a formula (the CSV export guard cannot run on
   stored data; numbers are exempt; for ``set_category`` only the category is stored).

``plan`` answers ``graph`` with the reason; ``write`` raises 403 ``read_only_mode`` for 1 and 2
(the route refuses before the body is decoded in the common case) and answers ``graph`` for 3
and 4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sankey_studio.edits.job import graph_outcome, refusal_outcome
from sankey_studio.edits.mongo import target_of
from sankey_studio.errors import ReadOnlyModeError, SourceEditRefused
from sankey_studio.models import AddEntry, MongoSource, SetCategory
from sankey_studio.storage.mongo_source_writes import check_target
from sankey_studio.util import starts_like_formula

if TYPE_CHECKING:
    from sankey_studio.edits.job import EditJob
    from sankey_studio.models import EditOutcome

MSG_READ_ONLY: Final = (
    "Writing edits to the source is disabled in read-only remote mode "
    "(--allow-remote-writes, and --allow-source-writes for MongoDB)"
)


def _strings(edit: object) -> list[str]:
    """The new text an edit would store (numbers and node order are exempt).

    A ``set_category`` stores only the category: its source and target merely select the pair,
    so a node name that starts like a formula must not block it.
    """
    if isinstance(edit, SetCategory):
        return [] if edit.category is None else [edit.category]
    if not isinstance(edit, AddEntry):
        return []
    texts = [edit.source, edit.target]
    return texts if edit.category is None else [*texts, edit.category]


def _blocked(job: EditJob) -> bool:
    """Gates 1 and 2: the operator does not allow this write."""
    config = job.services.config
    if not config.privileged_writes_allowed:
        return True
    return isinstance(job.spec, MongoSource) and not config.source_writes_allowed


def check_gates(job: EditJob, *, writing: bool) -> EditOutcome | None:
    """``None`` when the edit may go on, else the ``graph`` answer (or 403 when ``writing``)."""
    if _blocked(job):
        if writing:
            raise ReadOnlyModeError(MSG_READ_ONLY)
        return graph_outcome("read_only_mode")
    try:
        if isinstance(job.spec, MongoSource):
            check_target(target_of(job))
    except SourceEditRefused as refused:
        return refusal_outcome(refused)
    if any(starts_like_formula(text) for text in _strings(job.edit)):
        return graph_outcome("unsafe_value")
    return None
