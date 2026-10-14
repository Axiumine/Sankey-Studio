"""The typed accessors over ``app.state`` and the read-only guard (``require_writes``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi import APIRouter, Depends

from sankey_studio.pipeline import ClearableCache, ResultCache
from sankey_studio.web.deps import (
    ConfigDep,
    ResultCacheDep,
    ResultCacheLike,
    ServicesDep,
    WritesAllowed,
    require_writes,
)
from tests.graph_support import make_graph

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, Mode

JSON = {"Content-Type": "application/json"}
READ_ONLY = {
    "error": {
        "code": "read_only_mode",
        "message": (
            "This action is disabled in read-only remote mode (start with --allow-remote-writes)"
        ),
        "details": [],
    }
}

router = APIRouter()


@router.get("/api/v1/probe/state")
def _state(services: ServicesDep, config: ConfigDep, cache: ResultCacheDep) -> dict[str, int]:
    return {"services": id(services), "config": id(config), "cache": id(cache)}


@router.put("/api/v1/probe/param")
def _param(_: WritesAllowed) -> dict[str, bool]:
    return {"wrote": True}


@router.put("/api/v1/probe/decorator", dependencies=[Depends(require_writes)])
def _decorator() -> dict[str, bool]:
    return {"wrote": True}


@router.get("/api/v1/probe/read")
def _read() -> dict[str, bool]:
    return {"read": True}


@router.post("/api/v1/probe/compute")
def _compute() -> dict[str, bool]:
    return {"computed": True}


def test_the_accessors_return_what_create_app_stored(make_app: AppFactory) -> None:
    web = make_app([router])
    response = web.client.get("/api/v1/probe/state")
    assert response.json() == {
        "services": id(web.services),
        "config": id(web.config),
        "cache": id(web.app.state.result_cache),
    }


def test_the_real_result_cache_fits_the_protocol() -> None:
    cache: ResultCacheLike = ResultCache()
    assert cache.get("missing") is None
    cache.clear()
    assert cache.get("missing") is None


def test_the_web_cache_type_is_a_clearable_cache_for_the_layers_below() -> None:
    web_cache: ResultCacheLike = ResultCache()
    below: ClearableCache = web_cache  # mypy proves the two protocols agree
    below.put("k", make_graph([("a", "b", 1.0, None)]), 10)
    below.clear()
    assert web_cache.get("k") is None


class Mount(NamedTuple):
    mode: Mode
    status: int


@pytest.mark.parametrize(
    "case",
    [Mount("local", 200), Mount("remote_read_only", 403), Mount("remote_writes", 200)],
    ids=lambda c: c.mode,
)
@pytest.mark.parametrize("path", ["param", "decorator"])
def test_writes_are_refused_exactly_in_read_only_remote_mode(
    make_app: AppFactory, case: Mount, path: str
) -> None:
    response = make_app([router], mode=case.mode).client.put(f"/api/v1/probe/{path}", json={})
    assert response.status_code == case.status
    assert response.json() == (READ_ONLY if case.status == 403 else {"wrote": True})


@pytest.mark.parametrize("mode", ["local", "remote_read_only", "remote_writes"])
def test_reads_and_pure_computations_stay_available(make_app: AppFactory, mode: Mode) -> None:
    web = make_app([router], mode=mode)
    assert web.client.get("/api/v1/probe/read").json() == {"read": True}
    assert web.client.post("/api/v1/probe/compute", json={}).json() == {"computed": True}
