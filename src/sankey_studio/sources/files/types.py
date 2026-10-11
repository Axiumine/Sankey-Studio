"""Value types of the managed-files API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - field type, kept importable at runtime
from pathlib import Path  # noqa: TC003 - field type, kept importable at runtime


@dataclass(frozen=True, slots=True)
class SourceFileInfo:
    """A managed source file: its name relative to the sources dir (POSIX), size and mtime (UTC)."""

    name: str
    size: int
    modified: datetime


@dataclass(frozen=True, slots=True)
class SaveRequest:
    """Arguments of ``save_stream`` (``max_bytes`` is the largest accepted upload)."""

    sources_dir: Path
    filename: str
    max_bytes: int
    overwrite: bool = False
