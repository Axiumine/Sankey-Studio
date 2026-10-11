"""Behaviour shared by the file and the Mongo graph repositories.

Both backends must agree on timestamps (millisecond precision, because BSON cannot store more),
search terms, paging limits, how a revision change is built and which conflict they report.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from sankey_studio.errors import ConflictError, StorageError
from sankey_studio.models import (
    SCHEMA_VERSION,
    GraphCreate,
    GraphDefinition,
    GraphSummary,
    GraphUpdate,
)
from sankey_studio.storage.base import new_graph_id, upgrade_doc

Clock = Callable[[], datetime]

#: Longest search term honoured (longer ones are cut): a name holds 200 characters, a tag 40.
SEARCH_MAX = 200
#: Largest ``limit`` / ``offset`` handed to a backend (the largest signed 32-bit integer).
PAGE_MAX = 2**31 - 1
MSG_STALE = "Graph was modified since you loaded it; reload it or save a copy"
MSG_EXISTS = "A graph with this id already exists"
MSG_UNREADABLE = "Stored graph is unreadable"


def utc_now() -> datetime:
    """Current UTC time truncated to milliseconds (what BSON keeps; files stay identical)."""
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def search_term(query: str | None) -> str | None:
    """Trim a free-text query to what is searched; ``None`` when there is nothing to search."""
    if query is None:
        return None
    return query.strip()[:SEARCH_MAX] or None


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    """Paging values within ``0..PAGE_MAX``.

    Negative means zero (a negative slice would count from the end); above ``PAGE_MAX`` means
    ``PAGE_MAX`` (BSON cannot encode ints beyond 8 bytes, and no store holds that many graphs).
    """
    return min(max(limit, 0), PAGE_MAX), min(max(offset, 0), PAGE_MAX)


def summary_of(graph: GraphDefinition) -> GraphSummary:
    return GraphSummary(
        id=graph.id,
        name=graph.name,
        description=graph.description,
        tags=list(graph.tags),
        source_type=graph.source.type,
        revision=graph.revision,
        updated_at=graph.updated_at,
    )


def new_definition(data: GraphCreate, now: datetime) -> GraphDefinition:
    """A brand-new stored graph: fresh id, revision 1, both timestamps ``now``."""
    return GraphDefinition(
        id=new_graph_id(),
        name=data.name,
        description=data.description,
        tags=data.tags,
        source=data.source,
        transform=data.transform,
        style=data.style,
        schema_version=SCHEMA_VERSION,
        created_at=now,
        updated_at=now,
    )


def revised_definition(
    current: GraphDefinition, data: GraphUpdate, now: datetime
) -> GraphDefinition:
    """``current`` replaced by the editable fields of ``data``: revision + 1, ``updated_at`` now."""
    return GraphDefinition(
        id=current.id,
        name=data.name,
        description=data.description,
        tags=data.tags,
        source=data.source,
        transform=data.transform,
        style=data.style,
        schema_version=SCHEMA_VERSION,
        revision=current.revision + 1,
        created_at=current.created_at,
        updated_at=now,
    )


def stale_error(revision: int | None, updated_at: datetime | None) -> ConflictError:
    """The optimistic-concurrency failure (the stored revision moved on)."""
    return ConflictError(MSG_STALE, current_revision=revision, current_updated_at=updated_at)


def exists_error(revision: int | None, updated_at: datetime | None) -> ConflictError:
    """``put`` without ``overwrite`` found the id taken."""
    return ConflictError(MSG_EXISTS, current_revision=revision, current_updated_at=updated_at)


def validation_lines(exc: ValidationError, root: str) -> list[str]:
    """``location: message`` for every error of ``exc``; ``root`` names a model-level error.

    The offending input, the error context and the documentation URL are never included, so the
    lines can go into a response or a log (a masked URI, 2 MB of pasted text, ...).
    """
    errors = exc.errors(include_input=False, include_context=False, include_url=False)
    return [f"{'.'.join(str(part) for part in err['loc']) or root}: {err['msg']}" for err in errors]


def parse_definition(doc: dict[str, Any]) -> GraphDefinition:
    """``upgrade_doc`` + ``GraphDefinition.model_validate``; any failure is ``StorageError``."""
    prepared = upgrade_doc(doc)
    try:
        return GraphDefinition.model_validate(prepared)
    except ValidationError:
        raise StorageError(MSG_UNREADABLE) from None
