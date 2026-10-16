# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers of ``test_matrix*.py`` and ``test_app_full*.py``: the route table of the FULL app.

No tests here. ``ENDPOINTS`` lists every ``(method, path)`` that ``routers.ALL_ROUTERS`` serves,
with the path parameters filled in (an unknown graph id, a made-up connection or file name), so a
matrix test is parametrised over the real route table and a new route joins it automatically.
``test_app_full_routes.py`` proves the list equals what ``create_app()`` really registers.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, NamedTuple

from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from sankey_studio.web.routers import ALL_ROUTERS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.routing import BaseRoute

UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: A well-formed graph id that is never stored.
UNKNOWN_ID: Final = "0" * 32
_PARAMETER: Final = re.compile(r"\{(\w+)(?::(\w+))?\}")
_FILLERS: Final = {"graph_id": UNKNOWN_ID, "folder_id": UNKNOWN_ID, "name": "x"}


class Endpoint(NamedTuple):
    """One method of one route: ``template`` as registered, ``path`` ready to request."""

    method: str
    template: str
    path: str

    @property
    def label(self) -> str:
        return f"{self.method} {self.template}"


def fill(template: str) -> str:
    """``template`` with every ``{parameter}`` replaced by a plausible value."""

    def value(match: re.Match[str]) -> str:
        return "a.csv" if match.group(2) == "path" else _FILLERS[match.group(1)]

    return _PARAMETER.sub(value, template)


def api_contexts(routes: Sequence[BaseRoute]) -> list[RouteContext]:
    """The effective ``APIRoute`` of ``routes`` in matching order, include prefixes applied.

    ``create_app(...).routes`` holds one included-router node per ``include_router`` call (FastAPI
    0.143); ``iter_route_contexts`` is what FastAPI's own OpenAPI code uses to flatten them.
    Mounts and anything else that is not an ``APIRoute`` are skipped.
    """
    return [
        context
        for context in iter_route_contexts(routes)
        if isinstance(context.original_route, APIRoute) and context.path is not None
    ]


def endpoints_of(routes: Sequence[BaseRoute]) -> list[Endpoint]:
    """One ``Endpoint`` per method of every ``APIRoute`` in ``routes``, in matching order."""
    return [
        Endpoint(method, str(context.path), fill(str(context.path)))
        for context in api_contexts(routes)
        for method in sorted(context.methods or ())
    ]


ENDPOINTS: Final = endpoints_of([r for router in ALL_ROUTERS for r in router.routes])
UNSAFE: Final = [e for e in ENDPOINTS if e.method in UNSAFE_METHODS]
SAFE: Final = [e for e in ENDPOINTS if e.method not in UNSAFE_METHODS]
UPLOAD: Final = Endpoint("POST", "/api/v1/sources/files", "/api/v1/sources/files")


def ids(endpoints: Sequence[Endpoint]) -> list[str]:
    """Readable pytest ids: ``POST /api/v1/graphs``."""
    return [endpoint.label for endpoint in endpoints]
