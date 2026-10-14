"""Behaviour every ``FolderRepository`` must show, run once per backend: records and rules."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import ConflictError, FolderNameTakenError, FolderRuleError, NotFoundError
from sankey_studio.models import FOLDER_DEPTH_MAX, FolderUpdate
from sankey_studio.storage import folder_tree
from tests.storage.folder_builders import body, fid, folder
from tests.storage.support import NOW

if TYPE_CHECKING:
    from sankey_studio.models import FolderDefinition
    from tests.storage.conftest import FolderEnv

UNKNOWN = fid(0xDEAD)
BAD_IDS = ["", "a" * 31, "a" * 33, "A" * 32, "../x", "..%2f", "\x00" + "a" * 31, "a" * 32 + "\n"]


def _make(env: FolderEnv, name: str, parent: FolderDefinition | None = None) -> FolderDefinition:
    return env.folders.create_folder(body(name, None if parent is None else parent.id))


def _update(
    env: FolderEnv, current: FolderDefinition, *, name: str | None = None, parent: str | None = ""
) -> FolderDefinition:
    """Rename and/or move ``current`` (``parent=""`` keeps the parent; ``None`` = top level)."""
    return env.folders.update_folder(
        current.id,
        FolderUpdate(
            name=name or current.name,
            parent_id=current.parent_id if parent == "" else parent,
            revision=current.revision,
        ),
    )


def _names(env: FolderEnv) -> list[str]:
    return [row.name for row in env.folders.list_folders()]


# --------------------------------------------------------------------------- create / get


def test_create_assigns_id_revision_and_timestamps(folder_env: FolderEnv) -> None:
    created = _make(folder_env, "Finance")
    assert len(created.id) == 32
    assert (created.revision, created.schema_version) == (1, 1)
    assert created.created_at == created.updated_at == NOW
    assert (created.name, created.parent_id) == ("Finance", None)
    assert folder_env.folders.get_folder(created.id) == created


def test_created_ids_are_unique_and_each_create_reads_the_clock_once(folder_env: FolderEnv) -> None:
    ids = {_make(folder_env, f"f{i}").id for i in range(5)}
    assert len(ids) == 5
    assert folder_env.clock.calls == 5


def test_a_folder_is_created_inside_another(folder_env: FolderEnv) -> None:
    outer = _make(folder_env, "Outer")
    inner = _make(folder_env, "Inner", outer)
    assert inner.parent_id == outer.id
    assert folder_env.folders.get_folder(inner.id).parent_id == outer.id


def test_get_of_an_unknown_id_is_not_found(folder_env: FolderEnv) -> None:
    with pytest.raises(NotFoundError) as info:
        folder_env.folders.get_folder(UNKNOWN)
    assert info.value.message == "Folder not found"
    assert info.value.status_code == 404


@pytest.mark.parametrize("bad", BAD_IDS)
def test_a_malformed_id_is_not_found_everywhere(folder_env: FolderEnv, bad: str) -> None:
    repo = folder_env.folders
    update = FolderUpdate(name="x", parent_id=None, revision=1)
    with pytest.raises(NotFoundError):
        repo.get_folder(bad)
    with pytest.raises(NotFoundError):
        repo.update_folder(bad, update)
    with pytest.raises(NotFoundError):
        repo.delete_folder(bad)
    assert repo.list_folders() == []


def test_a_create_below_an_unknown_parent_is_not_found_and_stores_nothing(
    folder_env: FolderEnv,
) -> None:
    with pytest.raises(NotFoundError):
        folder_env.folders.create_folder(body("x", UNKNOWN))
    assert folder_env.folders.list_folders() == []


# --------------------------------------------------------------------------- listing


def test_list_folders_is_name_then_id_order_with_counts(folder_env: FolderEnv) -> None:
    beta = _make(folder_env, "beta")
    alpha = _make(folder_env, "Alpha")
    child = _make(folder_env, "Child", beta)
    rows = folder_env.folders.list_folders()
    assert [row.id for row in rows] == [alpha.id, beta.id, child.id]
    assert [(r.graph_count, r.child_count) for r in rows] == [(0, 0), (0, 1), (0, 0)]
    assert rows[1].parent_id is None
    assert rows[2].parent_id == beta.id
    assert (rows[0].revision, rows[0].updated_at) == (alpha.revision, alpha.updated_at)


def test_list_definitions_are_the_full_records_in_the_same_order(folder_env: FolderEnv) -> None:
    second = _make(folder_env, "b")
    first = _make(folder_env, "A")
    assert folder_env.folders.list_definitions() == [first, second]


def test_two_folders_with_one_name_key_are_ordered_by_id(folder_env: FolderEnv) -> None:
    outer_a, outer_b = _make(folder_env, "a"), _make(folder_env, "b")
    in_a = _make(folder_env, "same", outer_a)
    in_b = _make(folder_env, "Same", outer_b)
    ordered = sorted([in_a.id, in_b.id])
    rows = [r.id for r in folder_env.folders.list_folders() if r.id in ordered]
    assert rows == ordered


# --------------------------------------------------------------------------- update


def test_update_renames_and_bumps_the_revision_and_updated_at(folder_env: FolderEnv) -> None:
    created = _make(folder_env, "old")
    renamed = _update(folder_env, created, name="new")
    assert (renamed.name, renamed.revision) == ("new", 2)
    assert renamed.created_at == created.created_at
    assert renamed.updated_at == created.updated_at + timedelta(seconds=1)
    assert folder_env.folders.get_folder(created.id) == renamed
    assert _names(folder_env) == ["new"]


def test_update_moves_a_folder_to_another_parent_and_back_to_the_top(folder_env: FolderEnv) -> None:
    target, moved = _make(folder_env, "target"), _make(folder_env, "moved")
    inside = _update(folder_env, moved, parent=target.id)
    assert inside.parent_id == target.id
    assert _update(folder_env, inside, parent=None).parent_id is None


class Stale(NamedTuple):
    given: int
    ok: bool


@pytest.mark.parametrize(
    "case", [Stale(1, False), Stale(2, True), Stale(3, False), Stale(99, False)]
)
def test_update_needs_the_stored_revision(folder_env: FolderEnv, case: Stale) -> None:
    created = _make(folder_env, "f")
    _update(folder_env, created, name="f2")  # the stored revision is 2 now
    data = FolderUpdate(name="g", parent_id=None, revision=case.given)
    if case.ok:
        assert folder_env.folders.update_folder(created.id, data).revision == 3
        return
    with pytest.raises(ConflictError) as info:
        folder_env.folders.update_folder(created.id, data)
    assert info.value.message == "Collection was modified since you loaded it; reload it"
    assert info.value.details[0] == "revision=2"
    assert folder_env.folders.get_folder(created.id).name == "f2"


def test_a_second_update_with_the_old_revision_is_a_conflict(folder_env: FolderEnv) -> None:
    created = _make(folder_env, "f")
    _update(folder_env, created, name="g")
    with pytest.raises(ConflictError) as info:
        _update(folder_env, created, name="h")
    assert info.value.current_revision == 2


def test_a_stale_revision_is_reported_before_the_rules(folder_env: FolderEnv) -> None:
    top = _make(folder_env, "top")
    inner = _make(folder_env, "inner", top)
    _update(folder_env, top, name="top 2")  # `top` is at revision 2 now
    cycle = FolderUpdate(name="top", parent_id=inner.id, revision=1)
    with pytest.raises(ConflictError):  # the move would be a cycle, but the revision is stale
        folder_env.folders.update_folder(top.id, cycle)


def test_update_of_an_unknown_id_is_not_found(folder_env: FolderEnv) -> None:
    with pytest.raises(NotFoundError):
        folder_env.folders.update_folder(
            UNKNOWN, FolderUpdate(name="x", parent_id=None, revision=1)
        )


# --------------------------------------------------------------------------- the rules


@pytest.mark.parametrize("second", ["same", "SAME", "Same", "sAmE"])
def test_sibling_names_are_unique_ignoring_case(folder_env: FolderEnv, second: str) -> None:
    _make(folder_env, "same")
    with pytest.raises(FolderNameTakenError) as info:
        _make(folder_env, second)
    assert info.value.message == "A collection with this name already exists in the same place"
    assert info.value.status_code == 409
    assert info.value.code == "folder_name_taken"
    assert _names(folder_env) == ["same"]


def test_sibling_names_are_unique_after_unicode_normalisation(folder_env: FolderEnv) -> None:
    _make(folder_env, "café")
    with pytest.raises(FolderNameTakenError):
        _make(folder_env, "café")


def test_one_name_may_be_used_in_different_parents(folder_env: FolderEnv) -> None:
    one, two = _make(folder_env, "one"), _make(folder_env, "two")
    _make(folder_env, "docs", one)
    _make(folder_env, "docs", two)
    assert _make(folder_env, "docs").parent_id is None
    assert _names(folder_env).count("docs") == 3


def test_a_rename_or_move_onto_a_siblings_name_is_refused(folder_env: FolderEnv) -> None:
    outer = _make(folder_env, "outer")
    _make(folder_env, "taken", outer)
    mover = _make(folder_env, "taken")
    with pytest.raises(FolderNameTakenError):
        _update(folder_env, mover, parent=outer.id)
    other = _make(folder_env, "other", outer)
    with pytest.raises(FolderNameTakenError):
        _update(folder_env, other, name="TAKEN")
    assert _update(folder_env, other, name="OTHER").name == "OTHER"  # its own name, other case


def test_nesting_is_allowed_to_the_depth_limit_and_not_below(folder_env: FolderEnv) -> None:
    parent: FolderDefinition | None = None
    for level in range(FOLDER_DEPTH_MAX):
        parent = _make(folder_env, f"level {level + 1}", parent)
    with pytest.raises(FolderRuleError) as info:
        _make(folder_env, "too deep", parent)
    assert info.value.message == "Collections can be nested at most 8 levels deep"
    assert (info.value.status_code, info.value.code) == (422, "folder_rule")
    assert len(folder_env.folders.list_folders()) == FOLDER_DEPTH_MAX


def test_a_subtree_cannot_be_moved_past_the_depth_limit(folder_env: FolderEnv) -> None:
    top = _make(folder_env, "top")
    for level in range(FOLDER_DEPTH_MAX - 2):  # a chain below `top`: depth 7 at the end
        top = _make(folder_env, f"c{level}", top)
    pair = _make(folder_env, "pair")
    _make(folder_env, "leaf", pair)
    with pytest.raises(FolderRuleError):
        _update(folder_env, pair, parent=top.id)  # 7 + a subtree of 2 = 9


def test_a_folder_cannot_move_into_itself_or_below_itself(folder_env: FolderEnv) -> None:
    top = _make(folder_env, "top")
    mid = _make(folder_env, "mid", top)
    low = _make(folder_env, "low", mid)
    expected = "A collection cannot be moved into itself or into one of its own collections"
    for target in (top, mid, low):
        with pytest.raises(FolderRuleError) as info:
            _update(folder_env, top, parent=target.id)
        assert info.value.message == expected
    assert folder_env.folders.get_folder(top.id).parent_id is None


def test_the_number_of_folders_is_capped(
    folder_env: FolderEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(folder_tree, "FOLDERS_MAX", 3)
    for i in range(3):
        _make(folder_env, f"f{i}")
    with pytest.raises(FolderRuleError) as info:
        _make(folder_env, "one more")
    assert info.value.message == "At most 1000 collections are allowed"
    assert len(_names(folder_env)) == 3
    renamed = folder_env.folders.list_definitions()[0]
    assert _update(folder_env, renamed, name="still fine").name == "still fine"


# --------------------------------------------------------------------------- put


def test_put_keeps_every_field_verbatim(folder_env: FolderEnv) -> None:
    given = folder(7, "Kept", revision=5)
    stored = folder_env.folders.put_folder(given)
    assert stored == given
    assert folder_env.folders.get_folder(given.id) == given
    assert folder_env.clock.calls == 0


def test_put_of_a_taken_id_is_a_conflict_unless_it_overwrites(folder_env: FolderEnv) -> None:
    folder_env.folders.put_folder(folder(7, "old", revision=3))
    with pytest.raises(ConflictError) as info:
        folder_env.folders.put_folder(folder(7, "new"))
    assert info.value.message == "A collection with this id already exists"
    assert info.value.details[0] == "revision=3"
    assert folder_env.folders.get_folder(fid(7)).name == "old"
    folder_env.folders.put_folder(folder(7, "new", revision=4), overwrite=True)
    assert (folder_env.folders.get_folder(fid(7)).name, _names(folder_env)) == ("new", ["new"])


def test_put_refuses_a_name_that_another_folder_has_in_the_same_place(
    folder_env: FolderEnv,
) -> None:
    folder_env.folders.put_folder(folder(1, "Docs"))
    with pytest.raises(FolderNameTakenError):
        folder_env.folders.put_folder(folder(2, "docs"))
    with pytest.raises(FolderNameTakenError):
        folder_env.folders.put_folder(folder(2, "DOCS"), overwrite=True)
    folder_env.folders.put_folder(folder(1, "DOCS"), overwrite=True)  # its own name
    folder_env.folders.put_folder(folder(3, "docs", 1))  # another parent
    assert sorted(_names(folder_env)) == ["DOCS", "docs"]


def test_put_counts_new_folders_only(
    folder_env: FolderEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(folder_tree, "FOLDERS_MAX", 2)
    folder_env.folders.put_folder(folder(1, "a"))
    folder_env.folders.put_folder(folder(2, "b"))
    with pytest.raises(FolderRuleError):
        folder_env.folders.put_folder(folder(3, "c"))
    folder_env.folders.put_folder(folder(2, "b2"), overwrite=True)  # a replacement is not new
    assert sorted(_names(folder_env)) == ["a", "b2"]


def test_put_does_not_check_depth_or_cycles(folder_env: FolderEnv) -> None:
    ring = [folder(1, "a", 2), folder(2, "b", 1)]
    for item in ring:
        folder_env.folders.put_folder(item)
    assert len(folder_env.folders.list_folders()) == 2


# --------------------------------------------------------------------------- ping


def test_ping_succeeds_on_a_usable_store(folder_env: FolderEnv) -> None:
    folder_env.folders.ping()


# --------------------------------------------------------------------------- a missing parent


def _orphan(env: FolderEnv, name: str = "Kid") -> FolderDefinition:
    """A stored folder whose parent record is gone (it reads as a top-level one)."""
    return env.folders.put_folder(folder(5, name, 99))


def test_a_rename_that_repeats_the_missing_parent_heals_it_to_the_top_level(
    folder_env: FolderEnv,
) -> None:
    orphan = _orphan(folder_env)
    renamed = _update(folder_env, orphan, name="Renamed")
    assert (renamed.name, renamed.parent_id, renamed.revision) == ("Renamed", None, 2)
    assert folder_env.folders.get_folder(orphan.id).parent_id is None


def test_a_move_to_a_different_missing_parent_is_still_not_found(folder_env: FolderEnv) -> None:
    orphan = _orphan(folder_env)
    with pytest.raises(NotFoundError):
        _update(folder_env, orphan, parent=fid(98))
    assert folder_env.folders.get_folder(orphan.id).parent_id == fid(99)


def test_an_orphan_takes_part_in_the_top_level_name_check(folder_env: FolderEnv) -> None:
    _orphan(folder_env)
    with pytest.raises(FolderNameTakenError):
        _make(folder_env, "KID")
    other = _make(folder_env, "Other")
    with pytest.raises(FolderNameTakenError):
        _update(folder_env, other, name="kid")
    with pytest.raises(FolderNameTakenError):
        folder_env.folders.put_folder(folder(6, "kid"))


def test_an_orphan_renamed_onto_a_top_level_name_is_refused(folder_env: FolderEnv) -> None:
    orphan = _orphan(folder_env)
    _make(folder_env, "Taken")
    with pytest.raises(FolderNameTakenError):
        _update(folder_env, orphan, name="taken")
