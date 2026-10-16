# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""One error envelope for every failure: ``{"error": {"code", "message", "details"}}``.

* ``SankeyError`` subclasses answer with their own ``status_code`` and ``code``.
* Request validation answers 422 ``validation_error``; the details are ``"<location>: <message>"``
  built from the error location and message ONLY (never the submitted value: a 422 must not echo
  a pasted URI or 2 MB of text). The one pydantic message that quotes the input, a discriminator
  tag that matches no variant (``union_tag_invalid``: "Input tag 'x' found using ..."), is
  replaced by a fixed sentence built from the EXPECTED tags (``tag_message``).
* Routing errors (404, 405, ...) keep their status; anything unexpected is a generic 500 with no
  stack and no secret.
* A browser navigation (``GET`` asking for ``text/html``, outside ``/api/`` and ``/static/``) never
  gets the envelope: it gets an HTML page in the app shell with the status of the error
  (``pages.error_page``). A 404 (unknown URL, graph that does not exist, page query that is not
  valid) is the not-found page; an unreachable graph store (503 ``storage_error``) says so; every
  other domain or HTTP error and every unexpected 500 is "Something went wrong". The page never
  contains the request path, an id or the text of the error. Every other client, and every API
  path, keeps the JSON envelope.

``error_response`` is also what the pure ASGI middleware use for their 403, 413 and 415, and
every response built here carries the security headers itself: some of them are produced outside
the ``SecurityHeaders`` middleware (the outermost 500 handler, the body-size 413).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from sankey_studio.errors import NotFoundError, SankeyError
from sankey_studio.web.routers.pages import error_page, not_found_page, storage_kind
from sankey_studio.web.security import DEFAULT_POLICY

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from starlette.responses import Response

logger = logging.getLogger(__name__)

CODE_VALIDATION = "validation_error"
CODE_INTERNAL = "internal_error"
CODE_HTTP = "http_error"
MSG_VALIDATION = "The request is not valid"
MSG_INTERNAL = "Internal server error"
#: Routing statuses with a stable machine code; every other HTTP error is ``http_error``.
HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}
#: ``SankeyError.code`` of an unreachable or unusable graph store: its page names the store.
CODE_STORAGE = "storage_error"
#: Pydantic error types whose message quotes the submitted discriminator value.
TAG_ERRORS = frozenset({"union_tag_invalid", "union_tag_not_found"})
MAX_DETAILS = 50
MAX_DETAIL_CHARS = 300
#: The first path segments that are never browser pages: their errors stay JSON.
NON_PAGE_ROOTS = frozenset({"api", "static"})


