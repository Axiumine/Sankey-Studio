"""The library-folder ("collection") flows of ``/api/v1/folders``, written once for the file store,
mongomock (``tests/e2e/http``) and a real MongoDB (``tests/e2e/mongo``).

Each ``check_*`` function is one scenario over a ``FlowEnv`` (``http_b_world``): it drives the live
API the way the library page does (create folders, save graphs in them, move, rename, delete,
export and import a bundle, read the boot data of the page) and asserts what the API says. The
store it runs on is the active one: the file store by default, the Mongo store after ``on_mongo``
switched the storage backend. ``FOLDER_FLOWS`` is the pytest parameter list both suites run.

``check_the_storage_switch_carries_the_tree`` and the two ``check_*_in_the_store`` scenarios need
the Mongo world; they look into ``world.database`` (and nothing else).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pymongo.errors import DuplicateKeyError

from sankey_studio.storage.base import MONGO_FOLDERS_COLLECTION, MONGO_GRAPHS_COLLECTION
from tests.e2e.support.clients import json_of
from tests.e2e.support.http_b_mongo_flows import configure, finish, scenario_param
from tests.e2e.support.http_b_security import boot_data
from tests.e2e.support.http_b_storage_flows import (
    NO_REPORT,
    active_backend,
    storage_body,
    switch,
)
from tests.e2e.support.http_b_world import MAIN, FlowEnv

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet

    from tests.e2e.support.http_b_mongo_flows import Scenario

FOLDERS: Final = "/api/v1/folders"
GRAPHS: Final = "/api/v1/graphs"
HTML: Final = {"Accept": "text/html"}
JSON_HEADERS: Final = {"Content-Type": "application/json"}
NAME_TAKEN: Final = "A collection with this name already exists in the same place"
UNKNOWN: Final = "0" * 32


# ------------------------------------------------------------------------------ helpers


def make_folder(env: FlowEnv, name: str, parent: str | None = None) -> dict[str, Any]:
    body = {"name": name, "parent_id": parent}
    return dict(json_of(env.api.post(FOLDERS, json=body), 201))


def make_graph(env: FlowEnv, name: str, folder: str | None = None) -> dict[str, Any]:
    """``POST /graphs`` (``?folder=`` when given) of a small manual graph."""
    links = [{"source": "a", "target": "b", "value": 1}]
    body = {"name": name, "source": {"type": "manual", "links": links}}
    params = {} if folder is None else {"folder": folder}
    return dict(json_of(env.api.post(GRAPHS, params=params, json=body), 201))


def names_in(env: FlowEnv, scope: str) -> list[str]:
    """The names of the graphs ``GET /graphs?folder=scope`` lists, newest first."""
    page = json_of(env.api.get(GRAPHS, params={"folder": scope}))
    return [item["name"] for item in page["items"]]


def folder_tree(env: FlowEnv) -> dict[str, str | None]:
    """``{folder name: parent name}`` as ``GET /folders`` lists them (names are unique here)."""
    items = json_of(env.api.get(FOLDERS))["items"]
    names = {item["id"]: item["name"] for item in items}
    return {item["name"]: names.get(item["parent_id"]) for item in items}


def error_of(response: Any, status: int) -> dict[str, Any]:
    return dict(json_of(response, status)["error"])


def put_folder(env: FlowEnv, folder: dict[str, Any], **changes: Any) -> Any:
    keep = {
        "name": folder["name"],
        "parent_id": folder["parent_id"],
        "revision": folder["revision"],
    }
    return env.api.put(f"{FOLDERS}/{folder['id']}", json={**keep, **changes})


def on_mongo(scenario: Scenario) -> Scenario:
    """``scenario`` on the Mongo store: add the connections, switch (no copy) and run it."""

    def run(env: FlowEnv) -> None:
        configure(env)
        saved = switch(env, storage_body(env, "mongo", MAIN), migrate=False)
        assert json_of(saved)["copy_report"] is None
        assert active_backend(env) == ("mongo", MAIN)
        scenario(env)

    run.__name__ = f"{scenario.__name__}_on_mongo"
    return run


# ------------------------------------------------------------------------------ the flows


def check_folders_and_the_rules(env: FlowEnv) -> None:
    """Nested create, a clash in any letter case, a stale revision, a cycle, unknown ids."""
    finance = make_folder(env, "Finance")
    q3 = make_folder(env, "Q3", finance["id"])
    make_folder(env, "Travel")
    assert (finance["revision"], finance["parent_id"], q3["parent_id"]) == (1, None, finance["id"])
    for name, parent in (("finance", None), ("q3", finance["id"]), (" FINANCE ", None)):
        clash = env.api.post(FOLDERS, json={"name": name, "parent_id": parent})
        assert error_of(clash, 409) == {
            "code": "folder_name_taken",
            "message": NAME_TAKEN,
            "details": [],
        }
    assert make_folder(env, "Q3", None)["parent_id"] is None  # the same name elsewhere is fine
    assert json_of(env.api.get(f"{FOLDERS}/{q3['id']}")) == q3
    assert [i["name"] for i in json_of(env.api.get(FOLDERS))["items"]] == [
        "Finance",
        "Q3",
        "Q3",
        "Travel",
    ]
    cycle = put_folder(env, finance, parent_id=q3["id"])
    assert error_of(cycle, 422)["code"] == "folder_rule"
    assert json_of(env.api.get(f"{FOLDERS}/{finance['id']}"))["revision"] == 1
    for missing in (UNKNOWN, "not-an-id"):
        assert env.api.get(f"{FOLDERS}/{missing}").status_code == 404
    parent = env.api.post(FOLDERS, json={"name": "Lost", "parent_id": UNKNOWN})
    assert error_of(parent, 404)["code"] == "not_found"
    finish(env)


def check_rename_and_move_use_the_revision(env: FlowEnv) -> None:
    """A rename bumps the revision; the same revision again is a 409 ``conflict``; a move works."""
    finance = make_folder(env, "Finance")
    travel = make_folder(env, "Travel")
    renamed = json_of(put_folder(env, finance, name="Money"))
    assert (renamed["name"], renamed["revision"]) == ("Money", 2)
    stale = error_of(put_folder(env, finance, name="Other"), 409)
    assert stale["code"] == "conflict"
    assert stale["details"][0] == "revision=2"
    moved = json_of(put_folder(env, travel, parent_id=finance["id"]))
    assert (moved["parent_id"], moved["revision"]) == (finance["id"], 2)
    assert folder_tree(env) == {"Money": None, "Travel": "Money"}
    taken = make_folder(env, "Taken")
    assert error_of(put_folder(env, taken, name="money"), 409)["code"] == "folder_name_taken"
    finish(env)


def check_graphs_live_in_folders(env: FlowEnv) -> None:
    """Save into a folder, list a scope, move, report the missing, refuse an unknown target."""
    finance = make_folder(env, "Finance")
    q3 = make_folder(env, "Q3", finance["id"])
    inside = make_graph(env, "In Q3", q3["id"])
    make_graph(env, "In Finance", finance["id"])
    loose = make_graph(env, "Loose")
    assert inside["folder_id"] == q3["id"]
    assert (names_in(env, "root"), names_in(env, finance["id"]), names_in(env, q3["id"])) == (
        ["Loose"],
        ["In Finance"],
        ["In Q3"],
    )
    assert names_in(env, UNKNOWN) == []
    body = {"name": "N", "source": {"type": "manual", "links": []}}
    nowhere = env.api.post(GRAPHS, params={"folder": UNKNOWN}, json=body)
    assert error_of(nowhere, 404)["code"] == "not_found"
    assert json_of(env.api.get(GRAPHS))["total"] == 3  # nothing was stored
    move = {"ids": [loose["id"], UNKNOWN], "folder_id": q3["id"]}
    assert json_of(env.api.post(f"{GRAPHS}/move", json=move)) == {"moved": 1, "missing": [UNKNOWN]}
    assert sorted(names_in(env, q3["id"])) == ["In Q3", "Loose"]
    after = json_of(env.api.get(f"{GRAPHS}/{loose['id']}"))
    assert (after["revision"], after["updated_at"]) == (loose["revision"], loose["updated_at"])
    refused = env.api.post(f"{GRAPHS}/move", json={"ids": [loose["id"]], "folder_id": UNKNOWN})
    assert error_of(refused, 404)["code"] == "not_found"
    assert env.api.get(GRAPHS, params={"folder": "root", "q": "x"}).status_code == 422
    finish(env)


def check_a_duplicate_and_an_edit_stay_in_their_folder(env: FlowEnv) -> None:
    """A copy lands next to its original; saving the graph again cannot move it."""
    finance = make_folder(env, "Finance")
    original = make_graph(env, "Budget", finance["id"])
    copy = json_of(env.api.post(f"{GRAPHS}/{original['id']}/duplicate"), 201)
    assert (copy["name"], copy["folder_id"]) == ("Budget (copy)", finance["id"])
    edit = {key: original[key] for key in ("name", "description", "tags", "source")}
    updated = json_of(env.api.put(f"{GRAPHS}/{original['id']}", json={**edit, "revision": 1}))
    assert updated["folder_id"] == finance["id"]
    assert sorted(names_in(env, finance["id"])) == ["Budget", "Budget (copy)"]
    finish(env)


def check_deleting_moves_everything_up(env: FlowEnv) -> None:
    """Delete never deletes a graph: folders and graphs go up; a name clash refuses it."""
    top = make_folder(env, "Top")
    middle = make_folder(env, "Middle", top["id"])
    leaf = make_folder(env, "Leaf", middle["id"])
    graph = make_graph(env, "Kept", middle["id"])
    assert env.api.delete(f"{FOLDERS}/{middle['id']}").status_code == 204
    assert folder_tree(env) == {"Top": None, "Leaf": "Top"}
    assert json_of(env.api.get(f"{GRAPHS}/{graph['id']}"))["folder_id"] == top["id"]
    assert names_in(env, top["id"]) == ["Kept"]
    assert env.api.delete(f"{FOLDERS}/{top['id']}").status_code == 204
    assert (folder_tree(env), names_in(env, "root")) == ({"Leaf": None}, ["Kept"])
    assert json_of(env.api.get(f"{FOLDERS}/{leaf['id']}"))["parent_id"] is None
    assert env.api.delete(f"{FOLDERS}/{top['id']}").status_code == 404
    assert json_of(env.api.get(GRAPHS))["total"] == 1
    finish(env)


def check_deleting_is_refused_when_a_child_would_clash(env: FlowEnv) -> None:
    """The children keep their parent when one of them has a sibling's name at the new level."""
    top = make_folder(env, "Top")
    make_folder(env, "Same")
    make_folder(env, "Same", top["id"])
    clash = env.api.delete(f"{FOLDERS}/{top['id']}")
    assert error_of(clash, 409)["code"] == "folder_name_taken"
    items = json_of(env.api.get(FOLDERS))["items"]
    found = sorted(((i["name"], i["parent_id"]) for i in items), key=str)
    assert found == sorted([("Top", None), ("Same", None), ("Same", top["id"])], key=str)
    assert json_of(env.api.get(f"{FOLDERS}/{top['id']}"))["revision"] == 1
    finish(env)


