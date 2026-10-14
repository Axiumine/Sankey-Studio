"""E2E A.5 (library): export a bundle, import it into a second storage directory, bad bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.storage.bundle import import_bundle
from tests.e2e.support.builders import (
    MONGO_PASSWORD,
    graph_create,
    graph_draft,
    mongo_settings,
    unique_name,
)
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_a_library import GRAPHS, Library, seed_library, update_body

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

COUNT = 25
IMPORT = f"{GRAPHS}/import"
EXPORT = f"{GRAPHS}/export"
UNICODE_NAME = "Smoke éü ☃"
CONTENT = ("name", "description", "tags", "source", "transform", "style")


@dataclass(frozen=True, slots=True)
class Origin:
    """The module's source server with its client and the 25 graphs (+ one unicode name)."""

    server: LiveServer
    api: httpx.Client
    library: Library
    unicode_graph: dict[str, Any]

    def bundle(self, ids: list[str] | None = None) -> dict[str, Any]:
        wanted = self.library.ids if ids is None else ids
        return dict(json_of(self.api.get(EXPORT, params={"ids": ",".join(wanted)})))


@pytest.fixture(scope="module")
def origin(module_server: LiveServer) -> Iterator[Origin]:
    with make_client(module_server) as api:
        library = seed_library(api, COUNT)
        edited = library.graphs[2]
        for number in (1, 2):  # revision 3 on one graph, so "revision kept" means something
            edited = json_of(
                api.put(
                    f"{GRAPHS}/{edited['id']}", json=update_body(edited, description=f"v{number}")
                )
            )
        library.graphs[2] = edited
        body = graph_create(UNICODE_NAME, tags=["ü"], description="☃")
        unicode_graph = json_of(api.post(GRAPHS, json=body), 201)
        yield Origin(module_server, api, library, unicode_graph)


@pytest.fixture(scope="module")
def empty(module_make_server: ServerFactory) -> Iterator[httpx.Client]:
    """A client of a second module server that no test imports valid graphs into."""
    server = module_make_server()
    with make_client(server) as api:
        yield api


def content_of(graph: dict[str, Any]) -> dict[str, Any]:
    return {key: graph[key] for key in CONTENT}


def by_name(api: httpx.Client, ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """The graphs of a server (``ids``, else every one), loaded whole, keyed by name.

    The shared origin server also holds what other tests of the module created there (and in any
    order): compare only the ids that were exported, never "everything on the server".
    """
    if ids is None:
        ids = [item["id"] for item in json_of(api.get(GRAPHS))["items"]]
    graphs = (json_of(api.get(f"{GRAPHS}/{graph_id}")) for graph_id in ids)
    return {graph["name"]: graph for graph in graphs}


def test_the_bundle_is_one_utf8_json_download_in_the_order_asked(origin: Origin) -> None:
    ids = [origin.library.ids[5], origin.unicode_graph["id"], origin.library.ids[0]]
    answer = origin.api.get(EXPORT, params={"ids": ",".join([*ids, ids[0]])})  # a repeat is dropped
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/json"
    assert answer.headers["content-disposition"].startswith(
        'attachment; filename="sankey-studio-graphs.json"'
    )
    bundle = answer.json()
    assert (bundle["format"], bundle["version"]) == ("sankey-studio/graphs", 2)
    assert [graph["id"] for graph in bundle["graphs"]] == ids
    assert UNICODE_NAME in answer.content.decode("utf-8")  # raw UTF-8 ...
    assert "\\u" not in answer.text  # ... not \uXXXX escapes
    assert bundle["graphs"][1] == origin.unicode_graph


def test_ids_may_be_repeated_parameters_too(origin: Origin) -> None:
    first, second = origin.library.ids[:2]
    answer = origin.api.get(EXPORT, params=[("ids", first), ("ids", second)])
    assert [graph["id"] for graph in json_of(answer)["graphs"]] == [first, second]


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"ids": "0" * 32}, 404, "not_found"),
        ({"ids": "not-an-id"}, 422, "validation_error"),
        ({"ids": ""}, 422, "validation_error"),
        ({}, 422, "validation_error"),
        ({"ids": ",".join(f"{n:032x}" for n in range(201))}, 422, "validation_error"),
    ],
    ids=["unknown", "malformed", "empty", "missing", "over-200"],
)
def test_an_export_of_bad_ids_is_refused(
    origin: Origin, params: dict[str, str], status: int, code: str
) -> None:
    answer = origin.api.get(EXPORT, params=params)
    assert json_of(answer, status)["error"]["code"] == code
    assert "content-disposition" not in answer.headers


