"""Pure ASGI middleware: host check, body-size limiter, security headers and the CSRF guard.

Pure ASGI on purpose: ``BaseHTTPMiddleware`` buffers or re-reads bodies and would defeat the
streaming byte count. Each class is built as ``(app, one_bundle)`` and passes every non-``http``
scope (lifespan, websocket) straight through. Order (outermost first, see ``app.create_app``):
host check, body-size limiter, security headers, CSRF guard.

The host check is Starlette's ``TrustedHostMiddleware`` made case-insensitive: host names are
(RFC 9110), and ``allowed_hosts=["MyServer.Local"]`` must accept the ``myserver.local`` a browser
sends as well as the ``MYSERVER.LOCAL`` a script may. The app below sees a lower-case ``Host``.

The body-size limiter also guards the one upload route, before anything is read: the cap is the
live ``max_upload_mb`` setting plus 1 MiB, and in remote read-only mode every unsafe request to it
is answered 403 ``read_only_mode`` without touching the body (FastAPI would otherwise parse and
spool a 100 MiB multipart to disk before its ``require_writes`` dependency refuses it).

CSRF rule (SPEC section 6), applied to POST, PUT, PATCH and DELETE on every path: allowed iff
``Sec-Fetch-Site`` is ``same-origin`` or ``none``, OR ``Origin`` equals the request's own origin
and its host is in ``allowed_hosts``; with NEITHER header the client is not a browser and may only
send ``application/json``. Then the content type is enforced (415).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import ClientDisconnect

from sankey_studio.errors import (
    ForbiddenError,
    PayloadTooLargeError,
    ReadOnlyModeError,
    SankeyError,
    UnsupportedMediaTypeError,
)
from sankey_studio.web.deps import MSG_READ_ONLY
from sankey_studio.web.errors import sankey_response
from sankey_studio.web.security import API_PREFIX, DEFAULT_POLICY, UPLOAD_PATH

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from sankey_studio.web.security import BodyLimits, HeaderPolicy

UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SAME_ORIGIN_SITES: Final = frozenset({"same-origin", "none"})
JSON_TYPE: Final = "application/json"
MULTIPART_TYPE: Final = "multipart/form-data"
#: Header names as constants: ``Headers`` compares them case-insensitively, so a changed spelling
#: would be a mutant no test can see.
CONTENT_LENGTH: Final = "content-length"
CONTENT_TYPE: Final = "content-type"
TRANSFER_ENCODING: Final = "transfer-encoding"
SEC_FETCH_SITE: Final = "sec-fetch-site"
ORIGIN: Final = "origin"
HOST: Final = "host"
#: The same name as it appears in ``scope["headers"]`` (lower-case bytes, per ASGI).
HOST_KEY: Final = b"host"
#: The ASGI default of ``scope["scheme"]`` (a server may leave it out).
DEFAULT_SCHEME: Final = "http"
DEFAULT_PORTS: Final = {"http": 80, "https": 443}
MSG_CROSS_ORIGIN: Final = "Cross-origin request refused"
MSG_MEDIA_TYPE: Final = "The request body must be application/json"
MSG_TOO_LARGE: Final = "The request body is too large"

#: ``(scheme, host, port)`` of an origin; the host is lower case and without brackets.
Origin = tuple[str, str, int]


# --------------------------------------------------------------------------- body size


def _declared_length(headers: Headers) -> int | None:
    """The ``Content-Length`` as an int, ``None`` when absent or not a plain number."""
    value = headers.get(CONTENT_LENGTH)
    return int(value) if value is not None and value.isascii() and value.isdigit() else None


class _CountingStream:
    """Counts request bytes as the app reads them and answers 413 once over ``limit``.

    The app is told about the refusal with ``http.disconnect`` (whatever it then raises or sends
    is dropped: the client already has its 413). A response that already started cannot be
    replaced, so then the app only sees the disconnect.
    """

    def __init__(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        self._scope = scope
        self._receive = receive
        self._send = send
        self._limit = limit
        self._received = 0
        self._over = False
        self._started = False
        #: True once this class has sent the 413 itself.
        self.answered = False

    async def receive(self) -> Message:
        if self._over:
            return {"type": "http.disconnect"}
        message = await self._receive()
        self._received += len(message.get("body", b""))
        if self._received <= self._limit:
            return message
        self._over = True
        if not self._started:
            self.answered = True
            await refuse_too_large(self._scope, self._receive, self._send, self._limit)
        return {"type": "http.disconnect"}

    async def send(self, message: Message) -> None:
        if self.answered:
            return
        self._started = True  # whatever the app sends first is the start of its response
        await self._send(message)


async def refuse_too_large(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
    """Send the 413 envelope (with the security headers: this runs outside ``SecurityHeaders``)."""
    error = PayloadTooLargeError(MSG_TOO_LARGE, details=[f"limit_bytes={limit}"])
    await sankey_response(error, scope["path"])(scope, receive, send)


class BodySizeLimit:
    """413 ``payload_too_large`` for a body above its route's cap, counted while streaming.

    Also 403 ``read_only_mode`` for an unsafe request to the upload route when the limits say
    writes are off, and the upload cap follows the live setting (see ``BodyLimits``).
    """

    def __init__(self, app: ASGIApp, limits: BodyLimits) -> None:
        self.app = app
        self.limits = limits

    async def _limit(self, scope: Scope) -> int:
        """The cap for this request; raises 403 when the upload route is closed to it."""
        path = scope["path"]
        if path != UPLOAD_PATH or scope["method"] not in UNSAFE_METHODS:
            return self.limits.limit_for(path)
        if not self.limits.writes_allowed:
            raise ReadOnlyModeError(MSG_READ_ONLY)
        return await run_in_threadpool(self.limits.upload_limit)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            limit = await self._limit(scope)
        except SankeyError as error:  # the refusal, or the settings could not be read
            await sankey_response(error, scope["path"])(scope, receive, send)
            return
        declared = _declared_length(Headers(scope=scope))
        if declared is not None and declared > limit:
            await refuse_too_large(scope, receive, send, limit)
            return
        stream = _CountingStream(scope, receive, send, limit)
        try:
            await self.app(scope, stream.receive, stream.send)
        except ClientDisconnect:
            # a route that reads the body itself sees our "disconnect"; the client has its 413
            if not stream.answered:
                raise


# --------------------------------------------------------------------------- headers


class SecurityHeaders:
    """Adds the headers of ``policy`` to every response that does not set them itself."""

    def __init__(self, app: ASGIApp, policy: HeaderPolicy = DEFAULT_POLICY) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        wanted = self.policy.for_path(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in wanted:
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


# --------------------------------------------------------------------------- CSRF


def origin_of(value: str) -> Origin | None:
    """``(scheme, host, port)`` of an ``Origin`` value, ``None`` unless it is a plain origin.

    ``null``, other schemes, user info, a path, query or fragment and an unparsable port or
    address all give ``None``. A missing port is the scheme's default.
    """
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    plain = not ("@" in parts.netloc or parts.path or parts.query or parts.fragment)
    if parts.scheme not in DEFAULT_PORTS or not host or not plain:
        return None
    return parts.scheme, host, DEFAULT_PORTS[parts.scheme] if port is None else port


def host_allowed(host: str, allowed: Sequence[str]) -> bool:
    """``host`` matches an entry of ``allowed`` (lower case, no brackets; ``*`` and ``*.x``)."""
    return any(host == p or (p.startswith("*") and host.endswith(p[1:])) for p in allowed)


def _normalise_hosts(allowed_hosts: Sequence[str]) -> list[str]:
    return [h.lower().removeprefix("[").removesuffix("]") for h in allowed_hosts]


def _media_type(headers: Headers) -> str:
    return headers.get(CONTENT_TYPE, "").partition(";")[0].strip().lower()


def _has_body(headers: Headers) -> bool:
    """A body is announced by ``Transfer-Encoding`` or by a ``Content-Length`` other than 0."""
    if TRANSFER_ENCODING in headers:
        return True
    return headers.get(CONTENT_LENGTH, "").strip("0") != ""


def _check_content_type(headers: Headers, path: str) -> SankeyError | None:
    """415 unless a body (or a ``Content-Type``) is JSON, or multipart on the upload route."""
    media_type = _media_type(headers)
    if not (media_type or _has_body(headers)):
        return None  # DELETE and "duplicate" carry no body
    allowed = {JSON_TYPE, MULTIPART_TYPE} if path == UPLOAD_PATH else {JSON_TYPE}
    return None if media_type in allowed else UnsupportedMediaTypeError(MSG_MEDIA_TYPE)


class CsrfGuard:
    """403 ``forbidden`` / 415 ``unsupported_media_type`` per the module rule."""

    def __init__(self, app: ASGIApp, allowed_hosts: Sequence[str]) -> None:
        self.app = app
        self.allowed = _normalise_hosts(allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            error = self.verdict(scope)
            if error is not None:
                await sankey_response(error, scope["path"])(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def verdict(self, scope: Scope) -> SankeyError | None:
        """The refusal for this request, ``None`` when it may proceed."""
        headers = Headers(scope=scope)
        if scope["method"] not in UNSAFE_METHODS:
            return self._check_safe(headers, scope["path"])
        if not self._same_origin(scope, headers):
            return ForbiddenError(MSG_CROSS_ORIGIN)
        return _check_content_type(headers, scope["path"])

    @staticmethod
    def _check_safe(headers: Headers, path: str) -> SankeyError | None:
        """``GET`` under ``/api`` launches Chrome or opens Mongo connections: not cross-site."""
        site = headers.get(SEC_FETCH_SITE)
        if path.startswith(API_PREFIX) and site is not None and site.lower() == "cross-site":
            return ForbiddenError(MSG_CROSS_ORIGIN)
        return None

    def _same_origin(self, scope: Scope, headers: Headers) -> bool:
        site = headers.get(SEC_FETCH_SITE)
        if site is not None and site.lower() in SAME_ORIGIN_SITES:
            return True
        origin = headers.get(ORIGIN)
        if origin is not None:
            return self._origin_matches(scope, headers, origin)
        # no browser signal at all: a script or curl, which must say it speaks JSON
        return site is None and _media_type(headers) == JSON_TYPE

    def _origin_matches(self, scope: Scope, headers: Headers, origin: str) -> bool:
        claimed = origin_of(origin)
        host = headers.get(HOST)
        own = None if host is None else origin_of(f"{scope.get('scheme', DEFAULT_SCHEME)}://{host}")
        return claimed is not None and claimed == own and host_allowed(claimed[1], self.allowed)


# --------------------------------------------------------------------------- host check


class CaseInsensitiveTrustedHost(TrustedHostMiddleware):
    """400 ``Invalid host header`` unless ``Host`` is in ``allowed_hosts``, in any letter case."""

    def __init__(
        self, app: ASGIApp, allowed_hosts: Sequence[str], *, www_redirect: bool = False
    ) -> None:
        super().__init__(app, [pattern.lower() for pattern in allowed_hosts], www_redirect)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope = {**scope, "headers": [_lower_host(pair) for pair in scope["headers"]]}
        await super().__call__(scope, receive, send)


def _lower_host(pair: tuple[bytes, bytes]) -> tuple[bytes, bytes]:
    name, value = pair
    return (name, value.lower()) if name == HOST_KEY else pair
