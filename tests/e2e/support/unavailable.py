# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``ExportUnavailable``: an ASGI wrapper that makes image exports answer 501 on ONE server.

This is the seam behind ``make_server(export_unavailable=True)``. The browser UI falls back to
``Plotly.downloadImage`` when the server cannot draw images (no Chrome: 501 ``export_unavailable``);
Chrome IS installed on the test machine, so the 501 has to be forced. Patching
``render.export.images._render_image`` would change every server in the process (the app runs in
this process, in a thread) and would have to be restored across threads; wrapping the ASGI app of
ONE server touches nothing else.

The answer is the production one: the domain error that ``export_image`` maps a missing Chrome to
(``map_render_error(ChromeNotFoundError())``) rendered by the app's own ``sankey_response``, so
status, code, message, envelope and security headers are exactly what a server without Chrome
sends. Only the image formats are affected (``format=svg`` which is the default, and ``png``) on
``GET /api/v1/graphs/{id}/export`` and ``POST /api/v1/export``; html, json and csv exports,
every other route and the lifespan go to the real app untouched.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final
from urllib.parse import parse_qs

from kaleido.errors import ChromeNotFoundError

from sankey_studio.render.export.images import map_render_error
from sankey_studio.web.errors import sankey_response

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

IMAGE_FORMATS: Final = frozenset({"svg", "png"})
DEFAULT_FORMAT: Final = "svg"
SAVED_EXPORT: Final = re.compile(r"^/api/v1/graphs/[^/]+/export$")
DRAFT_EXPORT: Final = "/api/v1/export"


def is_image_export(scope: Scope) -> bool:
    """True for an image export request: the routes of the module doc with ``svg`` or ``png``."""
    if scope["type"] != "http":
        return False
    path, method = scope["path"], scope["method"]
    routed = (method == "GET" and SAVED_EXPORT.match(path)) or (
        method == "POST" and path == DRAFT_EXPORT
    )
    if not routed:
        return False
    query = parse_qs(scope["query_string"].decode("latin-1"))
    return query.get("format", [DEFAULT_FORMAT])[-1] in IMAGE_FORMATS


async def drain(receive: Receive) -> None:
    """Read the request body to its end, so the connection can be reused after the answer."""
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            return


class ExportUnavailable:
    """Wrap ``app``: image exports answer the production 501 envelope, all else passes through."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not is_image_export(scope):
            await self.app(scope, receive, send)
            return
        await drain(receive)
        response = sankey_response(map_render_error(ChromeNotFoundError()), scope["path"])
        await response(scope, receive, send)
