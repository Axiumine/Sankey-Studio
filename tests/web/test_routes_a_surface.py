# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""What the settings, sources and mongo routers DECLARE: paths, status, guard, response model.

mutmut skips decorated functions, and every route handler is one, so a changed decorator
argument or return annotation would otherwise pass the suite when no behaviour test happens to
look at it. The table below pins them: the exact route set of each router, the success status
code, the guard on exactly the persisting routes (``GuardedRoute`` as the ``route_class`` of the
settings router, the ``require_writes`` dependency on the sources routes), the response model that
FastAPI validates and filters every answer with (a secret-free ``SettingsOut`` cannot grow a
field by accident), the prefix, the tags and the public names of each module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi.routing import APIRoute

from sankey_studio.sources.files import SourceFileInfo
from sankey_studio.web.deps import GuardedRoute, require_writes
from sankey_studio.web.routers import mongo, settings, sources
from sankey_studio.web.schemas import SettingsOut, SettingsSaved

if TYPE_CHECKING:
    from types import ModuleType

    from fastapi import APIRouter

SETTINGS = "/api/v1/settings"
SOURCES = "/api/v1/sources"
MONGO = "/api/v1/mongo"
MONGO_TEST = f"{SETTINGS}/mongo/{{name}}/test"


class Declared(NamedTuple):
    """One route: where it lives, what it answers on success and what guards it."""

    module: ModuleType
    method: str
    path: str
    status: int
    response: object
    guarded: bool


DECLARED = [
    Declared(settings, "GET", SETTINGS, 200, SettingsOut, guarded=False),
    Declared(settings, "PUT", SETTINGS, 200, SettingsSaved, guarded=True),
    Declared(settings, "POST", f"{SETTINGS}/storage/test", 200, settings.ProbeOk, guarded=True),
    Declared(
        settings,
        "POST",
        f"{SETTINGS}/mongo/{{name}}/test",
        200,
        settings.MongoProbeOk,
        guarded=True,
    ),
    Declared(sources, "GET", f"{SOURCES}/files", 200, list[SourceFileInfo], guarded=False),
    Declared(sources, "POST", f"{SOURCES}/files", 201, SourceFileInfo, guarded=True),
    Declared(sources, "DELETE", f"{SOURCES}/files/{{name:path}}", 204, None, guarded=True),
    Declared(
        sources, "GET", f"{SOURCES}/files/{{name:path}}/preview", 200, sources.FilePreview, False
    ),
    Declared(sources, "POST", f"{SOURCES}/detect", 200, sources.DetectOut, guarded=False),
    Declared(mongo, "GET", f"{MONGO}/{{name}}/databases", 200, list[str], guarded=False),
    Declared(mongo, "GET", f"{MONGO}/{{name}}/collections", 200, list[str], guarded=False),
    Declared(mongo, "GET", f"{MONGO}/{{name}}/sample", 200, mongo.SampleOut, guarded=False),
]


def routes_of(router: APIRouter) -> dict[tuple[str, str], APIRoute]:
    """``{(method, path): route}`` of a router (every route here is an ``APIRoute``)."""
    found: dict[tuple[str, str], APIRoute] = {}
    for route in router.routes:
        assert isinstance(route, APIRoute)
        for method in route.methods or set():
            found[method, route.path] = route
    return found


@pytest.mark.parametrize("case", DECLARED, ids=[f"{c.method} {c.path}" for c in DECLARED])
def test_each_route_declares_its_status_response_model_and_guard(case: Declared) -> None:
    route = routes_of(case.module.router)[case.method, case.path]
    assert (route.status_code or 200) == case.status
    assert route.response_model == case.response
    guards = [dependency.dependency for dependency in route.dependencies]
    by_class = case.module is settings  # the settings router guards through its route class
    assert guards == ([require_writes] if case.guarded and not by_class else [])
    assert isinstance(route, GuardedRoute) == by_class  # which lets a safe method through


@pytest.mark.parametrize(
    ("module", "route_class"),
    [(settings, GuardedRoute), (sources, APIRoute), (mongo, APIRoute)],
    ids=lambda p: getattr(p, "__name__", ""),
)
def test_the_route_class_of_each_router(module: ModuleType, route_class: type) -> None:
    assert module.router.route_class is route_class


@pytest.mark.parametrize("module", [settings, sources, mongo], ids=lambda m: m.__name__)
def test_a_router_serves_exactly_the_declared_routes(module: ModuleType) -> None:
    expected = {(c.method, c.path) for c in DECLARED if c.module is module}
    assert set(routes_of(module.router)) == expected
    assert len(module.router.routes) == len(expected)


class Surface(NamedTuple):
    """The module-level facts of one router module."""

    module: ModuleType
    prefix: str
    tag: str
    public: list[str]


SURFACES = [
    Surface(settings, SETTINGS, "settings", ["MongoProbeOk", "ProbeOk", "router"]),
    Surface(sources, SOURCES, "sources", ["DetectIn", "DetectOut", "FilePreview", "router"]),
    Surface(mongo, MONGO, "mongo", ["SampleOut", "router"]),
]


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s.tag)
def test_prefix_tags_and_public_names_of_a_router_module(surface: Surface) -> None:
    router = surface.module.router
    assert router.prefix == surface.prefix
    assert router.tags == [surface.tag]
    assert sorted(surface.module.__all__) == surface.public
    assert all(hasattr(surface.module, name) for name in surface.public)
    assert all(route.tags == [surface.tag] for route in routes_of(router).values())
