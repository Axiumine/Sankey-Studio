"""Library folders (shown as "collections"): a tree that groups saved graphs.

The identifier noun is ``folder`` everywhere in code; the UI says "collection".
"""

from __future__ import annotations

from pydantic import AwareDatetime, ConfigDict, Field

from sankey_studio.models.base import SCHEMA_VERSION, _Model
from sankey_studio.models.fields import FolderId, FolderLabel, GraphId


class FolderCreate(_Model):
    """Body of ``POST /folders``: a label and the parent (``None`` = the top level)."""

    name: FolderLabel
    parent_id: FolderId | None = None


class FolderUpdate(FolderCreate):
    """Rename and/or move a folder; ``revision`` is the one the client last saw (CAS)."""

    revision: int = Field(ge=1)


class FolderDefinition(FolderCreate):
    """The PERSISTED shape of a folder (never a request body).

    Unknown top-level fields are ignored, like ``GraphDefinition``, so a later version can add
    one without making every stored folder unreadable.
    """

    model_config = ConfigDict(extra="ignore")

    id: FolderId
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    revision: int = Field(default=1, ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class FolderSummary(_Model):
    """A folder as listed: with the number of graphs and sub-folders directly inside."""

    id: FolderId
    name: str
    parent_id: FolderId | None
    revision: int
    updated_at: AwareDatetime
    graph_count: int = Field(ge=0)
    child_count: int = Field(ge=0)


class MoveReport(_Model):
    """Answer of ``POST /graphs/move``: how many graphs moved and which ids do not exist."""

    moved: int = Field(ge=0)
    missing: list[GraphId]
