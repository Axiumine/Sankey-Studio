# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Builders for folder tests (not a test module): ids, folder records, create bodies."""

from __future__ import annotations

from sankey_studio.models import FolderCreate, FolderDefinition
from tests.storage.support import NOW


def fid(number: int) -> str:
    """A valid folder id with a known sort order (``fid(1) < fid(2)``)."""
    return f"{number:032x}"


def folder(
    number: int, name: str, parent: int | None = None, *, revision: int = 1
) -> FolderDefinition:
    """A stored folder: id ``fid(number)``, parent ``fid(parent)`` (``None`` = top level)."""
    return FolderDefinition(
        id=fid(number),
        name=name,
        parent_id=None if parent is None else fid(parent),
        revision=revision,
        created_at=NOW,
        updated_at=NOW,
    )


def body(name: str, parent: str | None = None) -> FolderCreate:
    """The body of a ``create_folder`` call."""
    return FolderCreate(name=name, parent_id=parent)
