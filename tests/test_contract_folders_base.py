# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests for ``storage.folders_base``: ids, scopes, stored records and the Protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import NotFoundError, StorageError
from sankey_studio.models import MoveReport
from sankey_studio.storage.folders_base import (
    MSG_EXISTS,
    MSG_NOT_FOUND,
    MSG_STALE,
    MSG_UNREADABLE,
    ROOT_SCOPE,
    FolderRepository,
    check_folder_id,
    exists_error,
    new_folder_id,
    parse_folder,
    scope_id,
    stale_error,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sankey_studio.models import (
        FolderCreate,
        FolderDefinition,
        FolderSummary,
        FolderUpdate,
        GraphSummary,
    )

NOW = datetime(2025, 5, 1, 12, 0, tzinfo=UTC)
ID = "a" * 32
BAD_IDS = [
    "",
    "a" * 31,
    "a" * 33,
    "A" * 32,
    "g" * 32,
    "../x",
    "..%2f",
    "\x00" + "a" * 31,
    "a" * 32 + "\n",
    " " + "a" * 31,
    "root",
    "ROOT",
]


def _record(**changes: Any) -> dict[str, Any]:
    base = {"id": ID, "name": "Finance", "parent_id": None, "created_at": NOW, "updated_at": NOW}
    return {**base, **changes}


def test_the_top_level_scope_is_not_a_valid_id() -> None:
    assert ROOT_SCOPE == "root"
    with pytest.raises(NotFoundError):
        check_folder_id(ROOT_SCOPE)


def test_new_ids_are_valid_and_unique() -> None:
    ids = {new_folder_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(check_folder_id(folder_id) == folder_id for folder_id in ids)


@pytest.mark.parametrize("bad", BAD_IDS)
def test_a_malformed_id_is_not_found(bad: str) -> None:
    with pytest.raises(NotFoundError) as info:
        check_folder_id(bad)
    assert info.value.message == "Folder not found" == MSG_NOT_FOUND
    assert info.value.status_code == 404


def test_scope_id_maps_the_top_level_to_none_and_ids_to_themselves() -> None:
    assert scope_id(ROOT_SCOPE) is None
    assert scope_id(ID) == ID


@pytest.mark.parametrize("bad", [b for b in BAD_IDS if b != "root"])
def test_scope_id_refuses_anything_else(bad: str) -> None:
    with pytest.raises(NotFoundError):
        scope_id(bad)


def test_parse_folder_strips_the_mongo_id_and_defaults_the_schema_version() -> None:
    folder = parse_folder({**_record(), "_id": "ignored"})
    assert (folder.id, folder.name, folder.parent_id) == (ID, "Finance", None)
    assert (folder.schema_version, folder.revision) == (1, 1)


def test_parse_folder_does_not_mutate_its_input() -> None:
    doc = {**_record(), "_id": "x"}
    parse_folder(doc)
    assert "_id" in doc
    assert "schema_version" not in doc


def test_parse_folder_ignores_fields_a_later_version_added() -> None:
    assert parse_folder(_record(added_later=1)).id == ID


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": 99}, "Stored folder was written by a newer version of sankey-studio"),
        ({"schema_version": 0}, "Stored folder has an invalid schema version"),
        ({"schema_version": "1"}, "Stored folder has an invalid schema version"),
        ({"name": ""}, MSG_UNREADABLE),
        ({"id": "nope"}, MSG_UNREADABLE),
        ({"created_at": datetime(2025, 1, 1)}, MSG_UNREADABLE),  # noqa: DTZ001 - naive on purpose
        ({"revision": 0}, MSG_UNREADABLE),
    ],
)
def test_parse_folder_refuses_unusable_records_with_a_fixed_message(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(StorageError) as info:
        parse_folder(_record(**changes))
    assert info.value.message == message


def test_an_unreadable_record_does_not_echo_its_content() -> None:
    with pytest.raises(StorageError) as info:
        parse_folder(_record(name="hunter2" * 100, parent_id="not-an-id"))
    assert "hunter2" not in info.value.message
    assert MSG_UNREADABLE == "Stored folder is unreadable"


def test_the_stale_error_is_a_conflict_that_carries_the_current_state() -> None:
    err = stale_error(4, NOW)
    assert err.status_code == 409
    assert err.code == "conflict"
    assert err.message == MSG_STALE == "Collection was modified since you loaded it; reload it"
    assert err.details == ["revision=4", f"updated_at={NOW.isoformat()}"]
    assert stale_error(None, None).details == []


def test_the_exists_error_names_the_taken_id() -> None:
    err = exists_error(2, NOW)
    assert err.code == "conflict"
    assert err.message == MSG_EXISTS == "A collection with this id already exists"
    assert err.details == ["revision=2", f"updated_at={NOW.isoformat()}"]
    assert exists_error(None, None).details == []


def test_protocol_surface_is_frozen() -> None:
    names = {n for n in vars(FolderRepository) if not n.startswith("_")}
    assert names == {
        "list_folders",
        "list_definitions",
        "get_folder",
        "create_folder",
        "update_folder",
        "delete_folder",
        "put_folder",
        "list_in",
        "count_in",
        "move_graphs",
        "ping",
    }


class _Stub:
    """Compile-time proof (mypy) that the Protocol is implementable with these signatures."""

    def list_folders(self) -> list[FolderSummary]:
        return []

    def list_definitions(self) -> list[FolderDefinition]:
        return []

    def get_folder(self, folder_id: str) -> FolderDefinition:
        raise NotFoundError(folder_id)

    def create_folder(self, data: FolderCreate) -> FolderDefinition:
        raise NotImplementedError

    def update_folder(self, folder_id: str, data: FolderUpdate) -> FolderDefinition:
        raise NotImplementedError

    def delete_folder(self, folder_id: str) -> None:
        raise NotFoundError(folder_id)

    def put_folder(self, folder: FolderDefinition, *, overwrite: bool = False) -> FolderDefinition:
        del overwrite  # the stub only has to match the Protocol signature
        return folder

    def list_in(self, scope: str, *, limit: int = 200, offset: int = 0) -> list[GraphSummary]:
        del scope, limit, offset  # the stub only has to match the Protocol signature
        return []

    def count_in(self, scope: str) -> int:
        del scope  # the stub only has to match the Protocol signature
        return 0

    def move_graphs(self, ids: Sequence[str], folder_id: str | None) -> MoveReport:
        del ids, folder_id  # the stub only has to match the Protocol signature
        return MoveReport(moved=0, missing=[])

    def ping(self) -> None:
        return None


def test_stub_satisfies_protocol() -> None:
    repo: FolderRepository = _Stub()
    assert repo.list_folders() == []
    assert repo.count_in(ROOT_SCOPE) == 0
    assert repo.move_graphs([], None).moved == 0
