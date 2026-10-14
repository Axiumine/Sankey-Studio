"""``Stores``: the two repositories of one library, handled as a pair.

A library is the graphs AND the folders that group them. They always sit on the same backend (the
same directory, or the same Mongo database), so a candidate storage target is built, probed and
copied as one value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sankey_studio.storage.base import GraphRepository
    from sankey_studio.storage.folders_base import FolderRepository


@dataclass(frozen=True, slots=True)
class Stores:
    graphs: GraphRepository
    folders: FolderRepository

    def ping(self) -> None:
        """Probe the graph store, then the folder store.

        A missing write permission on the second Mongo collection shows up in the settings
        "test storage" probe instead of at the first folder the person creates.
        """
        self.graphs.ping()
        self.folders.ping()