def check_the_library_page_boots_a_folder_scope(env: FlowEnv) -> None:
    """``/`` boots the top level, ``/?folder=`` one folder, a stranger id the top level."""
    finance = make_folder(env, "Finance")
    make_graph(env, "Filed", finance["id"])
    make_graph(env, "Loose")
    top = boot_data(env.api.get("/", headers=HTML).text)
    assert (top["folder"], [g["name"] for g in top["graphs"]], top["total"]) == (None, ["Loose"], 1)
    assert [f["name"] for f in top["folders"]] == ["Finance"]
    inside = boot_data(env.api.get("/", params={"folder": finance["id"]}, headers=HTML).text)
    assert (inside["folder"], [g["name"] for g in inside["graphs"]]) == (finance["id"], ["Filed"])
    stranger = boot_data(env.api.get("/", params={"folder": UNKNOWN}, headers=HTML).text)
    assert (stranger["folder"], stranger["total"]) == (None, 1)
    new = boot_data(env.api.get("/graphs/new", params={"folder": finance["id"]}, headers=HTML).text)
    assert (new["folder_id"], new["graph"]) == (finance["id"], None)
    none = boot_data(env.api.get("/graphs/new", params={"folder": UNKNOWN}, headers=HTML).text)
    assert none["folder_id"] is None
    finish(env)


