"""Routers of the web API.

``ALL_ROUTERS`` is what ``create_app`` serves when it is not given ``routers=``: one router per
area, in the order the app registers them. Starlette matches routes in registration order, so a
static path must come before a dynamic one that would also match it: inside ``graphs`` the
``/graphs/export`` and ``/graphs/import`` routes are declared before ``/graphs/{graph_id}``, and
``pages`` declares ``/graphs/new`` before ``/graphs/{graph_id}``. The pages come last, and the
``/static`` mount (added by ``create_app`` after the routers) is the very last, so the vendored
``/static/vendor/plotly.min.js`` route of ``pages.support_router`` is never shadowed by it
(``tests/web/test_app_full_routes.py`` checks the whole table).

A router's own tests build an app with just that router:
``create_app(config, services=services, routers=[router])``.
"""

from __future__ import annotations

from fastapi import APIRouter

from sankey_studio.web.routers import (
    compare,
    edits,
    exports,
    folders,
    graphs,
    mongo,
    pages,
    preview,
    settings,
    sources,
)

ALL_ROUTERS: tuple[APIRouter, ...] = (
    pages.support_router,
    settings.router,
    sources.router,
    mongo.router,
    preview.router,
    edits.router,
    edits.writes_router,
    graphs.router,
    folders.router,
    compare.router,
    exports.router,
    pages.router,
)