def test_all_graphs_import_into_a_second_storage_with_new_ids(
    origin: Origin, make_server: ServerFactory
) -> None:
    target = make_server()
    exported = [*origin.library.ids, origin.unicode_graph["id"]]
    bundle = origin.bundle(exported)
    with make_client(target) as second:
        report = json_of(second.post(IMPORT, json=bundle))
        assert (report["imported"], report["failed"], report["errors"]) == (COUNT + 1, 0, [])
        assert len(set(report["ids"])) == COUNT + 1
        assert not set(report["ids"]) & set(origin.library.ids)  # HTTP import never keeps ids
        copies = by_name(second)
    originals = by_name(origin.api, exported)
    assert set(copies) == set(originals)
    for name, copy in copies.items():
        assert content_of(copy) == content_of(originals[name])
        assert copy["revision"] == 1  # a fresh graph, even where the original was edited
        assert copy["id"] in report["ids"]
    assert originals["Budget 02"]["revision"] == 3


def test_imported_graphs_draw_like_the_originals(
    origin: Origin, make_server: ServerFactory
) -> None:
    target = make_server()
    graph = origin.library.graphs[4]
    with make_client(target) as second:
        report = json_of(second.post(IMPORT, json=origin.bundle([graph["id"]])))
        mine = json_of(second.get(f"{GRAPHS}/{report['ids'][0]}/render"))
    theirs = json_of(origin.api.get(f"{GRAPHS}/{graph['id']}/render"))
    assert mine["stats"] == theirs["stats"]
    assert mine["figure"] == theirs["figure"]


def test_importing_twice_makes_two_copies(origin: Origin, make_server: ServerFactory) -> None:
    target = make_server()
    bundle = origin.bundle(origin.library.ids[:3])
    with make_client(target) as second:
        first = json_of(second.post(IMPORT, json=bundle))
        again = json_of(second.post(IMPORT, json=bundle))
        assert not set(first["ids"]) & set(again["ids"])
        assert json_of(second.get(GRAPHS))["total"] == 6


def test_keeping_the_ids_keeps_revisions_and_dates_and_refuses_a_second_import(
    origin: Origin, make_server: ServerFactory
) -> None:
    target = make_server()
    ids = [origin.library.ids[2], origin.library.ids[3]]  # the edited one (revision 3) and another
    bundle = origin.bundle(ids)
    report = import_bundle(target.services.graphs(), bundle, "keep_ids")  # the library-level mode
    assert (report.imported, report.failed, report.ids) == (2, 0, ids)
    with make_client(target) as second:
        for graph_id in ids:
            mine = json_of(second.get(f"{GRAPHS}/{graph_id}"))
            assert mine == json_of(origin.api.get(f"{GRAPHS}/{graph_id}"))  # byte for byte
        assert json_of(second.get(f"{GRAPHS}/{ids[0]}"))["revision"] == 3
        again = import_bundle(target.services.graphs(), bundle, "keep_ids")
        assert (again.imported, again.failed) == (0, 2)
        assert again.errors == [
            "graph 1: A graph with this id already exists",
            "graph 2: A graph with this id already exists",
        ]
        assert json_of(second.get(GRAPHS))["total"] == 2
        stale = update_body(json_of(second.get(f"{GRAPHS}/{ids[0]}")), description="after")
        assert json_of(second.put(f"{GRAPHS}/{ids[0]}", json=stale))["revision"] == 4


MALFORMED = [
    pytest.param(
        {"format": "something/else", "version": 2, "graphs": []}, "not a sankey-studio", id="format"
    ),
    pytest.param([], "not a sankey-studio", id="a-list"),
    pytest.param("text", "not a sankey-studio", id="a-string"),
    pytest.param(
        {"format": "sankey-studio/graphs", "version": 3, "graphs": []},
        "Unsupported bundle version",
        id="version",
    ),
    pytest.param(
        {"format": "sankey-studio/graphs", "version": 1, "graphs": []},
        "Unsupported bundle version",
        id="version-1-is-no-longer-read",
    ),
    pytest.param(
        {"format": "sankey-studio/graphs", "version": True, "graphs": []},
        "Unsupported bundle version",
        id="bool-version",
    ),
    pytest.param(
        {"format": "sankey-studio/graphs", "version": 2}, "no list of graphs", id="no-graphs"
    ),
    pytest.param(
        {"format": "sankey-studio/graphs", "version": 2, "graphs": {}},
        "no list of graphs",
        id="graphs-object",
    ),
    pytest.param(
        {"format": "sankey-studio/graphs", "version": 2, "graphs": [{}] * 1001},
        "at most 1000 graphs",
        id="too-many",
    ),
]


