"""Wire models of the library folders ("collections" in the UI).

``FolderList`` is the answer of ``GET /folders``; ``MoveGraphsIn`` is the body of
``POST /graphs/move``. The folder records themselves (``FolderCreate``, ``FolderUpdate``,
``FolderDefinition``, ``FolderSummary``, ``MoveReport``) are models of the package ``models``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sankey_studio.models import FolderId, FolderSummary, GraphId
from sankey_studio.web.schemas.queries import EXPORT_IDS_MAX

__all__ = ["MOVE_IDS_MAX", "FolderList", "MoveGraphsIn"]

#: Graphs in one move (the same cap as one bundle export).
MOVE_IDS_MAX = EXPORT_IDS_MAX
MSG_REPEATED_IDS = "ids must not repeat a graph"


class FolderList(BaseModel):
    """``GET /folders``: every folder (at most ``FOLDERS_MAX``) in ``(name, id)`` order."""

    model_config = ConfigDict(extra="forbid")

    items: list[FolderSummary]


class MoveGraphsIn(BaseModel):
    """Body of ``POST /graphs/move``: 1..200 distinct graph ids and the folder they go to.

    ``folder_id`` is required: ``null`` names the top level, so a body that forgot the key is a
    422 instead of a silent move out of a folder.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    ids: Annotated[list[GraphId], Field(min_length=1, max_length=MOVE_IDS_MAX)]
    folder_id: FolderId | None

    @field_validator("ids")
    @classmethod
    def _distinct(cls, ids: list[str]) -> list[str]:
        if len(set(ids)) != len(ids):
            raise ValueError(MSG_REPEATED_IDS)
        return ids
