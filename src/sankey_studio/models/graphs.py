"""Saved-graph shapes: drafts, create/update bodies, the persisted definition, summaries."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, field_validator

from sankey_studio.models.base import NAME_MAX, SCHEMA_VERSION, TAG_MAX, _Model
from sankey_studio.models.fields import FolderId, GraphId
from sankey_studio.models.sources import SourceSpec
from sankey_studio.models.style import StyleSpec
from sankey_studio.models.transform import TransformSpec


class GraphDraft(_Model):
    """Everything needed to draw a graph, saved or not."""

    source: SourceSpec
    transform: TransformSpec = Field(default_factory=TransformSpec)
    style: StyleSpec = Field(default_factory=StyleSpec)


class GraphCreate(GraphDraft):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(t.strip() for t in v if t.strip()))
        if any(len(t) > TAG_MAX for t in cleaned):
            raise ValueError(f"tags are limited to {TAG_MAX} characters")
        return cleaned


class GraphUpdate(GraphCreate):
    #: Revision the client last saw; a mismatch raises ``ConflictError``.
    revision: int = Field(ge=1)


class GraphDefinition(GraphCreate):
    """The PERSISTED shape of a saved graph (never a request body).

    Unknown top-level fields are ignored so a later version can add or drop one without making
    every saved graph unreadable; repositories also strip ``_id`` and run ``upgrade_doc`` first.
    """

    model_config = ConfigDict(extra="ignore")

    id: GraphId
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    revision: int = Field(default=1, ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    #: The library folder ("collection") the graph sits in; ``None`` = the top level.
    folder_id: FolderId | None = None


class GraphSummary(_Model):
    id: GraphId
    name: str
    description: str
    tags: list[str]
    source_type: Literal["manual", "text", "mongo"]
    revision: int
    updated_at: AwareDatetime
    folder_id: FolderId | None = None
