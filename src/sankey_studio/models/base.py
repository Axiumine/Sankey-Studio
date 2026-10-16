# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Constants and the ``_Model`` base class shared by every spec model."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

# --------------------------------------------------------------------------- constants

NAME_MAX = 200
TAG_MAX = 40
CATEGORY_MAX = 100
#: A graph keeps at most this many distinct categories; later ones become uncategorised (+ warning).
MAX_CATEGORIES = 200
#: Render-time labels for the synthetic buckets. Reserved: no real category can carry them.
UNCATEGORIZED = "Uncategorized"
OTHER = "Other"
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
GRAPH_ID_PATTERN = r"^[0-9a-f]{32}$"
SCHEMA_VERSION = 1
CONNECTION_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
FIELD_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*$")
_VALUE_FORMAT_RE = re.compile(r"^[-+ ,.~$%a-zA-Z0-9]{0,24}$")

MAX_INLINE_CHARS = 2_000_000
MAX_MANUAL_LINKS = 5_000
MAX_ENTRY_CATEGORIES = 20_000
MAX_MERGE_NODES = 5_000
MAX_HIDE_NODES = 1_000
MAX_COLOR_OVERRIDES = 1_000
#: Extra (graph-only) flows kept in ``TransformSpec.extra_links``.
MAX_EXTRA_LINKS = 2_000
#: Names kept in ``StyleSpec.node_order``.
MAX_NODE_ORDER = 5_000
#: Longest opaque write-back target key (``WriteBackPref.target``).
WRITE_TARGET_MAX = 400
#: Library folders ("collections" in the UI): label length, nesting depth and total count.
FOLDER_LABEL_MAX = 100
FOLDER_DEPTH_MAX = 8
FOLDERS_MAX = 1_000
#: ``entries`` preview rows in a ``RenderBundle``; the full list is paged via ``POST /entries``.
ENTRIES_PREVIEW_LIMIT = 2_000
ENTRIES_PAGE_MAX = 500

#: array typecodes of the ``SankeyGraph`` columns. Signed on purpose: ``-1`` = uncategorised.
INDEX_TYPECODE = "i"
VALUE_TYPECODE = "d"


class _Model(BaseModel):
    """Base of every spec: strict input, trimmed strings, no unknown fields.

    ``hide_input_in_errors`` keeps the offending input (a URI with a password, 2 MB of pasted
    text) out of ``str(ValidationError)``; the API's 422 handler also drops ``input``/``ctx``
    via ``exc.errors(include_input=False, include_context=False, include_url=False)``.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        hide_input_in_errors=True,
    )
