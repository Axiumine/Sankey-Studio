# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Versioned URLs of the files under ``web/static``: the cache-busting half of the cache policy.

``UncachedStaticFiles`` answers ``Cache-Control: no-store``, but a browser that stored a file
before that header existed keeps reusing it, without asking, until its heuristic freshness runs
out (hours). The pages therefore link every style sheet, script and icon under a version prefix,
``/static/v-<digest>/<name>``: ``<digest>`` follows the content of the whole static directory, so
a changed tree is a new URL namespace that no browser has ever stored. Scripts import each other
with relative paths and load their style sheets relative to ``import.meta.url``, so every file a
page pulls in (nested modules included) lives under the same prefix. The static mount drops the
prefix (``unversioned``, any digest) before the lookup; the plain ``/static/<name>`` still works.

The digest is computed once per process: an upgrade or an edit takes effect in the namespace at the
next server start, and the files themselves are never stored by the browser in between.

``static_url`` is a Jinja global (registered in ``routers.pages``).
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import cache
from pathlib import Path
from typing import Final

STATIC_DIR: Final = Path(__file__).parent / "static"
STATIC_URL: Final = "/static"
#: Hex characters of the SHA-256 digest kept in the URL (48 bits: plenty to tell versions apart).
DIGEST_LENGTH: Final = 12
#: The first path segment of a versioned static URL.
VERSION_SEGMENT: Final = re.compile(rf"v-[0-9a-f]{{{DIGEST_LENGTH}}}")


@cache
def tree_version(root: Path) -> str:
    """Digest of every file under ``root``: relative path and content (path only if unreadable)."""
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"\0unreadable")
        digest.update(b"\0")
    return digest.hexdigest()[:DIGEST_LENGTH]


def static_url(name: str) -> str:
    """``/static/v-<digest>/<name>``: the URL of a static file under the current version."""
    return f"{STATIC_URL}/v-{tree_version(STATIC_DIR)}/{name}"


def unversioned(path: str) -> str:
    """``path`` (relative to the static directory) without its leading ``v-<digest>`` segment."""
    head, sep, rest = path.partition(os.sep)
    return rest if sep and VERSION_SEGMENT.fullmatch(head) else path