def check_a_bundle_carries_the_tree(env: FlowEnv) -> None:
    """Export carries the folders of the graphs; importing again reuses them (no doubles)."""
    finance = make_folder(env, "Finance")
    q3 = make_folder(env, "Q3", finance["id"])
    make_folder(env, "Unused")
    ids = [make_graph(env, "In Q3", q3["id"])["id"], make_graph(env, "Loose")["id"]]
    exported = env.api.get(f"{GRAPHS}/export", params={"ids": ",".join(ids)})
    assert [f["name"] for f in json_of(exported)["folders"]] == ["Finance", "Q3"]  # parents first
    report = json_of(env.api.post(f"{GRAPHS}/import", content=exported.text, headers=JSON_HEADERS))
    assert (report["imported"], report["failed"], report["folders"]) == (2, 0, 0)
    assert sorted(names_in(env, q3["id"])) == ["In Q3", "In Q3"]
    assert sorted(folder_tree(env)) == ["Finance", "Q3", "Unused"]
    finish(env)


def check_a_bundle_into_an_empty_library_makes_the_tree(env: FlowEnv) -> None:
    """The folders of a bundle are created with new ids and the graphs go into them."""
    finance = make_folder(env, "Finance")
    q3 = make_folder(env, "Q3", finance["id"])
    graph = make_graph(env, "In Q3", q3["id"])
    text = env.api.get(f"{GRAPHS}/export", params={"ids": graph["id"]}).text
    assert env.api.delete(f"{GRAPHS}/{graph['id']}").status_code == 204
    for folder in (q3, finance):
        assert env.api.delete(f"{FOLDERS}/{folder['id']}").status_code == 204
    report = json_of(env.api.post(f"{GRAPHS}/import", content=text, headers=JSON_HEADERS))
    assert (report["imported"], report["folders"], report["errors"]) == (1, 2, [])
    tree = folder_tree(env)
    assert tree == {"Finance": None, "Q3": "Finance"}
    items = json_of(env.api.get(FOLDERS))["items"]
    assert {i["id"] for i in items}.isdisjoint({finance["id"], q3["id"]})
    (inner,) = [i for i in items if i["name"] == "Q3"]
    assert names_in(env, inner["id"]) == ["In Q3"]
    finish(env)


