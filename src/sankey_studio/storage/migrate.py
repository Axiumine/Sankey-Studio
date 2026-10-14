"""Moving graphs and folders between stores: backend migration and JSON bundles."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from sankey_studio.errors import ConflictError, FolderNameTakenError
from sankey_studio.storage.bundle import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    MAX_BUNDLE_GRAPHS,
    BundleError,
    ImportMode,
    ImportReport,
    export_bundle,
    import_bundle,
)
from sankey_studio.storage.folder_tree import order_parents_first

if TYPE_CHECKING:
    from sankey_studio.storage.base import GraphRepository
    from sankey_studio.storage.folders_base import FolderRepository
    from sankey_studio.storage.stores import Stores

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "MAX_BUNDLE_GRAPHS",
    "MAX_UNREADABLE_IDS",
    "BundleError",
    "CopyReport",
    "FolderCopy",
    "ImportMode",
    "ImportReport",
    "copy_folders",
    "copy_graphs",
    "copy_library",
    "export_bundle",
    "import_bundle",
]

logger = logging.getLogger(__name__)

#: ``on_conflict`` -> the ``overwrite`` flag of ``put``; an unknown word is a ``KeyError``.
_OVERWRITE = {"skip": False, "overwrite": True}
#: At most this many ids of unreadable source graphs are named in a ``CopyReport``.
MAX_UNREADABLE_IDS = 50


@dataclass(frozen=True, slots=True)
class CopyReport:
    """``copied`` graphs written to the destination, ``skipped`` ones it already had.

    ``unreadable`` source graphs (damaged, or written by a newer version) cannot be copied and
    stay behind in the source; the first ``MAX_UNREADABLE_IDS`` of them are named in
    ``unreadable_ids``. ``folders`` library folders were copied and ``folders_skipped`` were not
    (``copy_library`` only; both stay 0 for a graphs-only ``copy_graphs``).
    """

    copied: int
    skipped: int
    unreadable: int = 0
    unreadable_ids: tuple[str, ...] = ()
    folders: int = 0
    folders_skipped: int = 0


@dataclass(frozen=True, slots=True)
class FolderCopy:
    """Folders written to the destination, and folders it already had or refused by name."""

    copied: int
    skipped: int


def copy_graphs(
    src: GraphRepository,
    dst: GraphRepository,
    *,
    on_conflict: Literal["skip", "overwrite"] = "skip",
) -> CopyReport:
    """Copy every readable graph of ``src`` into ``dst`` verbatim (ids, revisions, timestamps).

    ``skip`` leaves graphs the destination already has alone (and counts them); ``overwrite``
    replaces them. ``src`` is never modified. A backend failure aborts the copy (the exception
    propagates; whatever was copied stays, ``put`` is idempotent so a retry is safe). Source
    graphs that cannot be read are not copied: they are counted in the report and logged.
    """
    overwrite = _OVERWRITE[on_conflict]
    copied = skipped = 0
    for graph in src.iter_definitions():
        try:
            dst.put(graph, overwrite=overwrite)
        except ConflictError:
            skipped += 1
        else:
            copied += 1
    left_behind = src.unreadable_ids()
    if left_behind:
        logger.warning("%d stored graph(s) are unreadable and were not copied", len(left_behind))
    return CopyReport(copied, skipped, len(left_behind), tuple(left_behind[:MAX_UNREADABLE_IDS]))


def copy_folders(
    src: FolderRepository,
    dst: FolderRepository,
    *,
    on_conflict: Literal["skip", "overwrite"] = "skip",
) -> FolderCopy:
    """Copy every folder of ``src`` into ``dst`` verbatim (ids, revisions, timestamps).

    Parents go first, so a copied tree is complete at every step. A folder the destination
    already has (same id, ``skip``) or one whose name a sibling of ANOTHER id already uses there is
    skipped and counted; neither aborts the copy. Graphs keep their ``folder_id``, so the graphs
    of a skipped folder read as top level in the destination. A backend failure, or the folder
    count limit, aborts the copy (``put_folder`` is idempotent, so a retry is safe).
    """
    overwrite = _OVERWRITE[on_conflict]
    copied = skipped = 0
    for folder in order_parents_first(src.list_definitions()):
        try:
            dst.put_folder(folder, overwrite=overwrite)
        except ConflictError, FolderNameTakenError:
            skipped += 1
        else:
            copied += 1
    return FolderCopy(copied, skipped)


def copy_library(
    src: Stores,
    dst: Stores,
    *,
    on_conflict: Literal["skip", "overwrite"] = "skip",
) -> CopyReport:
    """Copy the folders first, then the graphs; the report carries both counts."""
    folders = copy_folders(src.folders, dst.folders, on_conflict=on_conflict)
    report = copy_graphs(src.graphs, dst.graphs, on_conflict=on_conflict)
    return replace(report, folders=folders.copied, folders_skipped=folders.skipped)
