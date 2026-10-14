"""One edit request with everything the branches need, and the answers they build."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sankey_studio.edits.reasons import notice_for
from sankey_studio.errors import SourceEditRefused
from sankey_studio.graph.intern import resolve_aliases
from sankey_studio.models import (
    AddEntry,
    EditOutcome,
    GraphDraft,
    Link,
    MongoSource,
    SetCategory,
    TextSource,
    TransformSpec,
)

if TYPE_CHECKING:
    from sankey_studio.models import (
        AppSettings,
        EditRequest,
        ReorderNodes,
        SourceEdit,
        SourceSpec,
    )
    from sankey_studio.pipeline import ClearableCache
    from sankey_studio.services import Services


@dataclass(frozen=True, slots=True)
class EditJob:
    """The request, the services, the cache and what is derived once (settings, merge map)."""

    services: Services
    request: EditRequest
    cache: ClearableCache
    settings: AppSettings
    #: ``graph.intern.resolve_aliases(draft.transform.merge_nodes)``.
    alias: dict[str, str]

    @property
    def draft(self) -> GraphDraft:
        return self.request.draft

    @property
    def edit(self) -> SourceEdit:
        return self.request.edit

    @property
    def spec(self) -> SourceSpec:
        return self.request.draft.source

    @property
    def is_external(self) -> bool:
        """The data lives in a managed file or a MongoDB collection (needs consent to write)."""
        spec = self.spec
        return isinstance(spec, MongoSource) or (
            isinstance(spec, TextSource) and spec.origin == "file"
        )


def make_job(services: Services, request: EditRequest, cache: ClearableCache) -> EditJob:
    """The job of ``request``; a cyclic merge map raises ``GraphBuildError`` like the build."""
    alias = resolve_aliases(request.draft.transform.merge_nodes)
    return EditJob(services, request, cache, services.settings(), alias)


def graph_outcome(reason: str | None = None) -> EditOutcome:
    """The edit stays in the graph (an expected answer); ``notice`` is the fixed sentence."""
    return EditOutcome.model_validate(
        {"where": "graph", "reason": reason, "notice": notice_for(reason)}
    )


def refusal_outcome(refused: SourceEditRefused) -> EditOutcome:
    """The answer for a definite refusal; ``too_many`` is a hard 422 and is raised again."""
    if refused.reason == "too_many":
        raise refused
    return graph_outcome(refused.reason)


def reordering(edit: SourceEdit) -> ReorderNodes | None:
    """``edit`` when it is a reorder, else ``None``."""
    return None if isinstance(edit, (AddEntry, SetCategory)) else edit


def with_source(draft: GraphDraft, source: SourceSpec) -> GraphDraft:
    """``draft`` with another source, rebuilt through the validators."""
    return GraphDraft.model_validate({**draft.model_dump(), "source": source.model_dump()})


def with_extra_link(draft: GraphDraft, edit: AddEntry, *, capped: bool = True) -> GraphDraft:
    """``draft`` plus the new entry as a graph-only link (``too_many`` at the cap).

    ``capped=False`` is for an entry that goes to a file or collection: the link is only a
    stand-in for the new row there, so the cap of the overlay list does not apply.
    """
    link = Link(source=edit.source, target=edit.target, value=edit.value, category=edit.category)
    transform = draft.transform
    if not capped:
        grown = transform.model_copy(update={"extra_links": [*transform.extra_links, link]})
        return draft.model_copy(update={"transform": grown})
    fields: dict[str, Any] = {
        **transform.model_dump(),
        "extra_links": [*(item.model_dump() for item in transform.extra_links), link.model_dump()],
    }
    try:
        changed = TransformSpec.model_validate(fields)
    except ValidationError:
        raise SourceEditRefused("too_many") from None
    return GraphDraft.model_validate({**draft.model_dump(), "transform": changed.model_dump()})