def check_the_storage_switch_carries_the_tree(env: FlowEnv) -> None:
    """file -> Mongo with ``migrate`` copies folders and placements; back again skips them."""
    configure(env)
    finance = make_folder(env, "Finance")
    q3 = make_folder(env, "Q3", finance["id"])
    graph = make_graph(env, "In Q3", q3["id"])
    saved = json_of(switch(env, storage_body(env, "mongo", MAIN), migrate=True))
    assert saved["copy_report"] == {**NO_REPORT, "copied": 1, "folders": 2}
    assert folder_tree(env) == {"Finance": None, "Q3": "Finance"}
    assert json_of(env.api.get(f"{GRAPHS}/{graph['id']}"))["folder_id"] == q3["id"]
    assert names_in(env, q3["id"]) == ["In Q3"]
    make_folder(env, "Made on Mongo")
    back = json_of(switch(env, storage_body(env, "file"), migrate=True))
    assert back["copy_report"] == {**NO_REPORT, "skipped": 1, "folders": 1, "folders_skipped": 2}
    assert sorted(folder_tree(env)) == ["Finance", "Made on Mongo", "Q3"]
    assert names_in(env, q3["id"]) == ["In Q3"]
    finish(env)


# ------------------------------------------------------------------------------ the store itself


def check_the_store_rejects_a_duplicate_sibling_name(env: FlowEnv) -> None:
    """The unique ``(parent_id, name_key)`` index is really there: a raw insert is refused."""
    finance = make_folder(env, "Finance")
    collection = env.world.client[env.world.database][MONGO_FOLDERS_COLLECTION]
    stored = collection.find_one({"_id": finance["id"]})
    assert stored is not None
    clone = {**stored, "_id": "f" * 32}
    refused = False
    try:
        collection.insert_one(clone)
    except DuplicateKeyError:
        refused = True
    assert refused, "two folders with the same parent and name key were stored"
    assert collection.count_documents({}) == 1
    finish(env)


