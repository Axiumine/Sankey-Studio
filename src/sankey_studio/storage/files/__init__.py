# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""File-backed stores: graphs (one JSON file each) and library folders (``folders.json``).

Atomic writes, process-wide locking; both repositories of one directory share one lock.
"""

from __future__ import annotations

from sankey_studio.storage.files.folders import FileFolderRepository
from sankey_studio.storage.files.repo import FileGraphRepository

__all__ = ["FileFolderRepository", "FileGraphRepository"]
