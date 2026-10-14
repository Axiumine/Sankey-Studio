"""``storage.folder_tree``: the pure rules of the folder tree, as tables (both sides of limits)."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.errors import FolderNameTakenError, FolderRuleError, NotFoundError
from sankey_studio.models import FOLDER_DEPTH_MAX, FOLDERS_MAX, FolderDefinition
from sankey_studio.storage import folder_tree
from sankey_studio.storage.folder_tree import (
    Placement,
    check_name_free,
    closure,
    depth_of,
    descendants,
    effective,
    name_key,
    order_parents_first,
    path_of,
    reparent_plan,
    requested_parent,
    subtree_height,
    validate_new_count,
    validate_placement,
    with_counts,
)
from tests.storage.folder_builders import fid, folder


def _chain(length: int) -> list[FolderDefinition]:
    """``length`` nested folders: 1 at the top, 2 inside 1, 3 inside 2, ..."""
    return [folder(n, f"f{n}", None if n == 1 else n - 1) for n in range(1, length + 1)]


def _ids(items: list[FolderDefinition]) -> list[str]:
    return [item.id for item in items]


def _by_id(items: list[FolderDefinition]) -> dict[str, FolderDefinition]:
    return {item.id: item for item in items}


# --------------------------------------------------------------------------- name keys


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Budget", "budget"),
        ("BUDGET", "budget"),
        ("Straße", "strasse"),
        ("café", "café"),
        ("café", "café"),
        ("", ""),
    ],
)
def test_name_key_is_nfc_then_casefold(name: str, expected: str) -> None:
    assert name_key(name) == expected


def test_the_messages_are_fixed_english_sentences() -> None:
    assert folder_tree.MSG_NOT_FOUND == "Folder not found"
    assert folder_tree.MSG_CYCLE == (
        "A collection cannot be moved into itself or into one of its own collections"
    )
    assert folder_tree.MSG_DEPTH == "Collections can be nested at most 8 levels deep"
    assert folder_tree.MSG_COUNT == "At most 1000 collections are allowed"
    assert (
        folder_tree.MSG_NAME_TAKEN == "A collection with this name already exists in the same place"
    )


# --------------------------------------------------------------------------- walks


class Depth(NamedTuple):
    items: list[FolderDefinition]
    start: str | None
    expected: int


DEPTHS = [
    pytest.param(Depth(_chain(3), None, 0), id="top level"),
    pytest.param(Depth(_chain(3), fid(1), 1), id="one"),
    pytest.param(Depth(_chain(3), fid(3), 3), id="three"),
    pytest.param(Depth(_chain(3), fid(99), 0), id="unknown id"),
    pytest.param(Depth(_chain(8), fid(8), 8), id="at the limit"),
    pytest.param(Depth(_chain(9), fid(9), 9), id="one over the limit"),
    pytest.param(Depth(_chain(12), fid(12), 9), id="capped"),
    pytest.param(Depth([folder(1, "a", 2), folder(2, "b", 1)], fid(1), 2), id="cycle"),
    pytest.param(Depth([folder(1, "a", 1)], fid(1), 1), id="own parent"),
    pytest.param(Depth([folder(2, "b", 7)], fid(2), 1), id="missing parent"),
]


@pytest.mark.parametrize("case", DEPTHS)
def test_depth_of(case: Depth) -> None:
    assert depth_of(_by_id(case.items), case.start) == case.expected


def test_a_long_cycle_is_capped_one_over_the_limit() -> None:
    ring = [folder(n, f"r{n}", n % 12 + 1) for n in range(1, 13)]
    assert depth_of(_by_id(ring), fid(1)) == FOLDER_DEPTH_MAX + 1


def test_path_of_runs_from_the_top_down_to_the_folder() -> None:
    assert _ids(path_of(_chain(3), fid(3))) == [fid(1), fid(2), fid(3)]
    assert _ids(path_of(_chain(3), fid(1))) == [fid(1)]


@pytest.mark.parametrize("start", [None, fid(99)], ids=["top level", "unknown"])
def test_path_of_nothing_is_empty(start: str | None) -> None:
    assert path_of(_chain(3), start) == []


def test_path_of_stops_at_a_missing_parent_and_at_a_cycle() -> None:
    assert _ids(path_of([folder(2, "b", 7), folder(3, "c", 2)], fid(3))) == [fid(2), fid(3)]
    ring = [folder(1, "a", 2), folder(2, "b", 1)]
    assert sorted(_ids(path_of(ring, fid(1)))) == [fid(1), fid(2)]


TREE = [
    folder(1, "root"),
    folder(2, "a", 1),
    folder(3, "b", 1),
    folder(4, "a1", 2),
    folder(5, "a2", 2),
    folder(6, "a1x", 4),
    folder(7, "other"),
]


@pytest.mark.parametrize(
    ("start", "height"), [(1, 4), (2, 3), (3, 1), (4, 2), (6, 1), (7, 1), (99, 1)]
)
def test_subtree_height(start: int, height: int) -> None:
    assert subtree_height(TREE, fid(start)) == height


@pytest.mark.parametrize(
    ("start", "below"),
    [(1, {2, 3, 4, 5, 6}), (2, {4, 5, 6}), (4, {6}), (3, set()), (7, set()), (99, set())],
)
def test_descendants(start: int, below: set[int]) -> None:
    assert descendants(TREE, fid(start)) == {fid(n) for n in below}


def test_walks_down_a_hand_made_cycle_terminate() -> None:
    ring = [folder(1, "a", 2), folder(2, "b", 3), folder(3, "c", 1), folder(4, "d", 3)]
    assert descendants(ring, fid(1)) == {fid(2), fid(3), fid(4)}
    assert subtree_height(ring, fid(1)) == 3


# --------------------------------------------------------------------------- placement


class Place(NamedTuple):
    items: list[FolderDefinition]
    folder_id: int | None
    parent: int | None
    name: str


def _place(case: Place) -> Placement:
    return Placement(
        None if case.folder_id is None else fid(case.folder_id),
        None if case.parent is None else fid(case.parent),
        case.name,
    )


ALLOWED = [
    pytest.param(Place([], None, None, "new"), id="first folder"),
    pytest.param(Place(_chain(7), None, 7, "deep"), id="create at depth 8"),
    pytest.param(Place(TREE, 2, 3, "a"), id="move a subtree where it fits"),
    pytest.param(Place(TREE, 6, None, "a1x"), id="move to the top level"),
    pytest.param(Place([*_chain(6), folder(20, "x"), folder(21, "y", 20)], 20, 6, "x"), id="fits"),
    pytest.param(Place(TREE, 2, 1, "A"), id="the same place and name"),
    pytest.param(Place(TREE, 2, 1, "renamed"), id="rename"),
    pytest.param(Place(TREE, None, 2, "b"), id="same name, other parent"),
    pytest.param(Place(TREE, None, 1, "é"), id="a new name"),
]


@pytest.mark.parametrize("case", ALLOWED)
def test_validate_placement_accepts(case: Place) -> None:
    validate_placement(case.items, _place(case))


class Refused(NamedTuple):
    case: Place
    error: type[Exception]
    message: str


DEEP = [*_chain(6), folder(20, "x"), folder(21, "y", 20), folder(22, "z", 21)]
REFUSED = [
    pytest.param(
        Refused(Place(TREE, None, 99, "n"), NotFoundError, folder_tree.MSG_NOT_FOUND),
        id="unknown parent",
    ),
    pytest.param(
        Refused(Place(TREE, 1, 1, "root"), FolderRuleError, folder_tree.MSG_CYCLE), id="into itself"
    ),
    pytest.param(
        Refused(Place(TREE, 1, 4, "root"), FolderRuleError, folder_tree.MSG_CYCLE),
        id="into a grandchild",
    ),
    pytest.param(
        Refused(Place(TREE, 2, 6, "a"), FolderRuleError, folder_tree.MSG_CYCLE), id="into a child"
    ),
    pytest.param(
        Refused(Place(_chain(8), None, 8, "deep"), FolderRuleError, folder_tree.MSG_DEPTH),
        id="create at depth 9",
    ),
    pytest.param(
        Refused(Place(DEEP, 20, 6, "x"), FolderRuleError, folder_tree.MSG_DEPTH),
        id="a subtree of 3 under depth 6",
    ),
    pytest.param(
        Refused(Place(TREE, None, 2, "A1"), FolderNameTakenError, folder_tree.MSG_NAME_TAKEN),
        id="name clash by case",
    ),
    pytest.param(
        Refused(
            Place([folder(1, "café")], None, None, "café"),
            FolderNameTakenError,
            folder_tree.MSG_NAME_TAKEN,
        ),
        id="name clash by normalisation",
    ),
    pytest.param(
        Refused(Place(TREE, 3, 2, "A1"), FolderNameTakenError, folder_tree.MSG_NAME_TAKEN),
        id="a move into a place that has the name",
    ),
]


@pytest.mark.parametrize("refused", REFUSED)
def test_validate_placement_refuses(refused: Refused) -> None:
    with pytest.raises(refused.error) as info:
        validate_placement(refused.case.items, _place(refused.case))
    assert info.value.message == refused.message  # type: ignore[attr-defined]


def test_a_move_that_just_fits_the_depth_limit_is_allowed() -> None:
    items = [*_chain(6), folder(20, "x"), folder(21, "y", 20)]
    validate_placement(items, Placement(fid(20), fid(6), "x"))  # 6 + height 2 == 8
    with pytest.raises(FolderRuleError):  # 7 + height 2 == 9
        validate_placement(
            [*_chain(7), folder(20, "x"), folder(21, "y", 20)], Placement(fid(20), fid(7), "x")
        )


def test_the_checks_run_in_order_parent_cycle_depth_name() -> None:
    # into itself AND too deep AND a name clash: the cycle is reported
    items = [*_chain(8), folder(30, "x", 8)]
    with pytest.raises(FolderRuleError) as info:
        validate_placement(items, Placement(fid(30), fid(30), "x"))
    assert info.value.message == folder_tree.MSG_CYCLE
    # too deep AND a name clash: the depth is reported
    with pytest.raises(FolderRuleError) as info:
        validate_placement(items, Placement(None, fid(8), "x"))
    assert info.value.message == folder_tree.MSG_DEPTH
    # unknown parent comes before everything
    with pytest.raises(NotFoundError):
        validate_placement(items, Placement(fid(30), fid(99), "x"))


def test_a_folder_may_keep_its_own_name_but_not_take_a_siblings() -> None:
    items = [folder(1, "one"), folder(2, "two")]
    validate_placement(items, Placement(fid(1), None, "ONE"))
    with pytest.raises(FolderNameTakenError):
        validate_placement(items, Placement(fid(1), None, "Two"))


def test_a_placement_below_a_hand_made_ring_does_not_loop() -> None:
    ring = [folder(1, "a", 2), folder(2, "b", 1), folder(3, "c")]
    validate_placement(ring, Placement(None, fid(1), "new"))
    validate_placement(ring, Placement(fid(3), None, "c"))


def test_a_ring_as_long_as_the_limit_reads_as_too_deep() -> None:
    ring = [folder(n, f"r{n}", n % 8 + 1) for n in range(1, 9)]
    with pytest.raises(FolderRuleError) as info:
        validate_placement(ring, Placement(None, fid(1), "new"))
    assert info.value.message == folder_tree.MSG_DEPTH


# --------------------------------------------------------------------------- count


@pytest.mark.parametrize(
    ("count", "ok"), [(0, True), (FOLDERS_MAX - 1, True), (FOLDERS_MAX, False)]
)
def test_validate_new_count(count: int, ok: bool) -> None:
    items = [folder(n + 1, f"f{n}") for n in range(count)]
    if ok:
        validate_new_count(items)
        return
    with pytest.raises(FolderRuleError) as info:
        validate_new_count(items)
    assert info.value.message == folder_tree.MSG_COUNT


# --------------------------------------------------------------------------- delete plan


def test_reparent_plan_sends_children_to_the_parent_of_the_deleted_folder() -> None:
    assert reparent_plan(TREE, fid(2)) == [(fid(4), fid(1)), (fid(5), fid(1))]
    assert reparent_plan(TREE, fid(1)) == [(fid(2), None), (fid(3), None)]
    assert reparent_plan(TREE, fid(3)) == []


def test_reparent_plan_refuses_a_name_that_is_taken_at_the_target() -> None:
    items = [folder(1, "top"), folder(2, "A", 1), folder(3, "Docs", 2), folder(5, "docs", 1)]
    with pytest.raises(FolderNameTakenError) as info:
        reparent_plan(items, fid(2))
    assert info.value.message == folder_tree.MSG_NAME_TAKEN
    assert reparent_plan(items, fid(1)) == [(fid(2), None), (fid(5), None)]


def test_a_child_may_take_the_name_of_the_folder_that_is_deleted() -> None:
    items = [folder(1, "same"), folder(2, "Same", 1)]
    assert reparent_plan(items, fid(1)) == [(fid(2), None)]


def test_reparent_plan_of_an_unknown_folder_moves_its_orphans_to_the_top() -> None:
    assert reparent_plan([folder(2, "orphan", 9)], fid(9)) == [(fid(2), None)]
    assert reparent_plan([folder(2, "x")], fid(9)) == []


# --------------------------------------------------------------------------- membership


def test_effective_reads_an_unknown_folder_as_the_top_level() -> None:
    known = {fid(1), fid(2)}
    assert effective(fid(1), known) == fid(1)
    assert effective(fid(3), known) is None
    assert effective(None, known) is None
    assert effective(fid(1), set()) is None


def test_with_counts_lists_name_then_id_order_with_both_counts() -> None:
    items = [folder(3, "Bee"), folder(1, "bee", 3), folder(2, "Ant"), folder(4, "bee", 2)]
    rows = with_counts(items, {fid(3): 5, None: 7, fid(2): 1})
    assert [r.id for r in rows] == [fid(2), fid(1), fid(3), fid(4)]
    assert [(r.graph_count, r.child_count) for r in rows] == [(1, 1), (0, 0), (5, 1), (0, 0)]
    assert rows[2].name == "Bee"
    assert rows[1].parent_id == fid(3)
    assert (rows[0].revision, rows[0].updated_at) == (1, items[2].updated_at)


def test_with_counts_ignores_children_of_a_missing_parent() -> None:
    rows = with_counts([folder(1, "orphan", 9)], {})
    assert [(r.graph_count, r.child_count) for r in rows] == [(0, 0)]


# --------------------------------------------------------------------------- ordering


def test_order_parents_first_is_stable_and_puts_cycles_last() -> None:
    items = [
        folder(5, "e", 4),
        folder(4, "d", 3),
        folder(3, "c"),
        folder(9, "ring-a", 10),
        folder(10, "ring-b", 9),
        folder(6, "f"),
        folder(7, "orphan", 99),
    ]
    assert _ids(order_parents_first(items)) == [fid(n) for n in (3, 6, 7, 4, 5, 9, 10)]


def test_order_parents_first_of_nothing_is_empty() -> None:
    assert order_parents_first([]) == []


def test_closure_adds_the_ancestors_and_orders_parents_first() -> None:
    chosen = closure(list(reversed(TREE)), {fid(6), fid(3)})
    assert _ids(chosen) == [fid(1), fid(3), fid(2), fid(4), fid(6)]
    assert closure(TREE, set()) == []
    assert closure(TREE, {fid(99)}) == []
    assert _ids(closure(TREE, [fid(7)])) == [fid(7)]


def test_closure_of_a_cycle_terminates() -> None:
    ring = [folder(1, "a", 2), folder(2, "b", 1)]
    assert sorted(_ids(closure(ring, {fid(1)}))) == [fid(1), fid(2)]


def test_name_clashes_compare_the_effective_parent() -> None:
    orphan = [folder(1, "Kid", 99), folder(2, "Pal", 3), folder(3, "Home")]
    with pytest.raises(FolderNameTakenError):
        check_name_free(orphan, None, "kid", None)  # an orphan reads as top level
    with pytest.raises(FolderNameTakenError):
        check_name_free(orphan, fid(99), "KID", None)  # and so does a missing target parent
    check_name_free(orphan, fid(3), "Kid", None)  # a real sibling list is unaffected
    check_name_free(orphan, None, "Kid", fid(1))  # the folder itself is not a clash


@pytest.mark.parametrize(
    ("stored", "asked", "expected"),
    [
        (99, 99, None),  # repeats a missing parent: healed
        (99, 98, 98),  # a different missing parent is passed on (and refused later)
        (99, 3, 3),
        (99, None, None),
        (3, 3, 3),  # an existing parent is kept
        (None, None, None),
    ],
)
def test_requested_parent_heals_only_a_repeated_missing_parent(
    stored: int | None, asked: int | None, expected: int | None
) -> None:
    items = [folder(1, "Kid", stored), folder(3, "Home")]
    parent = None if asked is None else fid(asked)
    want = None if expected is None else fid(expected)
    assert requested_parent(items, items[0], parent) == want