def check_a_graph_without_the_folder_field_is_top_level(env: FlowEnv) -> None:
    """A graph saved before folders existed has no ``folder_id`` at all: it lists at the top."""
    finance = make_folder(env, "Finance")
    old = make_graph(env, "Old")
    make_graph(env, "Filed", finance["id"])
    graphs = env.world.client[env.world.database][MONGO_GRAPHS_COLLECTION]
    graphs.update_one({"_id": old["id"]}, {"$unset": {"folder_id": ""}})
    raw = graphs.find_one({"_id": old["id"]})
    assert raw is not None
    assert "folder_id" not in raw
    assert (names_in(env, "root"), names_in(env, finance["id"])) == (["Old"], ["Filed"])
    counts = {f["name"]: f["graph_count"] for f in json_of(env.api.get(FOLDERS))["items"]}
    assert counts == {"Finance": 1}
    finish(env)


#: ``(scenario, id)`` of every scenario that runs on any store.
STORE_FLOWS: Final[list[tuple[Scenario, str]]] = [
    (check_folders_and_the_rules, "rules"),
    (check_rename_and_move_use_the_revision, "rename-and-move"),
    (check_graphs_live_in_folders, "graphs-in-folders"),
    (check_a_duplicate_and_an_edit_stay_in_their_folder, "duplicate-and-edit"),
    (check_deleting_moves_everything_up, "delete-moves-up"),
    (check_deleting_is_refused_when_a_child_would_clash, "delete-clash"),
    (check_the_library_page_boots_a_folder_scope, "page-boot"),
    (check_a_bundle_carries_the_tree, "bundle-reuse"),
    (check_a_bundle_into_an_empty_library_makes_the_tree, "bundle-new"),
]
#: On the file store (the default of a server).
FILE_FLOWS: Final[list[ParameterSet]] = [
    scenario_param(scenario, label) for scenario, label in STORE_FLOWS
]
#: The same scenarios on the Mongo store, then what only the Mongo store can show.
MONGO_FLOWS: Final[list[ParameterSet]] = [
    *[scenario_param(on_mongo(scenario), f"mongo-{label}") for scenario, label in STORE_FLOWS],
    scenario_param(check_the_storage_switch_carries_the_tree, "storage-switch"),
    scenario_param(
        on_mongo(check_the_store_rejects_a_duplicate_sibling_name), "mongo-unique-index"
    ),
    scenario_param(
        on_mongo(check_a_graph_without_the_folder_field_is_top_level), "mongo-field-absent"
    ),
]
#: Everything the folder flows run: the file store first, then Mongo.
FOLDER_FLOWS: Final[list[ParameterSet]] = [*FILE_FLOWS, *MONGO_FLOWS]
