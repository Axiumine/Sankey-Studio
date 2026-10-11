"""Moving graphs between stores: backend migration and JSON bundles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sankey_studio.errors import ConflictError
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

if TYPE_CHECKING:
    from sankey_studio.storage.base import GraphRepository

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "MAX_BUNDLE_GRAPHS",
    "MAX_UNREADABLE_IDS",
    "BundleError",
    "CopyReport",
    "ImportMode",
    "ImportReport",
    "copy_graphs",
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
    ``unreadable_ids``.
    """

    copied: int
    skipped: int
    unreadable: int = 0
    unreadable_ids: tuple[str, ...] = ()


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
