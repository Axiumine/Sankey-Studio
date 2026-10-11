"""``GuardedRoute``: read-only mode refuses an unsafe method BEFORE FastAPI decodes the body."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

import pytest
from fastapi import APIRouter
from pydantic import BaseModel

from sankey_studio.web import middleware
from sankey_studio.web.deps import MSG_READ_ONLY, UNSAFE_METHODS, GuardedRoute
from sankey_studio.web.routers import graphs

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, Mode

JSON: Final = {"Content-Type": "application/json"}
REFUSED: Final = {"error": {"code": "read_only_mode", "message": MSG_READ_ONLY, "details": []}}
UNDECODABLE: Final = [b"{", b"not json", b"\xff\xfe", b""]
PATH: Final = "/api/v1/guarded"
calls: list[str] = []

router = APIRouter(route_class=GuardedRoute)


class Body(BaseModel):
    value: int


def handled(method: str) -> dict[str, str]:
    calls.append(method)
    return {"handled": method}


@router.post(PATH)
def _post(_body: Body) -> dict[str, str]:
    return handled("POST")


@router.put(PATH)
def _put(_body: Body) -> dict[str, str]:
    return handled("PUT")


@router.patch(PATH)
def _patch(_body: Body) -> dict[str, str]:
    return handled("PATCH")


@router.delete(PATH)
def _delete() -> dict[str, str]:
    return handled("DELETE")


@router.get(PATH)
def _get() -> dict[str, str]:
    return handled("GET")


@router.api_route(f"{PATH}/mixed", methods=["GET", "POST"])
def _mixed() -> dict[str, str]:
    return handled("MIXED")


@pytest.fixture(autouse=True)
def _no_calls() -> None:
    calls.clear()


class Case(NamedTuple):
    mode: Mode
    status: int


MODES = [Case("local", 200), Case("remote_read_only", 403), Case("remote_writes", 200)]


def test_the_unsafe_methods_are_the_ones_the_middleware_knows() -> None:
    assert sorted(UNSAFE_METHODS) == ["DELETE", "PATCH", "POST", "PUT"]
    assert UNSAFE_METHODS == middleware.UNSAFE_METHODS


def test_the_graphs_router_still_exports_the_one_guarded_route() -> None:
    assert vars(graphs)["GuardedRoute"] is GuardedRoute
    assert graphs.router.route_class is GuardedRoute


@pytest.mark.parametrize("case", MODES, ids=lambda c: c.mode)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_an_unsafe_method_is_refused_exactly_in_read_only_remote_mode(
    make_app: AppFactory, case: Case, method: str
) -> None:
    web = make_app([router], mode=case.mode)
    response = web.client.request(method, PATH, json={"value": 1})
    assert response.status_code == case.status
    assert response.json() == (REFUSED if case.status == 403 else {"handled": method})
    assert calls == ([] if case.status == 403 else [method])


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("raw", UNDECODABLE)
def test_an_undecodable_body_is_a_403_in_read_only_mode(
    make_app: AppFactory, method: str, raw: bytes
) -> None:
    web = make_app([router], mode="remote_read_only")
    response = web.client.request(method, PATH, content=raw, headers=JSON)
    assert (response.status_code, response.json()) == (403, REFUSED)
    assert calls == []


@pytest.mark.parametrize("mode", ["local", "remote_writes"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_an_undecodable_body_is_still_a_422_where_writes_are_allowed(
    make_app: AppFactory, mode: Mode, method: str
) -> None:
    web = make_app([router], mode=mode)
    response = web.client.request(method, PATH, content=b"{", headers=JSON)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert calls == []


@pytest.mark.parametrize("mode", ["local", "remote_read_only", "remote_writes"])
def test_a_safe_method_always_goes_through(make_app: AppFactory, mode: Mode) -> None:
    response = make_app([router], mode=mode).client.get(PATH)
    assert (response.status_code, response.json()) == (200, {"handled": "GET"})


@pytest.mark.parametrize("case", MODES, ids=lambda c: c.mode)
def test_a_route_with_any_unsafe_method_is_guarded_for_all_of_its_methods(
    make_app: AppFactory, case: Case
) -> None:
    web = make_app([router], mode=case.mode)
    response = web.client.get(f"{PATH}/mixed")
    assert response.status_code == case.status
    assert response.json() == (REFUSED if case.status == 403 else {"handled": "MIXED"})
