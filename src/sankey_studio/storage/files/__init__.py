"""File-backed graph store (one JSON file per graph, atomic writes, process-wide locking)."""

from __future__ import annotations

from sankey_studio.storage.files.repo import FileGraphRepository

__all__ = ["FileGraphRepository"]
