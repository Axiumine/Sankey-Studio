"""``create_app``: assembles the FastAPI application. Nothing else lives here.

Middleware order, outermost first (Starlette wraps the LAST ``add_middleware`` outermost, so they
are registered in reverse): ``CaseInsensitiveTrustedHost`` (also covers ``/static`` and error
responses; ``*`` only in remote mode), ``BodySizeLimit``, ``SecurityHeaders``, ``CsrfGuard``.
There is no docs UI (Swagger would pull its JavaScript from a CDN) and no CORS.

State written here, read through ``deps``: ``services``, ``config``, ``result_cache``. It is set
eagerly (not in the lifespan) so a ``TestClient`` used without ``with`` works too.

A configuration that would only fail later is refused here, before anything is built:
``InvalidConfigError`` for an ``allowed_hosts`` entry that ``TrustedHostMiddleware`` would assert
on at the first request (every request would then be a plain-text 500).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Final, override

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sankey_studio.pipeline import ResultCache
from sankey_studio.services import Services
from sankey_studio.web import assets
from sankey_studio.web import routers as router_registry
from sankey_studio.web.errors import register_error_handlers
from sankey_studio.web.middleware import (
    BodySizeLimit,
    CaseInsensitiveTrustedHost,
    CsrfGuard,
    SecurityHeaders,
)
from sankey_studio.web.security import BodyLimits, host_pattern_problem

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence
    from contextlib import AbstractAsyncContextManager

    from fastapi import APIRouter
    from starlette.datastructures import Headers
    from starlette.responses import Response
    from starlette.types import Scope

    from sankey_studio.config import BootstrapConfig
    from sankey_studio.web.deps import ResultCacheLike

#: The static directory and URL prefix live in ``assets`` (the page links need them too).
STATIC_DIR: Final = assets.STATIC_DIR
STATIC_URL: Final = assets.STATIC_URL
MSG_NOT_BINDABLE: Final = "a non-loopback host needs remote mode (--allow-remote)"


class InvalidConfigError(ValueError):
    """The configuration is unusable; ``str()`` is safe to print (it never echoes a value)."""

    def __init__(self, where: str, message: str) -> None:
        super().__init__(f"{where}: {message}")
        self.where = where
        self.message = message


def check_allowed_hosts(hosts: Sequence[str]) -> None:
    """``InvalidConfigError`` naming the first ``allowed_hosts`` entry that cannot work."""
    for index, host in enumerate(hosts):
        problem = host_pattern_problem(host)
        if problem is not None:
            raise InvalidConfigError(f"allowed_hosts[{index}]", problem)


#: Validators a browser would keep to revalidate a stored copy; a static answer sends neither.
_VALIDATORS: Final = ("etag", "last-modified")


class UncachedStaticFiles(StaticFiles):
    """``StaticFiles`` that no browser stores (``Cache-Control: no-store``, no validators).

    Every request reads the file again and answers 200 (never a 304), so an edited script or
    style sheet shows on the next reload: nothing survives a server restart in the browser.
    ``/static/v-<digest>/<name>`` (the page links, see ``assets``) serves ``<name>``.
    """

    @override
    def get_path(self, scope: Scope) -> str:
        """The requested file, relative to the directory, without its version prefix."""
        return assets.unversioned(super().get_path(scope))

    @override
    def is_not_modified(self, response_headers: Headers, request_headers: Headers) -> bool:
        """Never: a conditional request (an old stored copy) still gets the whole file."""
        return False

    async def get_response(self, path: str, scope: Scope) -> Response:
        """The file answer with ``no-store`` and without ``ETag`` / ``Last-Modified``."""
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        for name in _VALIDATORS:
            del response.headers[name]
        return response


def mount_static(app: FastAPI) -> None:
    """Serve ``web/static`` under ``/static``, after every router.

    ``/static/vendor/plotly.min.js`` (the file of the installed plotly package) is a ROUTE of
    ``routers.pages.support_router``: routers are included before this mount, which would
    otherwise answer every ``/static/...`` path itself. Nothing is mounted while the directory
    does not exist: Starlette would answer every request for it with a 500.
    """
    if STATIC_DIR.is_dir():
        app.mount(STATIC_URL, UncachedStaticFiles(directory=STATIC_DIR), name="static")


def _lifespan(
    owned: Services | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Shutdown closes the ``Services`` that ``create_app`` built; a caller's stay its own."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owned is not None:
                owned.close()

    return lifespan


def _body_limits(config: BootstrapConfig, services: Services) -> BodyLimits:
    """The upload cap follows ``max_upload_mb`` as stored NOW; read-only mode closes the route."""
    return BodyLimits(
        upload_mb=lambda: services.settings().max_upload_mb,
        writes_allowed=config.privileged_writes_allowed,
    )


def _add_middleware(app: FastAPI, config: BootstrapConfig, services: Services) -> None:
    app.add_middleware(CsrfGuard, config.allowed_hosts)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(BodySizeLimit, _body_limits(config, services))
    app.add_middleware(
        CaseInsensitiveTrustedHost, allowed_hosts=config.allowed_hosts, www_redirect=False
    )


def create_app(
    config: BootstrapConfig,
    *,
    services: Services | None = None,
    routers: Sequence[APIRouter] | None = None,
    result_cache: ResultCacheLike | None = None,
) -> FastAPI:
    """Build the application.

    ``services`` defaults to ``Services.create(config)``, closed when the app shuts down; pass
    your own (tests: mongomock-backed) and you keep closing it. ``routers`` defaults to
    ``routers.ALL_ROUTERS``; a router agent's tests pass just theirs. ``result_cache`` defaults
    to a fresh ``pipeline.ResultCache``. Refuses a non-loopback bind without remote mode and an
    ``allowed_hosts`` entry that cannot work (``InvalidConfigError``), before building anything.
    """
    if not (config.is_loopback or config.remote_mode):
        raise ValueError(MSG_NOT_BINDABLE)
    check_allowed_hosts(config.allowed_hosts)
    owned: Services | None = None
    if services is None:
        owned = services = Services.create(config)
    app = FastAPI(
        title="Sankey Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan(owned),
    )
    app.state.config = config
    app.state.services = services
    app.state.result_cache = ResultCache() if result_cache is None else result_cache
    register_error_handlers(app)
    for router in router_registry.ALL_ROUTERS if routers is None else routers:
        app.include_router(router)
    mount_static(app)
    _add_middleware(app, config, services)
    return app
