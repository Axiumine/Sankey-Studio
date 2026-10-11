"""Security building blocks shared by the middleware, the error handlers and the routers.

* ``HeaderPolicy`` / ``DEFAULT_POLICY``: the response headers every answer carries (the CSP of
  SPEC section 6 and friends) plus ``Cache-Control: no-store`` for ``/api``.
* ``BodyLimits``: per-route request-body caps (counted by ``middleware.BodySizeLimit`` while the
  body streams in, never trusted from ``Content-Length``). The upload cap follows the live
  ``max_upload_mb`` setting and the upload route is refused outright in read-only remote mode.
* ``host_pattern_problem``: why an ``allowed_hosts`` entry would never work (or would make
  Starlette's ``TrustedHostMiddleware`` assert), checked at start-up by ``create_app``.
* ``Download`` / ``download_response`` / ``content_disposition``: the ONE way a route serves a
  file. Every download is an attachment, ``nosniff`` and ``CSP: sandbox`` (an HTML or SVG export
  opened from the download list must not run in the origin of the app).
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Callable

MIB: Final = 2**20

#: Content-Security-Policy of every response (SPEC section 6): local assets only, no framing.
CSP: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)
#: CSP of a download: the file is rendered in a sandbox with no origin, no scripts.
SANDBOX_CSP: Final = "sandbox"
API_PREFIX: Final = "/api/"

#: Routes whose body cap differs from the JSON cap (the upload is the one multipart route).
UPLOAD_PATH: Final = "/api/v1/sources/files"
IMPORT_PATH: Final = "/api/v1/graphs/import"
#: ``AppSettings.max_upload_mb`` is editable at runtime and tops out at 100 MiB. The upload cap is
#: ``max_upload_mb`` plus 1 MiB of multipart framing, read per request; this ceiling is only the
#: static fallback of a ``BodyLimits`` that has no live setting to read.
UPLOAD_CEILING_MB: Final = 100
UPLOAD_FRAMING_BYTES: Final = MIB
JSON_BODY_BYTES: Final = 8 * MIB
#: Twice the JSON cap on purpose: a bundle of many graphs can be bigger than any one JSON body.
IMPORT_BODY_BYTES: Final = 16 * MIB
UPLOAD_BODY_BYTES: Final = UPLOAD_CEILING_MB * MIB + UPLOAD_FRAMING_BYTES

FALLBACK_NAME: Final = "graph"
FALLBACK_NAME_MAX: Final = 80
#: ``quote(..., safe=...)`` argument that leaves nothing unescaped (the default keeps "/").
QUOTE_EVERYTHING: Final = ""
#: Header names of a download. ``Response`` lower-cases them, so a changed spelling is invisible.
DISPOSITION_HEADER: Final = "content-disposition"
DOWNLOAD_HEADERS: Final = {
    "x-content-type-options": "nosniff",
    "content-security-policy": SANDBOX_CSP,
}
_UNSAFE_NAME_CHARS: Final = re.compile(r"[^A-Za-z0-9._-]+")
_UNSAFE_EXT_CHARS: Final = re.compile(r"[^A-Za-z0-9]")
#: An ``allowed_hosts`` entry: ``*``, a name or IPv4 address (``*.example.com`` allowed), or a
#: bracketed IPv6 address. No scheme, port or path: ``TrustedHostMiddleware`` matches the host only.
_HOST_PATTERN: Final = re.compile(r"\*|(\*\.)?[A-Za-z0-9._-]+|\[[0-9A-Fa-f:.]+]")
MSG_HOST_PATTERN: Final = (
    "must be a bare host name or address: no scheme, port or path, a wildcard only as "
    "'*.example.com', an IPv6 address in brackets"
)

Header = tuple[str, str]


@dataclass(frozen=True, slots=True)
class HeaderPolicy:
    """Headers added to a response unless the route already set them (``setdefault``)."""

    everywhere: tuple[Header, ...]
    api_only: tuple[Header, ...] = ()
    api_prefix: str = API_PREFIX

    def for_path(self, path: str) -> list[Header]:
        """The headers wanted on a response to ``path``."""
        extra = self.api_only if path.startswith(self.api_prefix) else ()
        return [*self.everywhere, *extra]


DEFAULT_POLICY: Final = HeaderPolicy(
    everywhere=(
        ("Content-Security-Policy", CSP),
        ("X-Content-Type-Options", "nosniff"),
        # fetch-only UI: "no-referrer" would make browsers send "Origin: null" on same-site POSTs
        ("Referrer-Policy", "same-origin"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
    ),
    api_only=(("Cache-Control", "no-store"),),
)


@dataclass(frozen=True, slots=True)
class BodyLimits:
    """Request-body caps in bytes: the JSON routes, the bundle import and the one upload.

    ``upload_mb`` reads the live ``max_upload_mb`` setting (it is editable at runtime); without
    it the upload cap is the static ``upload_bytes``. ``writes_allowed`` False refuses every
    unsafe request to the upload route before a byte of its body is read.
    """

    json_bytes: int = JSON_BODY_BYTES
    import_bytes: int = IMPORT_BODY_BYTES
    upload_bytes: int = UPLOAD_BODY_BYTES
    upload_mb: Callable[[], int] | None = None
    writes_allowed: bool = True

    def limit_for(self, path: str) -> int:
        """The static cap for a request to ``path`` (exact match; else a JSON route)."""
        if path == IMPORT_PATH:
            return self.import_bytes
        if path == UPLOAD_PATH:
            return self.upload_bytes
        return self.json_bytes

    def upload_limit(self) -> int:
        """The cap of the upload route right now: ``max_upload_mb`` plus the multipart framing.

        Reads the settings (file I/O): call it off the event loop. Errors of the setting
        provider propagate.
        """
        if self.upload_mb is None:
            return self.upload_bytes
        return self.upload_mb() * MIB + UPLOAD_FRAMING_BYTES


def host_pattern_problem(pattern: str) -> str | None:
    """Why ``pattern`` is not a usable ``allowed_hosts`` entry, ``None`` when it is."""
    return None if _HOST_PATTERN.fullmatch(pattern) else MSG_HOST_PATTERN


@dataclass(frozen=True, slots=True)
class Download:
    """A file to serve: ``name`` is the user's text (a graph name), ``ext`` the file extension."""

    body: bytes | str
    media_type: str
    name: str
    ext: str


def content_disposition(name: str, ext: str) -> str:
    """``attachment`` header with an ASCII fallback and an RFC 5987 UTF-8 name.

    The fallback keeps ``[A-Za-z0-9._-]`` (runs of anything else become ``_``, at most 80
    characters, ``graph`` when nothing is left), so quotes, ``;`` and CR/LF never reach the header.
    The ``filename*`` form carries the same name, percent-encoded.
    """
    fallback = _UNSAFE_NAME_CHARS.sub("_", name)[:FALLBACK_NAME_MAX] or FALLBACK_NAME
    suffix = _UNSAFE_EXT_CHARS.sub("", ext)
    shown = name[:FALLBACK_NAME_MAX] or FALLBACK_NAME
    full = urllib.parse.quote(shown, safe=QUOTE_EVERYTHING, errors="replace")
    return f"attachment; filename=\"{fallback}.{suffix}\"; filename*=UTF-8''{full}.{suffix}"


def download_response(download: Download) -> Response:
    """The shared response for every export: attachment, ``nosniff``, ``CSP: sandbox``."""
    return Response(
        content=download.body,
        media_type=download.media_type,
        headers={
            **DOWNLOAD_HEADERS,
            DISPOSITION_HEADER: content_disposition(download.name, download.ext),
        },
    )
