# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Upload filename validation."""

from __future__ import annotations

import unicodedata

from sankey_studio.errors import SourceError, UnsafeSourceError
from sankey_studio.sources.files.paths import check_extension

NAME_MAX_BYTES = 255
#: Control, format (bidi overrides, zero-width) and surrogate characters are never allowed.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


def clean_filename(raw: str) -> str:
    """The stored name for an uploaded ``raw`` filename, or an error.

    NFC-normalised (not trimmed), no control/format characters, no path separators (basename
    only), leading dots stripped, at most 255 UTF-8 bytes, and an extension of
    ``ALLOWED_EXTENSIONS`` (compared casefolded).
    """
    name = unicodedata.normalize("NFC", raw)
    if any(unicodedata.category(char) in _FORBIDDEN_CATEGORIES for char in name):
        raise SourceError("filename must not contain control or formatting characters")
    if "/" in name or "\\" in name:
        raise UnsafeSourceError("filename must be a plain name without path separators")
    name = name.lstrip(".")
    if not name:
        raise SourceError("filename is empty")
    if len(name.encode("utf-8")) > NAME_MAX_BYTES:
        raise SourceError(f"filename is longer than {NAME_MAX_BYTES} bytes")
    check_extension(name)
    return name
