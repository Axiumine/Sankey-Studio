"""E2E A.2 (file source): upload, list, preview, a graph that reads the file, and the render."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import (
    BUDGET,
    BUDGET_CATEGORISED,
    LAYERED,
    graph_draft,
    unique_name,
)
from tests.e2e.support.clients import json_of, post_multipart, upload_source

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
UPLOADS = "/api/v1/sources/files"


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: every test works on files with names of its own."""
    return module_server


def fresh(prefix: str, suffix: str = ".csv") -> str:
    """A file name no other test uses."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}{suffix}"


def names_of(api: httpx.Client) -> list[str]:
    """The names ``GET /sources/files`` lists."""
    return [item["name"] for item in json_of(api.get(UPLOADS))]


def file_source(path: str, **extra: Any) -> dict[str, Any]:
    """The ``source`` of a graph that reads the managed file ``path``."""
    return {"type": "text", "origin": "file", "path": path, "format": "csv", **extra}


def create_from_file(api: httpx.Client, path: str) -> dict[str, Any]:
    body = {"name": unique_name("From file"), "source": file_source(path)}
    return dict(json_of(api.post("/api/v1/graphs", json=body), 201))


def test_a_csv_goes_from_upload_to_a_rendered_graph(
    live_server: LiveServer, api: httpx.Client
) -> None:
    name = fresh("budget")
    stored = json_of(upload_source(api, name, BUDGET.csv), 201)
    assert stored["name"] == name
    assert stored["size"] == len(BUDGET.csv.encode())
    assert ISO_UTC.match(stored["modified"])
    assert (live_server.sources_dir / name).read_text() == BUDGET.csv
    assert stored in json_of(api.get(UPLOADS))
    preview = json_of(api.get(f"{UPLOADS}/{name}/preview"))
    assert preview["name"] == name
    assert preview["lines"] == BUDGET.csv.splitlines()

    graph = create_from_file(api, name)
    assert (graph["source"]["origin"], graph["source"]["path"]) == ("file", name)
    assert graph["source"]["content"] is None  # the file is read at render time, not copied
    bundle = json_of(api.get(f"/api/v1/graphs/{graph['id']}/render"))
    assert bundle["figure"]["data"][0]["type"] == "sankey"
    assert "Salary" in bundle["figure"]["data"][0]["node"]["label"]
    assert bundle["donut"] is None  # a graph without categories has no donut ...
    assert bundle["donut_available"] is False
    assert bundle["donut_empty_reason"] == "no_categories"
    assert (bundle["categories"], bundle["legend"], bundle["warnings"]) == ([], [], [])
    stats = bundle["stats"]
    assert (stats["nodes"], stats["links"], stats["layers"]) == (10, 9, 4)
    assert (stats["total_in"], stats["total_out"]) == (3800.0, 3800.0)
    assert bundle["entries_total"] == BUDGET.links


def test_a_file_with_a_category_column_draws_a_donut(api: httpx.Client) -> None:
    name = fresh("categorised")
    upload_source(api, name, BUDGET_CATEGORISED.csv)
    graph = create_from_file(api, name)
    bundle = json_of(api.get(f"/api/v1/graphs/{graph['id']}/render"))
    assert bundle["donut_available"] is True
    assert bundle["donut"]["data"][0]["type"] == "pie"
    shown = {c["name"]: c["value"] for c in bundle["categories"]}
    assert shown == dict(BUDGET_CATEGORISED.categories)


def test_a_graph_always_draws_the_file_as_it_is_now(api: httpx.Client) -> None:
    name = fresh("live")
    upload_source(api, name, BUDGET.csv)
    graph = create_from_file(api, name)
    render = f"/api/v1/graphs/{graph['id']}/render"
    assert json_of(api.get(render))["stats"]["nodes"] == BUDGET.nodes
    upload_source(api, name, LAYERED.csv, overwrite=True)
    assert json_of(api.get(render))["stats"]["nodes"] == LAYERED.nodes
    upload_source(api, name, LAYERED.csv.replace("10", "11"), overwrite=True)
    assert json_of(api.get(render))["stats"]["total_in"] == LAYERED.total + 1  # same size file


def test_a_name_that_is_taken_needs_overwrite_whatever_its_case(
    live_server: LiveServer, api: httpx.Client
) -> None:
    name = fresh("taken")
    upload_source(api, name, BUDGET.csv)
    for attempt in (name, name.upper().replace(".CSV", ".csv")):
        refused = json_of(upload_source(api, attempt, "x,y,1\n"), 409)["error"]
        assert refused["code"] == "conflict"
        assert "already exists" in refused["message"]
    assert (live_server.sources_dir / name).read_text() == BUDGET.csv
    replaced = json_of(upload_source(api, name, "x,y,1\n", overwrite=True), 201)
    assert replaced["size"] == len(b"x,y,1\n")
    assert json_of(api.get(f"{UPLOADS}/{name}/preview"))["lines"] == ["x,y,1"]
    assert names_of(api).count(name) == 1


def test_deleting_a_file_breaks_the_graph_that_reads_it_with_a_clear_error(
    live_server: LiveServer, api: httpx.Client
) -> None:
    name = fresh("short-lived")
    upload_source(api, name, BUDGET.csv)
    graph = create_from_file(api, name)
    assert api.delete(f"{UPLOADS}/{name}").status_code == 204
    assert name not in names_of(api)
    assert not (live_server.sources_dir / name).exists()
    for call in (
        api.get(f"{UPLOADS}/{name}/preview"),
        api.delete(f"{UPLOADS}/{name}"),
        api.get(f"/api/v1/graphs/{graph['id']}/render"),
    ):
        error = json_of(call, 404)["error"]
        assert error["code"] == "source_not_found"
        assert str(live_server.sources_dir) not in call.text  # no path of the host machine
    assert json_of(api.get(f"/api/v1/graphs/{graph['id']}"))["name"] == graph["name"]  # it stays


def test_a_file_in_a_sub_directory_is_listed_and_usable(
    live_server: LiveServer, api: httpx.Client
) -> None:
    folder = live_server.sources_dir / fresh("reports", "") / "2026"
    folder.mkdir(parents=True)
    (folder / "q1.csv").write_text(BUDGET.csv)
    name = f"{folder.parent.name}/2026/q1.csv"
    assert name in names_of(api)
    preview = json_of(api.get(f"{UPLOADS}/{name}/preview"))
    assert preview["lines"][0] == "source,target,value"
    graph = create_from_file(api, name)
    stats = json_of(api.get(f"/api/v1/graphs/{graph['id']}/render"))["stats"]
    assert stats["links"] == BUDGET.links
    assert api.delete(f"{UPLOADS}/{name}").status_code == 204
    assert name not in names_of(api)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("notes.exe", "only files with these extensions"),
        ("noextension", "only files with these extensions"),
        ("../up.csv", "plain name"),
        ("sub/dir.csv", "plain name"),
        ("/abs.csv", "plain name"),
        ("back\\slash.csv", "plain name"),
    ],
)
def test_an_upload_with_a_bad_name_is_refused_and_stores_nothing(
    live_server: LiveServer, api: httpx.Client, name: str, reason: str
) -> None:
    def disk() -> list[str]:
        root = live_server.sources_dir
        return sorted(str(path) for path in root.rglob("*")) if root.exists() else []

    before = disk(), names_of(api)
    error = json_of(upload_source(api, name, "a,b,1\n"), 400)["error"]
    assert error["code"] == "unsafe_source"
    assert reason in error["message"]
    assert (disk(), names_of(api)) == before
    assert not (live_server.sources_dir.parent / "up.csv").exists()


def test_an_upload_form_needs_the_file_part_and_knows_only_its_own_fields(
    api: httpx.Client,
) -> None:
    before = names_of(api)
    only_a_field = api.post(UPLOADS, files={"overwrite": (None, b"true")})  # multipart, no file
    assert json_of(only_a_field, 422)["error"]["code"] == "validation_error"
    plain_form = post_multipart(
        api, UPLOADS, {}, {"overwrite": "true"}
    )  # urlencoded, not multipart
    assert json_of(plain_form, 415)["error"]["code"] == "unsupported_media_type"
    typo = post_multipart(
        api, UPLOADS, {"file": ("t.csv", b"a,b,1", "text/csv")}, {"overwite": "1"}
    )
    detail = json_of(typo, 422)["error"]["details"]
    assert detail == ["body.overwite: Extra inputs are not permitted"]
    assert names_of(api) == before


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("source,target,value\nA,B,1\n", "csv"),
        ("source\ttarget\tvalue\nA\tB\t1\n", "tsv"),
        ("Salary [3000] Budget\nBudget [1200] Rent\n", "sankeymatic"),
        ('[{"source": "A", "target": "B", "value": 1}]', "json"),
    ],
)
def test_the_format_of_a_text_is_detected(api: httpx.Client, sample: str, expected: str) -> None:
    assert json_of(api.post("/api/v1/sources/detect", json={"sample": sample})) == {
        "format": expected
    }


def test_a_sankeymatic_file_is_read_with_the_format_on_auto(api: httpx.Client) -> None:
    name = fresh("flows", ".sankey")
    upload_source(api, name, "Salary [3000] Budget\nBudget [1200] Rent\nBudget [1800] Savings\n")
    source = file_source(name, format="auto")
    bundle = json_of(api.post("/api/v1/preview", json=graph_draft(source=source)))
    stats = bundle["stats"]
    assert (stats["nodes"], stats["links"], stats["total_in"]) == (4, 3, 3000.0)


def test_unreadable_rows_become_warnings_with_their_line_numbers(api: httpx.Client) -> None:
    name = fresh("rows")
    upload_source(api, name, "source,target,value\nA,B,1\nC,D,not-a-number\nE,F\nG,H,2\n")
    bundle = json_of(api.post("/api/v1/preview", json={"source": file_source(name)}))
    assert bundle["stats"]["links"] == 2  # the two good rows are drawn
    assert bundle["warnings"] == [
        f"{name}:3: value must be a positive number",
        f"{name}:4: value is missing",
    ]
