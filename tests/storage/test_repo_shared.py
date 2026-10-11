"""Behaviour every ``GraphRepository`` must show, run once per backend (file and Mongo)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import ConflictError, NotFoundError
from sankey_studio.models import ManualSource
from tests.storage.support import (
    ID_A,
    ID_B,
    ID_C,
    ID_D,
    NOW,
    Spec,
    create_data,
    definition,
    update_data,
)

if TYPE_CHECKING:
    from tests.storage.conftest import RepoEnv

ID_E = "e" * 32
UNKNOWN = "0" * 32
BAD_IDS = [
    "",
    "a" * 31,
    "a" * 33,
    "A" * 32,
    "g" * 32,
    "../x",
    "..%2f",
    "../" + "a" * 29,
    "\x00" + "a" * 31,
    "a" * 31 + "\x00",
    "a" * 32 + "\n",
    " " + "a" * 31,
    "a" * 16 + "/" + "a" * 15,
]


def _ids(env: RepoEnv, **kwargs: Any) -> list[str]:
    return [s.id for s in env.repo.list_graphs(**kwargs)]


def _names(env: RepoEnv, **kwargs: Any) -> list[str]:
    return [s.name for s in env.repo.list_graphs(**kwargs)]


# --------------------------------------------------------------------------- create / get


def test_create_assigns_id_revision_and_timestamps(env: RepoEnv) -> None:
    created = env.repo.create(create_data("Budget", Spec("about it", ("a", "b"), links=2)))
    assert len(created.id) == 32
    assert created.revision == 1
    assert created.created_at == created.updated_at == NOW
    assert (created.name, created.description, created.tags) == ("Budget", "about it", ["a", "b"])
    assert env.repo.get(created.id) == created


def test_created_ids_are_unique_and_each_create_reads_the_clock_once(env: RepoEnv) -> None:
    ids = {env.repo.create(create_data(f"g{i}")).id for i in range(5)}
    assert len(ids) == 5
    assert env.clock.calls == 5


def test_get_of_an_unknown_id_is_not_found(env: RepoEnv) -> None:
    with pytest.raises(NotFoundError) as info:
        env.repo.get(UNKNOWN)
    assert info.value.message == "Graph not found"
    assert info.value.status_code == 404


@pytest.mark.parametrize("bad", BAD_IDS)
def test_a_malformed_id_is_not_found_everywhere(env: RepoEnv, bad: str) -> None:
    with pytest.raises(NotFoundError, match="Graph not found"):
        env.repo.get(bad)
    with pytest.raises(NotFoundError, match="Graph not found"):
        env.repo.delete(bad)
    with pytest.raises(NotFoundError, match="Graph not found"):
        env.repo.update(bad, update_data(1))
    assert env.repo.count() == 0


# --------------------------------------------------------------------------- update


def test_update_bumps_the_revision_and_replaces_the_fields(env: RepoEnv) -> None:
    created = env.repo.create(create_data("old", Spec("old text", ("x",), links=1)))
    updated = env.repo.update(created.id, update_data(1, "new", Spec("new text", ("y",), links=3)))
    assert updated.id == created.id
    assert updated.revision == 2
    assert updated.created_at == created.created_at == NOW
    assert updated.updated_at == NOW + timedelta(seconds=1)
    assert (updated.name, updated.description, updated.tags) == ("new", "new text", ["y"])
    assert isinstance(updated.source, ManualSource)
    assert len(updated.source.links) == 3
    assert env.repo.get(created.id) == updated


def test_update_with_an_unknown_id_is_not_found(env: RepoEnv) -> None:
    with pytest.raises(NotFoundError, match="Graph not found"):
        env.repo.update(UNKNOWN, update_data(1))


class Stale(NamedTuple):
    given: int
    ok: bool


@pytest.mark.parametrize(
    "case", [Stale(1, False), Stale(2, True), Stale(3, False), Stale(99, False)]
)
def test_only_the_current_revision_may_update(env: RepoEnv, case: Stale) -> None:
    created = env.repo.create(create_data("g"))
    env.repo.update(created.id, update_data(1, "second"))  # now at revision 2
    if case.ok:
        assert env.repo.update(created.id, update_data(case.given, "third")).revision == 3
        return
    with pytest.raises(ConflictError):
        env.repo.update(created.id, update_data(case.given, "rejected"))
    assert env.repo.get(created.id).name == "second"
    assert env.repo.get(created.id).revision == 2


def test_a_stale_update_reports_the_current_revision_and_time(env: RepoEnv) -> None:
    created = env.repo.create(create_data("g"))
    current = env.repo.update(created.id, update_data(1, "second"))
    with pytest.raises(ConflictError) as info:
        env.repo.update(created.id, update_data(1, "late"))
    err = info.value
    assert err.message == "Graph was modified since you loaded it; reload it or save a copy"
    assert err.status_code == 409
    assert err.current_revision == 2
    assert err.current_updated_at == current.updated_at
    assert err.details == ["revision=2", f"updated_at={current.updated_at.isoformat()}"]


# --------------------------------------------------------------------------- put


def test_put_stores_the_graph_verbatim(env: RepoEnv) -> None:
    later = NOW + timedelta(days=3)
    graph = definition(ID_B, "kept", Spec("d", ("t",), links=2, revision=7, updated_at=later))
    assert env.repo.put(graph) == graph
    stored = env.repo.get(ID_B)
    assert stored == graph
    assert (stored.id, stored.revision, stored.created_at, stored.updated_at) == (
        ID_B,
        7,
        NOW,
        later,
    )


def test_put_without_overwrite_refuses_a_taken_id_and_names_its_state(env: RepoEnv) -> None:
    first = definition(ID_A, "first", Spec(revision=4, updated_at=NOW + timedelta(minutes=5)))
    env.repo.put(first)
    with pytest.raises(ConflictError) as info:
        env.repo.put(definition(ID_A, "second"))
    err = info.value
    assert err.message == "A graph with this id already exists"
    assert (err.current_revision, err.current_updated_at) == (4, first.updated_at)
    assert err.details == ["revision=4", f"updated_at={first.updated_at.isoformat()}"]
    assert env.repo.get(ID_A).name == "first"


def test_put_with_overwrite_replaces_the_graph(env: RepoEnv) -> None:
    env.repo.put(definition(ID_A, "first", spec=Spec(links=3)))
    replacement = definition(ID_A, "second", Spec("new", ("z",), links=1, revision=9))
    assert env.repo.put(replacement, overwrite=True) == replacement
    assert env.repo.get(ID_A) == replacement
    assert env.repo.count() == 1


def test_put_with_overwrite_creates_a_missing_graph(env: RepoEnv) -> None:
    env.repo.put(definition(ID_C, "new"), overwrite=True)
    assert env.repo.get(ID_C).name == "new"


# --------------------------------------------------------------------------- listing


def _put_five(env: RepoEnv) -> None:
    """Five graphs, three of them with the same timestamp, inserted out of order."""
    for graph_id, name, stamp in [
        (ID_C, "c", NOW),
        (ID_A, "a", NOW),
        (ID_D, "d", NOW + timedelta(hours=1)),
        (ID_B, "b", NOW),
        (ID_E, "e", NOW - timedelta(hours=1)),
    ]:
        env.repo.put(definition(graph_id, name, Spec(updated_at=stamp)))


def test_listing_order_is_updated_desc_then_id_asc(env: RepoEnv) -> None:
    _put_five(env)
    assert _ids(env) == [ID_D, ID_A, ID_B, ID_C, ID_E]


def test_listing_summaries_carry_the_listing_fields(env: RepoEnv) -> None:
    created = env.repo.create(create_data("Budget", Spec("about", ("a", "b"))))
    [summary] = env.repo.list_graphs()
    assert summary.id == created.id
    assert (summary.name, summary.description, summary.tags) == ("Budget", "about", ["a", "b"])
    assert (summary.source_type, summary.revision, summary.updated_at) == ("manual", 1, NOW)


def test_an_update_moves_the_graph_to_the_top(env: RepoEnv) -> None:
    first = env.repo.create(create_data("first"))
    second = env.repo.create(create_data("second"))
    assert _ids(env) == [second.id, first.id]
    env.repo.update(first.id, update_data(1, "first again"))
    assert _ids(env) == [first.id, second.id]
    assert _names(env) == ["first again", "second"]


class Page(NamedTuple):
    limit: int
    offset: int
    expected: list[str]


ORDER = [ID_D, ID_A, ID_B, ID_C, ID_E]


@pytest.mark.parametrize(
    "case",
    [
        Page(200, 0, ORDER),
        Page(5, 0, ORDER),
        Page(4, 0, ORDER[:4]),
        Page(2, 0, ORDER[:2]),
        Page(2, 2, ORDER[2:4]),
        Page(2, 4, ORDER[4:]),
        Page(2, 5, []),
        Page(2, 50, []),
        Page(1, 0, ORDER[:1]),
        Page(0, 0, []),
        Page(0, 2, []),
        Page(-1, 0, []),
        Page(-7, 3, []),
        Page(2, -1, ORDER[:2]),
        Page(10, 3, ORDER[3:]),
    ],
)
def test_paging_edges(env: RepoEnv, case: Page) -> None:
    _put_five(env)
    assert _ids(env, limit=case.limit, offset=case.offset) == case.expected


def test_a_short_listing_returns_everything_by_default(env: RepoEnv) -> None:
    for i in range(3):
        env.repo.create(create_data(f"g{i}"))
    assert len(env.repo.list_graphs()) == 3
    assert len(env.repo.list_graphs(limit=2)) == 2


# --------------------------------------------------------------------------- search


FIXTURES = [
    ("R&D (2024) [draft]", Spec("", ("finance",))),
    (".*", Spec("wildcard")),
    ("plain", Spec("Quarterly REPORT", ("Alpha", "alphabet"))),
    ("a+b", Spec("", ("alpha",))),
    ("cost $x", Spec("back\\slash")),
]


def _seed_search(env: RepoEnv) -> None:
    for name, spec in FIXTURES:
        env.repo.create(create_data(name, spec))


class Search(NamedTuple):
    query: str | None
    tag: str | None
    names: list[str]


#: Newest first: the fixtures are created in order, one second apart.
ALL = ["cost $x", "a+b", "plain", ".*", "R&D (2024) [draft]"]


@pytest.mark.parametrize(
    "case",
    [
        Search(None, None, ALL),
        Search("", None, ALL),
        Search("   ", None, ALL),
        Search("r&d", None, ["R&D (2024) [draft]"]),
        Search("R&D (2024)", None, ["R&D (2024) [draft]"]),
        Search("(2024)", None, ["R&D (2024) [draft]"]),
        Search("[draft]", None, ["R&D (2024) [draft]"]),
        Search(".*", None, [".*"]),
        Search("a+b", None, ["a+b"]),
        Search("$x", None, ["cost $x"]),
        Search("\\", None, ["cost $x"]),
        Search("^", None, []),
        Search("report", None, ["plain"]),
        Search("QUARTERLY report", None, ["plain"]),
        Search("ALPHA", None, ["a+b", "plain"]),
        Search("alphabe", None, ["plain"]),
        Search("  plain  ", None, ["plain"]),
        Search("zzz", None, []),
        Search(None, "alpha", ["a+b"]),
        Search(None, "Alpha", ["plain"]),
        Search(None, "alphabet", ["plain"]),
        Search(None, "alph", []),
        Search(None, "ALPHA", []),
        Search(None, "finance", ["R&D (2024) [draft]"]),
        Search(None, "", ALL),
        Search("plain", "alpha", []),
        Search("a", "alpha", ["a+b"]),
        Search("alpha", "Alpha", ["plain"]),
    ],
)
def test_search_and_tag_filters(env: RepoEnv, case: Search) -> None:
    _seed_search(env)
    assert _names(env, query=case.query, tag=case.tag) == case.names
    assert env.repo.count(query=case.query, tag=case.tag) == len(case.names)


def test_a_query_never_matches_across_two_fields(env: RepoEnv) -> None:
    env.repo.create(create_data("alpha", Spec("beta", ("gamma",))))
    assert _names(env, query="alpha\nbeta") == []
    assert _names(env, query="beta\ngamma") == []
    assert _names(env, query="alphabeta") == []
    assert _names(env, query="alpha") == ["alpha"]
    assert _names(env, query="gamma") == ["alpha"]


def test_a_search_term_is_cut_to_two_hundred_characters(env: RepoEnv) -> None:
    env.repo.create(create_data("x" * 200))
    assert _names(env, query="x" * 200) == ["x" * 200]
    assert _names(env, query="x" * 300) == ["x" * 200]
    assert _names(env, query="x" * 199 + "y") == []


def test_count_ignores_paging_and_matches_the_filters(env: RepoEnv) -> None:
    _seed_search(env)
    assert env.repo.count() == 5
    assert len(env.repo.list_graphs(limit=2)) == 2
    assert env.repo.count(tag="alpha") == 1
    assert env.repo.count(query="alpha") == 2
    assert env.repo.count(query="alpha", tag="alpha") == 1


def test_all_tags_are_distinct_and_sorted(env: RepoEnv) -> None:
    assert env.repo.all_tags() == []
    env.repo.create(create_data("one", Spec(tags=("beta", "alpha"))))
    env.repo.create(create_data("two", Spec(tags=("alpha", "Zed", "10"))))
    env.repo.create(create_data("three"))
    assert env.repo.all_tags() == ["10", "Zed", "alpha", "beta"]


# --------------------------------------------------------------------------- delete, stream, ping


def test_delete_removes_the_graph_and_a_second_delete_is_not_found(env: RepoEnv) -> None:
    keep, drop = env.repo.create(create_data("keep")), env.repo.create(create_data("drop"))
    env.repo.delete(drop.id)
    assert _ids(env) == [keep.id]
    assert env.repo.count() == 1
    with pytest.raises(NotFoundError, match="Graph not found"):
        env.repo.get(drop.id)
    with pytest.raises(NotFoundError, match="Graph not found"):
        env.repo.delete(drop.id)
    with pytest.raises(NotFoundError, match="Graph not found"):
        env.repo.update(drop.id, update_data(1))


def test_a_deleted_id_can_be_stored_again(env: RepoEnv) -> None:
    env.repo.put(definition(ID_A, "first"))
    env.repo.delete(ID_A)
    env.repo.put(definition(ID_A, "second"))
    assert env.repo.get(ID_A).name == "second"


def test_iter_definitions_streams_full_graphs_in_listing_order(env: RepoEnv) -> None:
    assert list(env.repo.iter_definitions()) == []
    _put_five(env)
    streamed = list(env.repo.iter_definitions())
    assert [g.id for g in streamed] == ORDER
    assert all(g.source.type == "manual" for g in streamed)
    assert streamed[0] == env.repo.get(ID_D)


def test_ping_succeeds_on_a_healthy_store(env: RepoEnv) -> None:
    env.repo.ping()
    env.repo.ping()
