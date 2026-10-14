"""The file branch of an edit: rewrite the text of a managed source file.

``dry_run`` reads the file and rewrites the text in memory (nothing is written; a reorder also
works out the pins that keep the colours); ``write_file`` repeats the rewrite under the
directory lock of ``edit_file`` and writes only when it produces exactly the text the dry run
produced, so a file that changed in between is a 409 and not a guessed write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sankey_studio.edits.job import reordering
from sankey_studio.edits.override import override_for
from sankey_studio.edits.recolour import pins_for
from sankey_studio.edits.target import display_target, write_target
from sankey_studio.errors import ConflictError, SourceEditRefused
from sankey_studio.graph import build_graph
from sankey_studio.models import EditOutcome, TextSource
from sankey_studio.pipeline import build_graph_from_draft
from sankey_studio.sources.base import Diagnostics
from sankey_studio.sources.files.paths import MIB
from sankey_studio.sources.files.store import FileEdit, edit_file, read_text
from sankey_studio.sources.overlay import with_extra_links
from sankey_studio.sources.rewrite import RewriteJob, Rewritten, rewrite_text
from sankey_studio.sources.rewrite.parsing import make_job, parse_links

if TYPE_CHECKING:
    from sankey_studio.edits.job import EditJob
    from sankey_studio.models import SankeyGraph, StylePins


def _spec(job: EditJob) -> TextSource:
    """The source of a job the caller routed here (``is_external`` and not MongoDB)."""
    return cast("TextSource", job.spec)


def _request(job: EditJob) -> FileEdit:
    spec = _spec(job)
    return FileEdit(
        sources_dir=job.services.sources_dir(),
        name=spec.path or "",
        encoding=spec.encoding,
        max_bytes=job.settings.max_upload_mb * MIB,
    )


def _rewrite(job: EditJob, text: str) -> Rewritten:
    ctx = job.services.source_context()
    result = rewrite_text(RewriteJob(_spec(job), text, job.edit, job.alias, ctx))
    if result.changed == 0:
        raise SourceEditRefused("order_in_graph")  # nothing to write: the data already says it
    return result


def _graph_of(job: EditJob, result: Rewritten) -> SankeyGraph:
    """The graph the rewritten text would draw (the file itself is not touched)."""
    parse = make_job(result.spec, result.text, job.services.source_context())
    links = with_extra_links(parse_links(parse, result.text), job.draft.transform.extra_links)
    return build_graph(
        links, job.draft.transform, max_raw_links=job.settings.max_links, diag=Diagnostics()
    )


def _pins(job: EditJob, result: Rewritten) -> StylePins | None:
    """The pins that keep the colours when a reorder moves the rows (``would_recolour`` when
    they would not fit in the style)."""
    if reordering(job.edit) is None:
        return None
    before = build_graph_from_draft(job.services, job.draft, job.cache)
    return pins_for(before, _graph_of(job, result), job.draft.style)


def _checked(job: EditJob) -> tuple[Rewritten, StylePins | None]:
    result = _rewrite(job, read_text(_request(job)))
    return result, _pins(job, result)


def dry_run(job: EditJob) -> Rewritten:
    """The rewrite of the current file content; ``SourceEditRefused`` says why not."""
    return _checked(job)[0]


def write_file(job: EditJob) -> EditOutcome:
    """Replace the file by the dry-run text (atomically); 409 if it changed meanwhile."""
    planned, pins = _checked(job)

    def commit(text: str) -> str:
        if _rewrite(job, text).text != planned.text:
            raise ConflictError("The file changed while it was being edited")
        return planned.text

    edit_file(_request(job), commit)
    spec = _spec(job)
    return EditOutcome(
        where="file",
        written=True,
        consent="granted",
        target=display_target(spec, job.settings),
        target_key=write_target(spec, job.settings),
        changed=planned.changed,
        source=planned.spec if planned.spec != spec else None,
        override=override_for(job),
        pins=pins,
    )
