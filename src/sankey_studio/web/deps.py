# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Typed accessors over ``request.app.state`` and the dependencies routers share.

``request.app.state.<x>`` is ``Any``; every read goes through ONE function here so the rest of the
web layer stays typed. ``create_app`` is the only writer of those attributes.

Routers use:

* ``ServicesDep`` / ``ConfigDep`` / ``ResultCacheDep`` as parameter annotations;
* ``require_writes`` for every endpoint that persists something. It answers 403 ``read_only_mode``
  exactly in remote mode without ``--allow-remote-writes``. Prefer the decorator form, which
  costs no parameter of the 4-parameter cap::

      @router.delete("/files/{name:path}", dependencies=[Depends(require_writes)])

  or take ``_: WritesAllowed`` when the signature has room;
* ``GuardedRoute`` as the ``route_class`` of a router whose unsafe methods all persist: the same
  403, but BEFORE FastAPI decodes the body (a dependency runs after the body was parsed, so it
  would answer an undecodable body 422 instead of 403 in read-only mode);
* ``MongoContextDep`` for the routes that only talk to a MongoDB connection: a ``SourceContext``
  that does not need (nor create) the sources directory, so a broken sources directory cannot
  take a Mongo route down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Final, Protocol

from fastapi import Depends, Request, Response
from fastapi.routing import APIRoute

from sankey_studio.config import BootstrapConfig
from sankey_studio.errors import ReadOnlyModeError
from sankey_studio.models import SankeyGraph
from sankey_studio.services import Services
from sankey_studio.sources.base import SourceContext

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

MSG_READ_ONLY = (
    "This action is disabled in read-only remote mode (start with --allow-remote-writes)"
)
#: The methods that persist. ``web.middleware.UNSAFE_METHODS`` is the same set (it cannot be
#: imported here: the middleware imports this module); a test pins the two together.
UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class ResultCacheLike(Protocol):  # pragma: no mutate block - interface only, never executed
    """The slice of ``pipeline.ResultCache`` the web layer needs (a TTL'd LRU keyed by hash).

    Declared here so this module (and a router's test fake) does not import ``pipeline``. It is a
    ``pipeline.ClearableCache``: ``clear`` empties it after a write to a source.
    """

    def get(self, key: str, /) -> SankeyGraph | None: ...

    def put(self, key: str, value: SankeyGraph, ttl_s: float, /) -> None: ...

    def clear(self) -> None: ...


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_config(request: Request) -> BootstrapConfig:
    config: BootstrapConfig = request.app.state.config
    return config


def get_result_cache(request: Request) -> ResultCacheLike:
    cache: ResultCacheLike = request.app.state.result_cache
    return cache


def require_writes(request: Request) -> None:
    """Raise ``ReadOnlyModeError`` (403 ``read_only_mode``) in remote mode without writes."""
    if not get_config(request).privileged_writes_allowed:
        raise ReadOnlyModeError(MSG_READ_ONLY)


def get_mongo_context(request: Request) -> SourceContext:
    """A ``SourceContext`` for the Mongo routes: settings and clients, no sources directory.

    ``sources_dir`` only names the configured location: nothing is created or touched, because
    a Mongo call never reads a source file (``Services.source_context`` would create it and
    answer 503 when it is unusable).
    """
    services = get_services(request)
    return SourceContext(
        settings=services.settings(),
        sources_dir=services.config.effective_sources_dir,
        mongo=services.mongo,
    )


class GuardedRoute(APIRoute):
    """A route whose unsafe methods persist: read-only mode refuses them BEFORE the body is decoded.

    FastAPI decodes a JSON body before it resolves ``dependencies``, so a ``require_writes``
    dependency alone would answer a malformed body 422 in read-only mode instead of 403.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        if UNSAFE_METHODS.isdisjoint(self.methods or ()):
            return handler

        async def guarded(request: Request) -> Response:
            require_writes(request)
            return await handler(request)

        return guarded


ServicesDep = Annotated[Services, Depends(get_services)]
ConfigDep = Annotated[BootstrapConfig, Depends(get_config)]
ResultCacheDep = Annotated[ResultCacheLike, Depends(get_result_cache)]
WritesAllowed = Annotated[None, Depends(require_writes)]
MongoContextDep = Annotated[SourceContext, Depends(get_mongo_context)]
