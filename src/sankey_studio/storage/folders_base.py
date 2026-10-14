"""Storage contract for library folders ("collections" in the UI).

``FolderRepository`` is the second Protocol next to ``GraphRepository``. A graph points at AT MOST
ONE folder with ``GraphDefinition.folder_id`` (``None`` = the top level); a folder is one small
record ``{id, name, parent_id, revision, timestamps}``. The rules (names, depth, count, cycles)
live in ``folder_tree``; both backends call them, so they behave the same.

* Membership is not part of the graph content: ``GraphRepository.update`` never changes it, only
  ``create(..., folder_id=)`` and ``move_graphs`` do, and a move changes neither ``revision`` nor
  ``updated_at`` of the graph.
* A ``folder_id`` that names no folder (a crash between two writes, a folder deleted while a
  graph was being moved into it) is tolerated, not prevented: such a graph reads as top level in
  every membership query.
* Ids are ``uuid4().hex``, validated with ``check_folder_id`` BEFORE any path or query use.
* Messages never contain URIs, credentials or folder names.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any, Final, Protocol

from pydantic import ValidationError

from sankey_studio.errors import ConflictError, NotFoundError, StorageError
from sankey_studio.models import GRAPH_ID_PATTERN, FolderDefinition
from sankey_studio.storage.base import upgrade_doc

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sankey_studio.models import (
        FolderCreate,
        FolderSummary,
        FolderUpdate,
        GraphSummary,
        MoveReport,
    )

#: The scope that names the top level. Not a valid id (not 32 hex digits): no clash possible.
ROOT_SCOPE: Final = "root"

MSG_NOT_FOUND = "Folder not found"
MSG_UNREADABLE = "Stored folder is unreadable"
MSG_STALE = "Collection was modified since you loaded it; reload it"
MSG_EXISTS = "A collection with this id already exists"

_FOLDER_ID_RE = re.compile(GRAPH_ID_PATTERN)


def new_folder_id() -> str:
    return uuid.uuid4().hex


def check_folder_id(folder_id: str) -> str:
    """``folder_id`` if it is a valid id; ``NotFoundError`` otherwise (``../x``, NUL, ...)."""
    if _FOLDER_ID_RE.fullmatch(folder_id) is None:
        raise NotFoundError(MSG_NOT_FOUND)
    return folder_id


def scope_id(scope: str) -> str | None:
    """The folder id a listing scope names: ``ROOT_SCOPE`` -> ``None``; anything else is an id."""
    if scope == ROOT_SCOPE:
        return None
    return check_folder_id(scope)


def parse_folder(doc: dict[str, Any]) -> FolderDefinition:
    """``upgrade_doc`` + ``FolderDefinition.model_validate``; any failure is ``StorageError``."""
    prepared = upgrade_doc(doc, "folder")
    try:
        return FolderDefinition.model_validate(prepared)
    except ValidationError:
        raise StorageError(MSG_UNREADABLE) from None


def stale_error(revision: int | None, updated_at: datetime | None) -> ConflictError:
    """The optimistic-concurrency failure of a folder (the stored revision moved on)."""
    return ConflictError(MSG_STALE, current_revision=revision, current_updated_at=updated_at)


def exists_error(revision: int | None, updated_at: datetime | None) -> ConflictError:
    """``put_folder`` without ``overwrite`` found the id taken."""
    return ConflictError(MSG_EXISTS, current_revision=revision, current_updated_at=updated_at)


class FolderRepository(Protocol):  # pragma: no mutate block - interface only, never executed
    def list_folders(self) -> list[FolderSummary]:
        """ALL folders (at most ``FOLDERS_MAX``) in ``(name key, id)`` order, with the number of
        graphs and sub-folders directly inside. Graphs with a dangling ``folder_id`` count for
        the top level only."""
        ...

    def list_definitions(self) -> list[FolderDefinition]:
        """The full records in the same order (bundle export, backend migration)."""
        ...

    def get_folder(self, folder_id: str) -> FolderDefinition:
        """Raises ``NotFoundError`` (also for a malformed id)."""
        ...

    def create_folder(self, data: FolderCreate) -> FolderDefinition:
        """Raises ``NotFoundError`` (parent), ``FolderRuleError`` (depth, count) or
        ``FolderNameTakenError``. ``revision=1``, both timestamps now."""
        ...

    def update_folder(self, folder_id: str, data: FolderUpdate) -> FolderDefinition:
        """Rename and/or move. Raises ``NotFoundError``, ``ConflictError`` when ``data.revision``
        is not the stored one, ``FolderRuleError`` (cycle, depth) or ``FolderNameTakenError``."""
        ...

    def delete_folder(self, folder_id: str) -> None:
        """Sub-folders AND graphs move up to the parent; no graph is deleted. Raises
        ``NotFoundError``, or ``FolderNameTakenError`` when a sub-folder would clash by name."""
        ...

    def put_folder(self, folder: FolderDefinition, *, overwrite: bool = False) -> FolderDefinition:
        """Store ``folder`` verbatim (backend migration, bundle import with ``keep_ids``).
        ``ConflictError`` when the id exists and ``overwrite`` is false;
        ``FolderNameTakenError`` for a name clash with ANOTHER folder; ``FolderRuleError`` for
        the count. Depth and cycles are not checked (a valid tree arrives parents first)."""
        ...

    def list_in(self, scope: str, *, limit: int = 200, offset: int = 0) -> list[GraphSummary]:
        """Graphs directly in ``scope`` (``ROOT_SCOPE`` or a folder id), newest first.
        An unknown id gives ``[]``."""
        ...

    def count_in(self, scope: str) -> int: ...

    def move_graphs(self, ids: Sequence[str], folder_id: str | None) -> MoveReport:
        """Put the graphs in ``folder_id`` (``None`` = top level). Unknown graph ids are reported
        in ``MoveReport.missing``; an unknown ``folder_id`` raises ``NotFoundError``."""
        ...

    def ping(self) -> None:
        """Raises ``StorageError`` if the backend is unreachable or unwritable."""
        ...
