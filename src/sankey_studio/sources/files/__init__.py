"""The managed sources directory: safe paths, upload names, and the list/save/delete/preview API.

``sankey_studio.sources.files`` is the import path the web layer uses.
"""

from __future__ import annotations

from sankey_studio.sources.files.names import clean_filename
from sankey_studio.sources.files.paths import (
    ALLOWED_EXTENSIONS,
    open_binary,
    resolve_source_path,
)
from sankey_studio.sources.files.store import delete_file, list_files, preview_file, save_stream
from sankey_studio.sources.files.types import SaveRequest, SourceFileInfo

__all__ = [
    "ALLOWED_EXTENSIONS",
    "SaveRequest",
    "SourceFileInfo",
    "clean_filename",
    "delete_file",
    "list_files",
    "open_binary",
    "preview_file",
    "resolve_source_path",
    "save_stream",
]