@pytest.mark.parametrize(("bundle", "message"), MALFORMED)
def test_a_bundle_that_is_not_usable_stores_nothing(
    empty: httpx.Client, bundle: Any, message: str
) -> None:
    error = json_of(empty.post(IMPORT, json=bundle), 422)["error"]
    assert error["code"] == "bundle_error"
    assert message in error["message"]
    assert json_of(empty.get(GRAPHS))["total"] == 0


def test_one_bad_graph_never_blocks_the_good_ones(
    origin: Origin, make_server: ServerFactory
) -> None:
    target = make_server()
    good = origin.bundle(origin.library.ids[:2])["graphs"]
    secret = unique_name("PRIVATE-NAME")
    bundle = {
        "format": "sankey-studio/graphs",
        "version": 2,
        "graphs": [good[0], {"name": secret}, 5, good[1], {**good[1], "name": ""}],
    }
    with make_client(target) as second:
        answer = second.post(IMPORT, json=bundle)
        report = json_of(answer)
        assert (report["imported"], report["failed"]) == (2, 3)
        assert [line.split(":")[0] for line in report["errors"]] == [
            "graph 2",
            "graph 3",
            "graph 5",
        ]
        assert report["errors"][0].startswith("graph 2: source: Field required")
        assert report["errors"][1] == "graph 3: not an object"
        assert report["errors"][2].startswith("graph 5: name")
        assert secret not in answer.text  # an error names the position, never the content
        assert {graph["name"] for graph in by_name(second).values()} == {g["name"] for g in good}


def test_a_body_that_is_not_json_or_has_the_wrong_type_is_refused(empty: httpx.Client) -> None:
    broken = empty.post(IMPORT, content=b"{nope", headers={"Content-Type": "application/json"})
    assert json_of(broken, 422)["error"]["details"] == ["body.1: JSON decode error"]
    plain = empty.post(IMPORT, content=b"{}", headers={"Content-Type": "text/plain"})
    assert json_of(plain, 415)["error"]["code"] == "unsupported_media_type"
    assert json_of(empty.get(GRAPHS))["total"] == 0


def test_a_bundle_holds_no_connection_string(make_server: ServerFactory) -> None:
    server = make_server(settings=mongo_settings("main"))
    source = {"type": "mongo", "connection": "main", "collection": "transfers", "mode": "find"}
    with make_client(server) as api:
        body = {"name": unique_name("Mongo graph"), "source": source}
        graph = json_of(api.post(GRAPHS, json=body), 201)
        answer = api.get(EXPORT, params={"ids": graph["id"]})
        assert answer.status_code == 200
        assert '"connection": "main"' in answer.text  # it names the connection ...
        assert MONGO_PASSWORD not in answer.text  # ... and carries nothing of its URI
        assert "mongo.invalid" not in answer.text
        assert json_of(api.post(IMPORT, json=answer.json()))["imported"] == 1


def test_a_graph_with_a_very_large_text_survives_the_round_trip(
    origin: Origin, make_server: ServerFactory
) -> None:
    rows = "".join(f"A{i:06d},B{i:06d},1\n" for i in range(100_000))  # about 1.9 million characters
    draft = graph_draft(f"source,target,value\n{rows}")
    body = graph_create(unique_name("Big"), draft)
    graph = json_of(origin.api.post(GRAPHS, json=body), 201)
    bundle = json_of(origin.api.get(EXPORT, params={"ids": graph["id"]}))
    with make_client(make_server()) as other:
        report = json_of(other.post(IMPORT, json=bundle))
        copy = json_of(other.get(f"{GRAPHS}/{report['ids'][0]}"))
    assert len(graph["source"]["content"]) > 1_800_000
    assert copy["source"]["content"] == graph["source"]["content"]