@dataclass(frozen=True, slots=True)
class ErrorBody:
    """The content of the ``error`` object of the envelope."""

    code: str
    message: str
    details: list[str] = field(default_factory=list)

    def envelope(self) -> dict[str, dict[str, Any]]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def error_response(
    status_code: int,
    body: ErrorBody,
    path: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """The envelope as a response to ``path``, with the security headers (see module doc)."""
    merged = dict(DEFAULT_POLICY.for_path(path))
    merged.update(headers or {})
    return JSONResponse(body.envelope(), status_code=status_code, headers=merged)


def sankey_response(exc: SankeyError, path: str) -> JSONResponse:
    """The response for a domain error (``status_code``, ``code``, ``message``, ``details``)."""
    body = ErrorBody(exc.code, exc.message, list(exc.details))
    return error_response(exc.status_code, body, path)


def tag_message(error: Mapping[str, Any]) -> str:
    """The message of a discriminator error, from the expected tags and never the submitted one.

    Pydantic words ``union_tag_invalid`` as "Input tag 'x' found using 'type' does not match any
    of the expected tags: ...", quoting what the caller sent. The context (``discriminator``,
    ``expected_tags``) comes from the schema, so it is safe: "type must be one of: manual, text,
    mongo". ``union_tag_not_found`` (no tag at all) is "type is required".
    """
    ctx = error.get("ctx") or {}
    tag_field = str(ctx.get("discriminator") or "tag").replace("'", "")
    tags = str(ctx.get("expected_tags") or "").replace("'", "")
    if error.get("type") == "union_tag_not_found":
        return f"{tag_field} is required"
    return f"{tag_field} must be one of: {tags}" if tags else f"{tag_field} is not valid"


def validation_details(errors: Iterable[Mapping[str, Any]]) -> list[str]:
    """``"loc.path: message"`` strings: at most ``MAX_DETAILS``, each cut to a fixed length."""
    details: list[str] = []
    for error in errors:
        if len(details) == MAX_DETAILS:
            break
        where = ".".join(str(part) for part in error.get("loc", ()))
        message = tag_message(error) if error.get("type") in TAG_ERRORS else str(error["msg"])
        text = f"{where}: {message}" if where else message
        details.append(text[:MAX_DETAIL_CHARS])
    return details


def wants_html(request: Request) -> bool:
    """True for a browser navigation: a ``GET`` for a page path that accepts ``text/html``.

    ``fetch`` and curl send ``*/*`` (no HTML wanted), and ``/api/...`` and ``/static/...`` are
    never pages.
    """
    if request.method != "GET":
        return False
    root = request.url.path.split("/")[1]
    return root not in NON_PAGE_ROOTS and "text/html" in request.headers.get("accept", "").lower()


def narrow[E: Exception](exc: Exception, kind: type[E]) -> E:
    """``exc`` as the ``kind`` its handler is registered for (Starlette picks by class)."""
    if isinstance(exc, kind):
        return exc
    raise TypeError(f"expected {kind.__name__}, got {type(exc).__name__}")


def browser_error(
    request: Request, kind: str, status_code: int, headers: Mapping[str, str] | None = None
) -> Response:
    """The HTML error page of ``kind`` with ``status_code``, the security headers and ``headers``.

    The headers are set here because the outermost 500 handler answers outside the
    ``SecurityHeaders`` middleware (which only fills in the ones that are missing).
    """
    response = error_page(request, kind, status_code)
    for name, value in DEFAULT_POLICY.for_path(request.url.path):
        response.headers.setdefault(name, value)
    response.headers.update(headers or {})
    return response


async def handle_sankey_error(request: Request, exc: Exception) -> Response:
    error = narrow(exc, SankeyError)
    html = wants_html(request)
    if isinstance(error, NotFoundError) and html:
        return not_found_page(request, graph=True)
    if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        where = f"{request.method} {request.url.path}"
        logger.warning("%s on %s: %s", type(error).__name__, where, error.message)
    if html:
        kind = storage_kind(request) if error.code == CODE_STORAGE else "server"
        return browser_error(request, kind, error.status_code)
    return sankey_response(error, request.url.path)


async def handle_request_validation(request: Request, exc: Exception) -> Response:
    errors = narrow(exc, RequestValidationError).errors()
    if wants_html(request):
        return not_found_page(request)
    body = ErrorBody(CODE_VALIDATION, MSG_VALIDATION, validation_details(errors))
    return error_response(422, body, request.url.path)


async def handle_model_validation(request: Request, exc: Exception) -> JSONResponse:
    # The context stays in: ``tag_message`` reads the expected tags from it (and nothing else).
    errors = narrow(exc, ValidationError).errors(include_input=False, include_url=False)
    body = ErrorBody(CODE_VALIDATION, MSG_VALIDATION, validation_details(errors))
    return error_response(422, body, request.url.path)


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    """Routing and static-file errors: the status is kept, the text is the standard phrase."""
    error = narrow(exc, StarletteHTTPException)
    if wants_html(request):
        if error.status_code == HTTPStatus.NOT_FOUND:
            return not_found_page(request)
        return browser_error(request, "server", error.status_code, error.headers)
    code = HTTP_CODES.get(error.status_code, CODE_HTTP)
    try:
        message = HTTPStatus(error.status_code).phrase
    except ValueError:
        message = "HTTP error"
    body = ErrorBody(code, message)
    return error_response(error.status_code, body, request.url.path, error.headers)


# Starlette calls every exception handler as handler(request, exc), so the parameter must stay.
# noinspection PyUnusedParameter
async def handle_unexpected(request: Request, exc: Exception) -> Response:
    """Anything else: generic 500 (the server logs the traceback when Starlette re-raises).

    A browser navigation gets the HTML page; if that page cannot be rendered either, the
    envelope answers, so the handler itself never fails.
    """
    if wants_html(request):
        # noinspection PyBroadException
        try:
            return browser_error(request, "server", 500)
        except Exception:  # whatever broke the page must not break its fallback
            logger.exception("The error page could not be rendered")
    return error_response(500, ErrorBody(CODE_INTERNAL, MSG_INTERNAL), request.url.path)


def register_error_handlers(app: FastAPI) -> None:
    """Install the handlers above on ``app`` (called once by ``create_app``)."""
    app.add_exception_handler(SankeyError, handle_sankey_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation)
    app.add_exception_handler(ValidationError, handle_model_validation)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected)
