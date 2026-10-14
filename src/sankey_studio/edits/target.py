"""The consent key of a source and the effective write-back preference.

The SERVER builds the key from RESOLVED values (rule 29): the browser cannot know the default
database of a connection, and editing the connection in Settings must not silently carry a
granted consent over to another server. ``write_back.target`` stores the key verbatim when the
person agrees in the dialog; ``effective_write_back`` compares it with the key of the current
source, so switching file, collection, database or connection asks again with no extra code.

The connection part of a Mongo key is a short fingerprint of the MASKED uri and the default
database (non-secret by construction: ``mask_uri`` fails closed); the uri itself never enters it.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final, Literal

from sankey_studio.models import ManualSource, MongoSource, TextSource
from sankey_studio.util import mask_uri

if TYPE_CHECKING:
    from sankey_studio.models import AppSettings, SourceSpec

__all__ = ["display_target", "effective_write_back", "resolved_database", "write_target"]

#: Hex digits of the connection fingerprint.
FINGERPRINT_CHARS: Final = 12
_SEPARATOR: Final = "\0"


def _fingerprint(settings: AppSettings, connection: str) -> str:
    conn = settings.connection(connection)
    if conn is None:
        text = _SEPARATOR
    else:
        text = mask_uri(conn.uri.get_secret_value()) + _SEPARATOR + (conn.default_database or "")
    return hashlib.sha256(text.encode()).hexdigest()[:FINGERPRINT_CHARS]


def resolved_database(spec: MongoSource, settings: AppSettings) -> str:
    """The database the source reads: its own, else the default of the connection, else ``""``."""
    if spec.database is not None:
        return spec.database
    conn = settings.connection(spec.connection)
    return (conn.default_database if conn is not None else None) or ""


def write_target(spec: SourceSpec, settings: AppSettings) -> str | None:
    """``file:<path>`` or ``mongo:<connection>/<database>/<collection>#<fingerprint>``.

    ``None`` for pasted text and manual links: they live in the graph and need no consent.
    """
    if isinstance(spec, TextSource) and spec.origin == "file":
        return f"file:{spec.path}"
    if isinstance(spec, MongoSource):
        where = f"{spec.connection}/{resolved_database(spec, settings)}/{spec.collection}"
        return f"mongo:{where}#{_fingerprint(settings, spec.connection)}"
    return None


def effective_write_back(
    spec: SourceSpec, settings: AppSettings
) -> Literal["ask", "source", "graph"]:
    """The saved preference when it was given for THIS target, else ``ask``."""
    if isinstance(spec, ManualSource) or spec.write_back is None:
        return "ask"
    if spec.write_back.target != write_target(spec, settings):
        return "ask"
    return spec.write_back.mode


def display_target(spec: SourceSpec, settings: AppSettings) -> str | None:
    """Text for the dialog: ``budget/2025.csv`` or ``main / shop.flows``; ``None`` for no target."""
    if isinstance(spec, TextSource) and spec.origin == "file":
        return spec.path
    if isinstance(spec, MongoSource):
        database = resolved_database(spec, settings)
        place = f"{database}.{spec.collection}" if database else spec.collection
        return f"{spec.connection} / {place}"
    return None
