"""Builders for the bundle-with-folders tests (not a test module)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sankey_studio.storage.bundle import BUNDLE_FORMAT, BUNDLE_VERSION
from tests.storage.folder_builders import fid, folder
from tests.storage.support import definition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sankey_studio.storage.base import GraphRepository
    from sankey_studio.storage.folders_base import FolderRepository


def graph_dump(graph_id: str, name: str, folder_number: int | None = None) -> dict[str, Any]:
    """A bundle graph; ``folder_number`` names the folder it sits in (``fid`` of that number)."""
    dump = definition(graph_id, name).model_dump(mode="json")
    dump["folder_id"] = None if folder_number is None else fid(folder_number)
    return dump


def folder_dump(number: int, name: str, parent: int | None = None) -> dict[str, Any]:
    """A bundle folder with id ``fid(number)`` below ``fid(parent)`` (``None`` = top level)."""
    return folder(number, name, parent).model_dump(mode="json")


def bundle_of(graphs: Sequence[Any] = (), folders: Sequence[Any] = ()) -> dict[str, Any]:
    """A v2 bundle document."""
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "graphs": list(graphs),
        "folders": list(folders),
    }


def tree_of(folders: FolderRepository) -> dict[str, str | None]:
    """``{folder name: parent name}`` of the stored folders (names are unique in the tests)."""
    stored = folders.list_definitions()
    names = {f.id: f.name for f in stored}
    return {f.name: names.get(f.parent_id) if f.parent_id else None for f in stored}


def home_of(graphs: GraphRepository, folders: FolderRepository) -> dict[str, str | None]:
    """``{graph name: name of the folder it sits in}``; ``None`` is the top level."""
    names = {f.id: f.name for f in folders.list_definitions()}
    return {
        g.name: names.get(g.folder_id) if g.folder_id else None for g in graphs.iter_definitions()
    }
