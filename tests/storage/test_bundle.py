"""Graph bundles: export and import."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import NotFoundError, SankeyError, StorageError
from sankey_studio.storage import FileGraphRepository, MongoGraphRepository, bundle
from sankey_studio.storage.bundle import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    MAX_BUNDLE_GRAPHS,
    MAX_REPORTED_ERRORS,
    BundleError,
    ImportReport,
    export_bundle,
    import_bundle,
)
from sankey_studio.storage.migrate import export_bundle as migrate_export
from sankey_studio.storage.migrate import import_bundle as migrate_import
from tests.storage.support import (
    ID_A,
    ID_B,
    ID_C,
    NOW,
    SECRET_URI,
    Spec,
    definition,
    nasty_create,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from sankey_studio.models import GraphDefinition
    from tests.storage.support import Ticker


def _seed(repo: FileGraphRepository) -> list[GraphDefinition]:
    graphs = [
        definition(ID_A, "a", Spec("d", ("x",), updated_at=NOW + timedelta(days=2))),
        definition(ID_B, "b", Spec(revision=4, updated_at=NOW + timedelta(days=1))),
        definition(ID_C, "c", spec=Spec(links=3)),
    ]
    for graph in graphs:
        repo.put(graph)
    return graphs


def _bundle(*graphs: Any) -> dict[str, Any]:
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "graphs": list(graphs),
        "folders": [],
    }


def _dump(graph: GraphDefinition) -> dict[str, Any]:
    return graph.model_dump(mode="json")


# --------------------------------------------------------------------------- constants


def test_the_format_and_limits() -> None:
    assert BUNDLE_FORMAT == "sankey-studio/graphs"
    assert BUNDLE_VERSION == 2
    assert MAX_BUNDLE_GRAPHS == 1000
    assert MAX_REPORTED_ERRORS == 50
    assert (BundleError.status_code, BundleError.code) == (422, "bundle_error")
    assert issubclass(BundleError, SankeyError)


def test_migrate_re_exports_the_bundle_functions() -> None:
    assert migrate_export is export_bundle
    assert migrate_import is import_bundle


# --------------------------------------------------------------------------- export


def test_export_all_lists_every_graph_in_listing_order(file_repo: FileGraphRepository) -> None:
    graphs = _seed(file_repo)
    out = export_bundle(file_repo)
    assert out == _bundle(*[_dump(g) for g in graphs])
    assert list(out) == ["format", "version", "graphs", "folders"]


def test_export_of_an_empty_store(file_repo: FileGraphRepository) -> None:
    assert export_bundle(file_repo) == _bundle()


def test_export_by_ids_keeps_the_given_order_and_drops_duplicates(
    file_repo: FileGraphRepository,
) -> None:
    graphs = _seed(file_repo)
    out = export_bundle(file_repo, [ID_C, ID_A, ID_C, ID_A])
    assert out["graphs"] == [_dump(graphs[2]), _dump(graphs[0])]
    assert export_bundle(file_repo, []) == _bundle()


@pytest.mark.parametrize("missing", [ID_B, "0" * 32, "../x", "short"])
def test_export_of_an_unknown_id_is_not_found(file_repo: FileGraphRepository, missing: str) -> None:
    file_repo.put(definition(ID_A, "a"))
    with pytest.raises(NotFoundError, match="Graph not found"):
        export_bundle(file_repo, [ID_A, missing] if missing != ID_B else [missing])


def test_a_bundle_holds_no_secret(mongo_repo: MongoGraphRepository) -> None:
    mongo_repo.create(nasty_create(mongo=True))
    text = json.dumps(export_bundle(mongo_repo))
    assert "hunter2" not in text
    assert SECRET_URI not in text
    assert '"connection": "c"' in text  # the source names its connection, nothing more


@pytest.mark.parametrize(("count", "ok"), [(2, True), (3, True), (4, False), (9, False)])
def test_the_graph_count_cap_is_inclusive(
    file_repo: FileGraphRepository, monkeypatch: pytest.MonkeyPatch, count: int, ok: bool
) -> None:
    ids = [f"{i:032x}" for i in range(count)]
    for graph_id in ids:
        file_repo.put(definition(graph_id, graph_id[-2:]))
    monkeypatch.setattr(bundle, "MAX_BUNDLE_GRAPHS", 3)
    calls: list[Callable[[], dict[str, Any]]] = [
        lambda: export_bundle(file_repo),
        lambda: export_bundle(file_repo, ids),
    ]
    for call in calls:
        if ok:
            assert len(call()["graphs"]) == count
            continue
        with pytest.raises(BundleError) as info:
            call()
        assert info.value.message == "A bundle may hold at most 3 graphs"


# --------------------------------------------------------------------------- import: happy paths


def test_import_with_new_ids_creates_fresh_graphs(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository, clock: Ticker
) -> None:
    graphs = _seed(file_repo)
    clock.now = NOW + timedelta(days=30)
    report = import_bundle(mongo_repo, export_bundle(file_repo), "new_ids")
    assert isinstance(report, ImportReport)
    assert (report.imported, report.failed, report.errors) == (3, 0, [])
    assert len(report.ids) == 3
    assert not {ID_A, ID_B, ID_C} & set(report.ids)
    created = [mongo_repo.get(graph_id) for graph_id in report.ids]  # in bundle order
    for step, (original, new) in enumerate(zip(graphs, created, strict=True)):
        assert new.id != original.id
        assert new.revision == 1  # a new graph starts over
        assert new.created_at == new.updated_at == NOW + timedelta(days=30, seconds=step)
        assert (new.name, new.description, new.tags) == (
            original.name,
            original.description,
            original.tags,
        )
        assert (new.source, new.transform, new.style) == (
            original.source,
            original.transform,
            original.style,
        )


def test_import_with_kept_ids_stores_the_graphs_verbatim(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    graphs = _seed(file_repo)
    report = import_bundle(mongo_repo, export_bundle(file_repo), "keep_ids")
    assert (report.imported, report.failed, report.errors) == (3, 0, [])
    assert report.ids == [ID_A, ID_B, ID_C]
    assert list(mongo_repo.iter_definitions()) == graphs
    assert mongo_repo.get(ID_B).revision == 4


def test_kept_ids_that_exist_are_reported_and_left_alone(file_repo: FileGraphRepository) -> None:
    _seed(file_repo)
    mine = definition(ID_B, "mine", Spec(revision=8))
    file_repo.put(mine, overwrite=True)
    report = import_bundle(file_repo, _bundle(_dump(definition(ID_B, "theirs"))), "keep_ids")
    assert report == ImportReport(
        imported=0, failed=1, ids=[], errors=["graph 1: A graph with this id already exists"]
    )
    assert file_repo.get(ID_B) == mine


def test_a_bundle_imported_with_new_ids_twice_makes_two_copies(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    _seed(file_repo)
    export = export_bundle(file_repo)
    first = import_bundle(mongo_repo, export, "new_ids")
    second = import_bundle(mongo_repo, export, "new_ids")
    assert mongo_repo.count() == 6
    assert set(first.ids).isdisjoint(second.ids)


def test_graphs_with_unsafe_names_survive_a_mongo_import(mongo_repo: MongoGraphRepository) -> None:
    graph = nasty_create(mongo=True)
    original = mongo_repo.create(graph)
    export = export_bundle(mongo_repo)
    other = copy.deepcopy(export)
    report = import_bundle(mongo_repo, other, "new_ids")
    assert report.imported == 1
    imported = mongo_repo.get(report.ids[0])
    assert imported.transform == original.transform
    assert imported.style == original.style
    assert imported.source == original.source


def test_an_empty_bundle_imports_nothing(file_repo: FileGraphRepository) -> None:
    assert import_bundle(file_repo, _bundle(), "new_ids") == ImportReport(0, 0, [], [])


def test_a_bundle_survives_a_json_round_trip(
    file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    graphs = _seed(file_repo)
    text = json.dumps(export_bundle(file_repo))
    assert import_bundle(mongo_repo, json.loads(text), "keep_ids").imported == 3
    assert list(mongo_repo.iter_definitions()) == graphs


# --------------------------------------------------------------------------- import: bad graphs


def _valid(graph_id: str = ID_A, name: str = "ok") -> dict[str, Any]:
    return _dump(definition(graph_id, name))


class BadGraph(NamedTuple):
    label: str
    item: Any
    reason: str


def _with(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**base, **changes}


BAD_GRAPHS = [
    BadGraph("not an object", "just text", "not an object"),
    BadGraph("a list", [], "not an object"),
    BadGraph("none", None, "not an object"),
    BadGraph(
        "empty name", _with(_valid(), name=""), "name: String should have at least 1 character"
    ),
    BadGraph(
        "missing name", {k: v for k, v in _valid().items() if k != "name"}, "name: Field required"
    ),
    BadGraph(
        "bad id", _with(_valid(), id="../x"), "id: String should match pattern '^[0-9a-f]{32}$'"
    ),
    BadGraph(
        "bad link value",
        _with(
            _valid(),
            source={"type": "manual", "links": [{"source": "a", "target": "b", "value": 0}]},
        ),
        "source.manual.links.0.value: Input should be greater than 0",
    ),
    BadGraph(
        "two problems",
        _with(_valid(), name="", tags="x"),
        "name: String should have at least 1 character (+1 more)",
    ),
    BadGraph(
        "newer schema",
        _with(_valid(), schema_version=99),
        "Stored graph was written by a newer version of sankey-studio",
    ),
    BadGraph(
        "bad schema",
        _with(_valid(), schema_version="x"),
        "Stored graph has an invalid schema version",
    ),
    BadGraph(
        "naive time",
        _with(_valid(), created_at="2025-01-01T00:00:00"),
        "created_at: Input should have timezone info",
    ),
]


@pytest.mark.parametrize("case", BAD_GRAPHS, ids=[c.label for c in BAD_GRAPHS])
@pytest.mark.parametrize("mode", ["new_ids", "keep_ids"])
def test_a_bad_graph_is_reported_by_position_and_the_others_still_import(
    file_repo: FileGraphRepository, case: BadGraph, mode: Any
) -> None:
    items = [_valid(ID_B, "first"), case.item, _valid(ID_C, "third")]
    report = import_bundle(file_repo, _bundle(*items), mode)
    assert report.imported == 2
    assert report.failed == 1
    assert report.errors == [f"graph 2: {case.reason}"]
    assert len(report.ids) == 2
    assert sorted(g.name for g in file_repo.iter_definitions()) == ["first", "third"]


def test_error_messages_never_echo_the_input(file_repo: FileGraphRepository) -> None:
    item = _with(_valid(), name="", description="SECRET-TEXT", tags=["SECRET-TAG"] * 30)
    report = import_bundle(file_repo, _bundle(item), "new_ids")
    assert report.failed == 1
    assert "SECRET" not in " ".join(report.errors)


@pytest.mark.parametrize(
    ("bad_count", "reported"),
    [(1, 1), (49, 49), (50, 50), (51, 50), (60, 50)],
)
def test_at_most_fifty_errors_are_listed_but_all_are_counted(
    file_repo: FileGraphRepository, bad_count: int, reported: int
) -> None:
    items = [_with(_valid(f"{i:032x}"), name="") for i in range(bad_count)] + [_valid(ID_A, "fine")]
    report = import_bundle(file_repo, _bundle(*items), "keep_ids")
    assert (report.imported, report.failed) == (1, bad_count)
    assert len(report.errors) == reported
    assert report.errors[0].startswith("graph 1: ")
    assert report.errors[-1] == f"graph {reported}: name: String should have at least 1 character"


def test_a_backend_failure_aborts_the_import(
    file_repo: FileGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(_graph: Any, **_options: Any) -> Any:
        raise StorageError("backend down")

    monkeypatch.setattr(file_repo, "create", down)
    with pytest.raises(StorageError, match="backend down"):
        import_bundle(file_repo, _bundle(_valid(), _valid(ID_B)), "new_ids")


def test_a_graph_imported_before_a_failure_stays(
    file_repo: FileGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_put = file_repo.put
    calls: list[str] = []

    def flaky(graph: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        calls.append(graph.id)
        if len(calls) == 2:
            raise StorageError("backend down")
        return real_put(graph, overwrite=overwrite)

    monkeypatch.setattr(file_repo, "put", flaky)
    with pytest.raises(StorageError):
        import_bundle(file_repo, _bundle(_valid(ID_A), _valid(ID_B), _valid(ID_C)), "keep_ids")
    assert file_repo.count() == 1


# --------------------------------------------------------------------------- import: bad bundles


def _is_error(bad: Any) -> BundleError:
    with pytest.raises(BundleError) as info:
        import_bundle(FileGraphRepository.__new__(FileGraphRepository), bad, "new_ids")
    return info.value


class BadBundle(NamedTuple):
    label: str
    value: Any
    message: str


NOT_A_BUNDLE = "This is not a sankey-studio graph bundle"
BAD_BUNDLES = [
    BadBundle("list", [], NOT_A_BUNDLE),
    BadBundle("none", None, NOT_A_BUNDLE),
    BadBundle("text", "bundle", NOT_A_BUNDLE),
    BadBundle("no format", {"version": 2, "graphs": []}, NOT_A_BUNDLE),
    BadBundle("other format", {"format": "other", "version": 2, "graphs": []}, NOT_A_BUNDLE),
    BadBundle("case", {"format": BUNDLE_FORMAT.upper(), "version": 2, "graphs": []}, NOT_A_BUNDLE),
    BadBundle("no version", {"format": BUNDLE_FORMAT, "graphs": []}, "Unsupported bundle version"),
    BadBundle(
        "version 1",
        {"format": BUNDLE_FORMAT, "version": 1, "graphs": []},
        "Unsupported bundle version",
    ),
    BadBundle(
        "version 3",
        {"format": BUNDLE_FORMAT, "version": 3, "graphs": []},
        "Unsupported bundle version",
    ),
    BadBundle(
        "version 0",
        {"format": BUNDLE_FORMAT, "version": 0, "graphs": []},
        "Unsupported bundle version",
    ),
    BadBundle(
        "text version",
        {"format": BUNDLE_FORMAT, "version": "2", "graphs": []},
        "Unsupported bundle version",
    ),
    BadBundle(
        "float version",
        {"format": BUNDLE_FORMAT, "version": 2.0, "graphs": []},
        "Unsupported bundle version",
    ),
    BadBundle(
        "bool version",
        {"format": BUNDLE_FORMAT, "version": True, "graphs": []},
        "Unsupported bundle version",
    ),
    BadBundle(
        "no graphs", {"format": BUNDLE_FORMAT, "version": 2}, "The bundle has no list of graphs"
    ),
    BadBundle(
        "graphs dict",
        {"format": BUNDLE_FORMAT, "version": 2, "graphs": {}},
        "The bundle has no list of graphs",
    ),
    BadBundle(
        "graphs text",
        {"format": BUNDLE_FORMAT, "version": 2, "graphs": "x"},
        "The bundle has no list of graphs",
    ),
]


@pytest.mark.parametrize("case", BAD_BUNDLES, ids=[c.label for c in BAD_BUNDLES])
def test_an_unusable_bundle_is_refused_as_a_whole(case: BadBundle) -> None:
    err = _is_error(case.value)
    assert err.message == case.message
    assert err.status_code == 422


@pytest.mark.parametrize(("count", "ok"), [(2, True), (3, True), (4, False)])
def test_the_import_graph_count_cap_is_inclusive(
    file_repo: FileGraphRepository, monkeypatch: pytest.MonkeyPatch, count: int, ok: bool
) -> None:
    monkeypatch.setattr(bundle, "MAX_BUNDLE_GRAPHS", 3)
    items = [_valid(f"{i:032x}", f"g{i}") for i in range(count)]
    if ok:
        assert import_bundle(file_repo, _bundle(*items), "keep_ids").imported == count
        return
    with pytest.raises(BundleError) as info:
        import_bundle(file_repo, _bundle(*items), "keep_ids")
    assert info.value.message == "A bundle may hold at most 3 graphs"
    assert file_repo.count() == 0  # refused before anything was stored


def test_extra_top_level_keys_are_ignored(file_repo: FileGraphRepository, tmp_path: Path) -> None:
    export = {**_bundle(_valid()), "generator": "someone else", "note": 1}
    assert import_bundle(file_repo, export, "keep_ids").imported == 1
    assert tmp_path.exists()


class CountingRepo(FileGraphRepository):
    """A repository that counts how many graphs ``iter_definitions`` hands out."""

    handed_out = 0

    def iter_definitions(self) -> Iterator[GraphDefinition]:
        for graph in super().iter_definitions():
            type(self).handed_out += 1
            yield graph


def test_export_all_reads_one_graph_more_than_the_cap_and_no_further(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = CountingRepo(tmp_path / "graphs")
    for i in range(8):
        repo.put(definition(f"{i:032x}", f"g{i}"))
    monkeypatch.setattr(bundle, "MAX_BUNDLE_GRAPHS", 3)
    CountingRepo.handed_out = 0
    with pytest.raises(BundleError):
        export_bundle(repo)
    assert CountingRepo.handed_out == 4  # enough to know it is too many, not the whole store
