"""``/api/v1/folders``: create, read, rename/move (optimistic), delete, and every refusal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import FolderDefinition
from sankey_studio.web.routers import folders
from tests.storage.support import create_data
from tests.web.test_routes_graphs_support import (
    API,
    MALFORMED_IDS,
    PLAIN,
    UNKNOWN_ID,
    code,
    save,
)

if TYPE_CHECKING:
    from httpx2 import Response

    from tests.web.conftest import AppFactory, WebApp

FOLDERS = f"{API}/folders"
_ORPHAN = {
    "id": "0" * 31 + "1",
    "name": "Kid",
    "revision": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}
NOT_FOUND = {"error": {"code": "not_found", "message": "Folder not found", "details": []}}
NAME_TAKEN = {
    "error": {
        "code": "folder_name_taken",
        "message": "A collection with this name already exists in the same place",
        "details": [],
    }
}
CYCLE = "A collection cannot be moved into itself or into one of its own collections"
DEFINITION_KEYS = {
    "id",
    "name",
    "parent_id",
    "schema_version",
    "revision",
    "created_at",
    "updated_at",
}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([folders.router])


def make(web: WebApp, name: str, parent: str | None = None) -> dict[str, Any]:
    response = web.client.post(FOLDERS, json={"name": name, "parent_id": parent})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def put(web: WebApp, folder: dict[str, Any], **changes: Any) -> Response:
    body = {
        "name": folder["name"],
        "parent_id": folder["parent_id"],
        "revision": folder["revision"],
    }
    return web.client.put(f"{FOLDERS}/{folder['id']}", json={**body, **changes})


# --------------------------------------------------------------------------- create and read


def test_an_empty_library_has_no_folders(web: WebApp) -> None:
    response = web.client.get(FOLDERS)
    assert (response.status_code, response.json()) == (200, {"items": []})


def test_a_created_folder_is_a_definition_at_revision_one(web: WebApp) -> None:
    response = web.client.post(FOLDERS, json={"name": "  Finance  "})
    assert response.status_code == 201
    created = response.json()
    assert set(created) == DEFINITION_KEYS
    assert (created["name"], created["parent_id"], created["revision"]) == ("Finance", None, 1)
    assert created["schema_version"] == 1
    assert created["created_at"] == created["updated_at"]
    assert len(created["id"]) == 32


def test_a_folder_can_be_created_below_another(web: WebApp) -> None:
    parent = make(web, "Finance")
    child = make(web, "Q3", parent["id"])
    assert child["parent_id"] == parent["id"]
    assert web.client.get(f"{FOLDERS}/{child['id']}").json() == child


def test_the_list_is_sorted_by_name_ignoring_case_and_counts_what_is_inside(web: WebApp) -> None:
    b = make(web, "b")
    make(web, "A")
    make(web, "c")
    inner = make(web, "inner", b["id"])
    web.services.graphs().create(create_data("g"), folder_id=inner["id"])
    items = web.client.get(FOLDERS).json()["items"]
    assert [item["name"] for item in items] == ["A", "b", "c", "inner"]
    by_name = {item["name"]: item for item in items}
    assert (by_name["b"]["child_count"], by_name["b"]["graph_count"]) == (1, 0)
    assert (by_name["inner"]["child_count"], by_name["inner"]["graph_count"]) == (0, 1)
    assert set(items[0]) == {
        "id",
        "name",
        "parent_id",
        "revision",
        "updated_at",
        "graph_count",
        "child_count",
    }


def test_get_answers_404_for_an_unknown_id(web: WebApp) -> None:
    response = web.client.get(f"{FOLDERS}/{UNKNOWN_ID}")
    assert (response.status_code, response.json()) == (404, NOT_FOUND)


@pytest.mark.parametrize("folder_id", MALFORMED_IDS)
def test_a_malformed_id_is_a_404_on_every_route_that_takes_one(web: WebApp, folder_id: str) -> None:
    body = {"name": "x", "parent_id": None, "revision": 1}
    answers = [
        web.client.get(f"{FOLDERS}/{folder_id}"),
        web.client.put(f"{FOLDERS}/{folder_id}", json=body),
        web.client.delete(f"{FOLDERS}/{folder_id}"),
    ]
    assert [(r.status_code, code(r)) for r in answers] == [(404, "not_found")] * 3


def test_a_parent_that_does_not_exist_is_a_404_and_nothing_is_stored(web: WebApp) -> None:
    response = web.client.post(FOLDERS, json={"name": "x", "parent_id": UNKNOWN_ID})
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert web.client.get(FOLDERS).json() == {"items": []}


def test_a_malformed_parent_in_the_body_is_a_validation_error(web: WebApp) -> None:
    response = web.client.post(FOLDERS, json={"name": "x", "parent_id": "not-an-id"})
    assert (response.status_code, code(response)) == (422, "validation_error")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "a\u0000b"},
        {"name": "x", "extra": 1},
        {"name": 5},
    ],
    ids=["empty", "blank", "spaces", "nul", "extra field", "number"],
)
def test_a_bad_body_is_a_validation_error_and_stores_nothing(web: WebApp, body: Any) -> None:
    response = web.client.post(FOLDERS, json=body)
    assert (response.status_code, code(response)) == (422, "validation_error")
    assert web.client.get(FOLDERS).json() == {"items": []}


def test_a_hostile_name_is_stored_and_returned_as_plain_text(web: WebApp) -> None:
    name = f"<img src=x onerror=alert(1)>{chr(0x202E)}"  # ends with a right-to-left override
    created = make(web, name)
    assert created["name"] == name
    assert web.client.get(f"{FOLDERS}/{created['id']}").json()["name"] == name


# --------------------------------------------------------------------------- names


@pytest.mark.parametrize("again", ["finance", "FINANCE", " Finance ", "FiNaNcE"])
def test_a_sibling_name_is_taken_whatever_its_case(web: WebApp, again: str) -> None:
    make(web, "Finance")
    response = web.client.post(FOLDERS, json={"name": again})
    assert (response.status_code, response.json()) == (409, NAME_TAKEN)


def test_a_name_clash_is_not_a_stale_revision(web: WebApp) -> None:
    make(web, "A")
    response = web.client.post(FOLDERS, json={"name": "a"})
    assert code(response) == "folder_name_taken"
    assert code(response) != "conflict"


def test_the_same_name_below_another_parent_is_fine(web: WebApp) -> None:
    first, second = make(web, "One"), make(web, "Two")
    make(web, "Same", first["id"])
    assert make(web, "Same", second["id"])["parent_id"] == second["id"]
    assert make(web, "Same")["parent_id"] is None


# --------------------------------------------------------------------------- rename and move


def test_a_rename_bumps_the_revision_and_keeps_the_id(web: WebApp) -> None:
    folder = make(web, "Old")
    response = put(web, folder, name="New")
    assert response.status_code == 200
    renamed = response.json()
    assert (renamed["id"], renamed["name"], renamed["revision"]) == (folder["id"], "New", 2)
    assert renamed["created_at"] == folder["created_at"]
    assert renamed["updated_at"] >= folder["updated_at"]
    assert web.client.get(f"{FOLDERS}/{folder['id']}").json() == renamed


def test_a_move_changes_the_parent(web: WebApp) -> None:
    one, two = make(web, "One"), make(web, "Two")
    moved = put(web, two, parent_id=one["id"]).json()
    assert moved["parent_id"] == one["id"]
    back = put(web, moved, parent_id=None).json()
    assert (back["parent_id"], back["revision"]) == (None, 3)


def test_a_stale_revision_is_a_409_conflict_with_the_current_revision(web: WebApp) -> None:
    folder = make(web, "A")
    assert put(web, folder, name="B").status_code == 200
    response = put(web, folder, name="C")  # still sends revision 1
    assert (response.status_code, code(response)) == (409, "conflict")
    details = response.json()["error"]["details"]
    assert details[0] == "revision=2"
    assert details[1].startswith("updated_at=")
    assert web.client.get(f"{FOLDERS}/{folder['id']}").json()["name"] == "B"


def test_a_rename_to_a_sibling_name_is_a_409_name_taken(web: WebApp) -> None:
    make(web, "A")
    other = make(web, "B")
    response = put(web, other, name="a")
    assert (response.status_code, response.json()) == (409, NAME_TAKEN)


def test_renaming_a_folder_to_its_own_name_in_another_case_is_fine(web: WebApp) -> None:
    folder = make(web, "docs")
    assert put(web, folder, name="DOCS").json()["name"] == "DOCS"


def test_a_folder_cannot_move_into_itself_or_below_itself(web: WebApp) -> None:
    top = make(web, "Top")
    child = make(web, "Child", top["id"])
    grandchild = make(web, "Grand", child["id"])
    for target in (top["id"], child["id"], grandchild["id"]):
        response = put(web, top, parent_id=target)
        assert (response.status_code, code(response)) == (422, "folder_rule"), target
        assert response.json()["error"]["message"] == CYCLE
    assert web.client.get(f"{FOLDERS}/{top['id']}").json()["revision"] == 1


def test_a_move_below_a_parent_that_does_not_exist_is_a_404(web: WebApp) -> None:
    folder = make(web, "A")
    response = put(web, folder, parent_id=UNKNOWN_ID)
    assert (response.status_code, response.json()) == (404, NOT_FOUND)


def test_a_rename_of_a_folder_with_a_missing_parent_heals_it_to_the_top_level(web: WebApp) -> None:
    orphan = web.services.folders().put_folder(
        FolderDefinition.model_validate({**_ORPHAN, "parent_id": UNKNOWN_ID})
    )
    listed = next(row for row in web.client.get(FOLDERS).json()["items"] if row["id"] == orphan.id)
    assert listed["parent_id"] == UNKNOWN_ID
    response = put(web, listed, name="Renamed")
    assert response.status_code == 200, response.text
    assert (response.json()["name"], response.json()["parent_id"]) == ("Renamed", None)


def test_an_unknown_folder_cannot_be_updated(web: WebApp) -> None:
    body = {"name": "x", "parent_id": None, "revision": 1}
    response = web.client.put(f"{FOLDERS}/{UNKNOWN_ID}", json=body)
    assert (response.status_code, response.json()) == (404, NOT_FOUND)


@pytest.mark.parametrize("revision", [0, -1, "x", None, 1.5])
def test_the_revision_must_be_a_positive_integer(web: WebApp, revision: Any) -> None:
    folder = make(web, "A")
    response = put(web, folder, revision=revision)
    assert (response.status_code, code(response)) == (422, "validation_error")


def test_a_put_without_a_revision_is_refused(web: WebApp) -> None:
    folder = make(web, "A")
    response = web.client.put(f"{FOLDERS}/{folder['id']}", json={"name": "B"})
    assert (response.status_code, code(response)) == (422, "validation_error")


# --------------------------------------------------------------------------- delete


def test_deleting_a_folder_moves_its_folders_and_graphs_up_and_deletes_none(web: WebApp) -> None:
    top = make(web, "Top")
    middle = make(web, "Middle", top["id"])
    leaf = make(web, "Leaf", middle["id"])
    graph = save(web, "kept", *PLAIN)
    web.services.folders().move_graphs([graph.id], middle["id"])
    response = web.client.delete(f"{FOLDERS}/{middle['id']}")
    assert (response.status_code, response.content) == (204, b"")
    assert web.client.get(f"{FOLDERS}/{middle['id']}").status_code == 404
    assert web.client.get(f"{FOLDERS}/{leaf['id']}").json()["parent_id"] == top["id"]
    assert web.services.graphs().get(graph.id).folder_id == top["id"]
    assert web.services.graphs().count() == 1


def test_deleting_a_top_level_folder_moves_its_graphs_to_the_top_level(web: WebApp) -> None:
    top = make(web, "Top")
    graph = save(web, "kept", *PLAIN)
    web.services.folders().move_graphs([graph.id], top["id"])
    assert web.client.delete(f"{FOLDERS}/{top['id']}").status_code == 204
    assert web.services.folders().list_in("root")[0].id == graph.id


def test_deleting_is_refused_when_a_child_would_clash_with_a_sibling_name(web: WebApp) -> None:
    top = make(web, "Top")
    make(web, "Same")
    make(web, "Same", top["id"])
    response = web.client.delete(f"{FOLDERS}/{top['id']}")
    assert (response.status_code, response.json()) == (409, NAME_TAKEN)
    assert web.client.get(f"{FOLDERS}/{top['id']}").status_code == 200  # nothing changed


def test_deleting_an_unknown_folder_is_a_404_and_a_second_delete_too(web: WebApp) -> None:
    assert web.client.delete(f"{FOLDERS}/{UNKNOWN_ID}").status_code == 404
    folder = make(web, "A")
    assert web.client.delete(f"{FOLDERS}/{folder['id']}").status_code == 204
    assert web.client.delete(f"{FOLDERS}/{folder['id']}").status_code == 404


def test_the_routes_only_answer_their_methods(web: WebApp) -> None:
    folder = make(web, "A")
    wrong = [
        web.client.request("PUT", FOLDERS),
        web.client.request("DELETE", FOLDERS),
        web.client.request("POST", f"{FOLDERS}/{folder['id']}"),
        web.client.request("PATCH", f"{FOLDERS}/{folder['id']}"),
    ]
    assert [(r.status_code, code(r)) for r in wrong] == [(405, "method_not_allowed")] * 4
