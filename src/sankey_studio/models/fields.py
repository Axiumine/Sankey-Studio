# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Annotated field types and validator helpers shared by several spec models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator, Field

from sankey_studio.errors import UnsafeSourceError
from sankey_studio.models.base import (
    CATEGORY_MAX,
    FOLDER_LABEL_MAX,
    GRAPH_ID_PATTERN,
    NAME_MAX,
)
from sankey_studio.util import is_reserved_category, normalize_category

if TYPE_CHECKING:
    from collections.abc import Callable


def _name_check(v: str) -> str:
    if "\0" in v:
        raise ValueError("must not contain NUL")
    return v


#: A node name: non-empty, bounded, trimmed.
NameStr = Annotated[str, Field(min_length=1, max_length=NAME_MAX), AfterValidator(_name_check)]

#: A saved-graph id (``uuid4().hex``). Validated before any path or query use.
GraphId = Annotated[str, Field(pattern=GRAPH_ID_PATTERN)]

#: A library-folder id (same shape as a graph id). Validated before any path or query use.
FolderId = Annotated[str, Field(pattern=GRAPH_ID_PATTERN)]

#: A folder label: non-empty, bounded, trimmed, no NUL.
FolderLabel = Annotated[
    str, Field(min_length=1, max_length=FOLDER_LABEL_MAX), AfterValidator(_name_check)
]


def _user_category(v: str) -> str:
    """Normalise a user-authored category and refuse the renderer-owned names.

    Control characters (NUL included) raise inside ``normalize_category``. The length is checked
    again on the RESULT: NFC can double it (``U+0344`` -> two characters), so the ``max_length``
    constraint on the raw text is not enough.
    """
    cleaned = normalize_category(v)
    if len(cleaned) > CATEGORY_MAX:
        raise ValueError(f"category must be at most {CATEGORY_MAX} characters after normalisation")
    if is_reserved_category(cleaned):
        raise ValueError("'Uncategorized' and 'Other' are reserved names; pick another category")
    return cleaned


def _optional_user_category(v: str | None) -> str | None:
    if v is None:
        return None
    return _user_category(v) or None  # empty text means "no category"


#: A category typed by the user (manual link, entry choice, rule): normalised, never reserved.
UserCategory = Annotated[
    str, Field(min_length=1, max_length=CATEGORY_MAX), AfterValidator(_user_category)
]
#: Same, but ``None``/empty is allowed.
OptUserCategory = Annotated[
    str | None, Field(max_length=CATEGORY_MAX), AfterValidator(_optional_user_category)
]


def _safe_name(check: Callable[[str], str], value: str) -> str:
    """Run a ``mongo_safety`` name validator and report failures as plain ``ValueError``."""
    try:
        return check(value)
    except UnsafeSourceError as exc:
        raise ValueError(exc.message) from exc
