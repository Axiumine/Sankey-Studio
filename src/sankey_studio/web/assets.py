"""Versioned URLs of the files under ``web/static``: the cache-busting half of the cache policy.

``RevalidatedStaticFiles`` answers ``Cache-Control: no-cache``, but a browser that stored a file
before that header existed keeps reusing it until its heuristic freshness runs out. The pages
(``Cache-Control: no-store``) therefore link every style sheet, script and icon as
``/static/<name>?v=<digest>``: the digest follows the content, so a changed file is a new URL for
every browser, whatever it cached before. The static mount ignores the query string.

``static_url`` is a Jinja global (registered in ``routers.pages``). A name that is not a regular
file inside the static directory gets the plain URL: the page still renders and the link 404s.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import os

STATIC_DIR: Final = Path(__file__).parent / "static"
STATIC_URL: Final = "/static"
#: Hex characters of the SHA-256 digest kept in the URL (48 bits: plenty to tell versions apart).
DIGEST_LENGTH: Final = 12

#: path -> ((mtime_ns, size), digest). The digest is read again only when the stat changes.
_digests: dict[Path, tuple[tuple[int, int], str]] = {}


def _digest(path: Path, info: os.stat_result) -> str:
    """The content digest of ``path``, reused while its modification time and size stay put."""
    key = (info.st_mtime_ns, info.st_size)
    cached = _digests.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_LENGTH]
    _digests[path] = (key, digest)
    return digest


def _version(name: str) -> str | None:
    """The digest of the static file ``name``, or None when it is not a file of the directory."""
    root = STATIC_DIR.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        return None
    try:
        info = path.stat()
        return _digest(path, info) if stat.S_ISREG(info.st_mode) else None
    except OSError:
        return None


def static_url(name: str) -> str:
    """``/static/<name>?v=<digest>``; plain ``/static/<name>`` when the file cannot be read."""
    url = f"{STATIC_URL}/{name}"
    version = _version(name)
    return url if version is None else f"{url}?v={version}"
