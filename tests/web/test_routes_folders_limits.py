"""Limits of the folder routes: name length, depth, count, ``POST /graphs/move`` bounds."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.storage import folder_tree
from sankey_studio.web.routers import folders, graphs
from tests.web.test_routes_graphs_support import API, UNKNOWN_ID, code, ids_of, put_graph

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

FOLDERS = f"{API}/folders"
MOVE = f"{API}/graphs/move"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([folders.router, graphs.router])


class Length(NamedTuple):
    chars: int
    status: int


@pytest.mark.parametrize(
    "case", [Length(0, 422), Length(1, 201), Length(100, 201), Length(101, 422)], ids=str
)
def test_a_name_is_1_to_100_characters(web: WebApp, case: Length) -> None:
    response = web.client.post(FOLDERS, json={"name": "n" * case.chars})
    assert response.status_code == case.status
    if case.status == 422:
        assert code(response) == "validation_error"


def test_the_length_counts_characters_not_bytes(web: WebApp) -> None:
    assert web.client.post(FOLDERS, json={"name": "\U0001f600" * 100}).status_code == 201
    assert web.client.post(FOLDERS, json={"name": "\U0001f600" * 101}).status_code == 422


def test_a_rename_obeys_the_same_length_limit(web: WebApp) -> None:
    folder = web.client.post(FOLDERS, json={"name": "a"}).json()
    body = {"parent_id": None, "revision": 1}
    long = web.client.put(f"{FOLDERS}/{folder['id']}", json={**body, "name": "x" * 101})
    exact = web.client.put(f"{FOLDERS}/{folder['id']}", json={**body, "name": "x" * 100})
    assert (long.status_code, exact.status_code) == (422, 200)


# --------------------------------------------------------------------------- depth and count


def chain(web: WebApp, levels: int) -> list[dict[str, Any]]:
    """``levels`` folders, each inside the one before (the first at the top level)."""
    made: list[dict[str, Any]] = []
    for number in range(levels):
        parent = made[-1]["id"] if made else None
        response = web.client.post(FOLDERS, json={"name": f"L{number}", "parent_id": parent})
        assert response.status_code == 201
        made.append(response.json())
    return made


def test_eight_levels_are_allowed_and_the_ninth_is_a_422_folder_rule(web: WebApp) -> None:
    made = chain(web, 8)
    response = web.client.post(FOLDERS, json={"name": "L8", "parent_id": made[-1]["id"]})
    assert (response.status_code, code(response)) == (422, "folder_rule")
    assert response.json()["error"]["message"] == folder_tree.MSG_DEPTH
    assert len(web.client.get(FOLDERS).json()["items"]) == 8


def test_moving_a_subtree_too_deep_is_refused_and_one_level_less_is_not(web: WebApp) -> None:
    made = chain(web, 7)  # depth 7
    sub = web.client.post(FOLDERS, json={"name": "sub"}).json()
    web.client.post(FOLDERS, json={"name": "leaf", "parent_id": sub["id"]})  # sub has height 2
    body = {"name": "sub", "revision": 1}
    refused = web.client.put(f"{FOLDERS}/{sub['id']}", json={**body, "parent_id": made[-1]["id"]})
    assert (refused.status_code, code(refused)) == (422, "folder_rule")
    fits = web.client.put(f"{FOLDERS}/{sub['id']}", json={**body, "parent_id": made[-2]["id"]})
    assert fits.status_code == 200


def test_the_count_cap_is_inclusive(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(folder_tree, "FOLDERS_MAX", 3)
    for number in range(3):
        assert web.client.post(FOLDERS, json={"name": f"F{number}"}).status_code == 201
    over = web.client.post(FOLDERS, json={"name": "F3"})
    assert (over.status_code, code(over)) == (422, "folder_rule")
    assert over.json()["error"]["message"] == folder_tree.MSG_COUNT
    assert len(web.client.get(FOLDERS).json()["items"]) == 3


# --------------------------------------------------------------------------- POST /graphs/move


class Move(NamedTuple):
    size: int
    status: int


@pytest.mark.parametrize(
    "case", [Move(0, 422), Move(1, 200), Move(200, 200), Move(201, 422)], ids=lambda c: str(c.size)
)
def test_a_move_takes_1_to_200_ids(web: WebApp, case: Move) -> None:
    ids = ids_of(case.size).split(",") if case.size else []
    response = web.client.post(MOVE, json={"ids": ids, "folder_id": None})
    assert response.status_code == case.status
    if case.status == 200:
        assert response.json() == {"moved": 0, "missing": ids}
    else:
        assert code(response) == "validation_error"


@pytest.mark.parametrize(
    "body",
    [
        {"ids": [UNKNOWN_ID, UNKNOWN_ID], "folder_id": None},
        {"ids": ["short"], "folder_id": None},
        {"ids": ["A" * 32], "folder_id": None},
        {"ids": UNKNOWN_ID, "folder_id": None},
        {"ids": [UNKNOWN_ID], "folder_id": "short"},
        {"ids": [UNKNOWN_ID]},
        {"folder_id": None},
        {"ids": [UNKNOWN_ID], "folder_id": None, "extra": 1},
    ],
    ids=[
        "repeated id",
        "malformed id",
        "upper case id",
        "ids not a list",
        "malformed folder",
        "no folder key",
        "no ids",
        "extra key",
    ],
)
def test_a_bad_move_body_is_a_422_and_moves_nothing(web: WebApp, body: Any) -> None:
    graph = put_graph(web, 1, "g")
    response = web.client.post(MOVE, json=body)
    assert (response.status_code, code(response)) == (422, "validation_error")
    assert web.services.graphs().get(graph).folder_id is None
