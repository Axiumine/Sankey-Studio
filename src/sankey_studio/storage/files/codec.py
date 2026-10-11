"""Reading and writing one ``<id>.json`` graph file."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sankey_studio.errors import StorageError
from sankey_studio.storage.atomic import read_file_nofollow
from sankey_studio.storage.common import MSG_UNREADABLE, parse_definition

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import GraphDefinition

GRAPH_SUFFIX = ".json"
#: A graph may hold 2 MB of pasted text, 20k entry choices and 5k manual links.
MAX_GRAPH_BYTES = 32 * 1024 * 1024
MSG_TOO_LARGE = "The graph is too large to save"


def graph_filename(graph_id: str) -> str:
    return f"{graph_id}{GRAPH_SUFFIX}"


def encode_graph(graph: GraphDefinition) -> bytes:
    """The plain model dump as ASCII JSON (lone surrogates are escaped, never encoded).

    The write cap is the read cap (``MAX_GRAPH_BYTES``): a file this module writes can always be
    read back. A longer document is a ``StorageError`` before any byte reaches the disk.
    """
    data = json.dumps(graph.model_dump(mode="json"), indent=2, allow_nan=False).encode("ascii")
    if len(data) > MAX_GRAPH_BYTES:
        raise StorageError(MSG_TOO_LARGE)
    return data


def read_graph(path: Path) -> GraphDefinition:
    """Load and validate one graph file.

    ``FileNotFoundError`` propagates (the caller decides: not found, or vanished meanwhile);
    everything else that is wrong with the file is a ``StorageError`` with a fixed message.
    """
    try:
        raw = read_file_nofollow(path, MAX_GRAPH_BYTES)
    except FileNotFoundError:
        raise
    except OSError:
        raise StorageError(MSG_UNREADABLE) from None
    try:
        doc = json.loads(raw)
    except ValueError, RecursionError:
        raise StorageError(MSG_UNREADABLE) from None
    if not isinstance(doc, dict):
        raise StorageError(MSG_UNREADABLE)
    graph = parse_definition(doc)
    if graph.id != path.stem:  # a file may only hold the graph its name says
        raise StorageError(MSG_UNREADABLE)
    return graph
