# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The import mode of a bundle is a closed set: any other word is refused up front."""

from __future__ import annotations

import inspect
from typing import Any, get_args

import pytest

from sankey_studio import errors
from sankey_studio.errors import SankeyError
from sankey_studio.storage import FileGraphRepository, MongoGraphRepository, bundle, migrate
from sankey_studio.storage.bundle import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    IMPORT_MODES,
    BundleError,
    ImportMode,
    import_bundle,
)
from tests.storage.support import ID_A, ID_B, definition

UNKNOWN_MODE = "Unknown import mode; use one of: new_ids, keep_ids"


def _bundle(*ids: str) -> dict[str, Any]:
    graphs = [definition(graph_id, graph_id[:1]).model_dump(mode="json") for graph_id in ids]
    return {"format": BUNDLE_FORMAT, "version": BUNDLE_VERSION, "graphs": graphs}


def test_the_modes_are_exactly_the_two_documented_words() -> None:
    assert IMPORT_MODES == ("new_ids", "keep_ids")
    assert set(IMPORT_MODES) == set(get_args(ImportMode))


@pytest.mark.parametrize(
    "mode",
    [
        "bogus",
        "",
        " ",
        "NEW_IDS",
        "Keep_Ids",
        "new_ids ",
        " keep_ids",
        "keep-ids",
        "new_ids,keep_ids",
    ],
)
def test_an_unknown_mode_is_refused_and_nothing_is_stored(
    file_repo: FileGraphRepository, mode: Any
) -> None:
    with pytest.raises(BundleError) as info:
        import_bundle(file_repo, _bundle(ID_A, ID_B), mode)
    assert info.value.message == UNKNOWN_MODE
    assert (info.value.status_code, info.value.code) == (422, "bundle_error")
    assert isinstance(info.value, SankeyError)
    assert file_repo.count() == 0


@pytest.mark.parametrize("mode", [None, 0, 1, True, b"new_ids", ["new_ids"], ("keep_ids",)])
def test_a_mode_that_is_not_a_string_is_refused_too(
    file_repo: FileGraphRepository, mode: Any
) -> None:
    with pytest.raises(BundleError) as info:
        import_bundle(file_repo, _bundle(ID_A), mode)
    assert info.value.message == UNKNOWN_MODE
    assert file_repo.count() == 0


def test_an_unknown_mode_is_refused_on_the_mongo_store_as_well(
    mongo_repo: MongoGraphRepository,
) -> None:
    bogus: Any = "bogus"
    with pytest.raises(BundleError, match=r"^Unknown import mode"):
        import_bundle(mongo_repo, _bundle(ID_A), bogus)
    assert mongo_repo.count() == 0


def test_the_mode_is_checked_before_the_bundle_and_before_the_repository_is_touched() -> None:
    untouched = FileGraphRepository.__new__(FileGraphRepository)  # any attribute access raises
    bogus: Any = "bogus"
    for payload in (_bundle(ID_A), "not a bundle", None, {}):
        with pytest.raises(BundleError) as info:
            import_bundle(untouched, payload, bogus)
        assert info.value.message == UNKNOWN_MODE


@pytest.mark.parametrize(("mode", "keeps_id"), [("new_ids", False), ("keep_ids", True)])
def test_both_known_modes_still_import(
    file_repo: FileGraphRepository, mode: ImportMode, keeps_id: bool
) -> None:
    report = import_bundle(file_repo, _bundle(ID_A), mode)
    assert (report.imported, report.failed, report.errors) == (1, 0, [])
    assert (ID_A in report.ids) is keeps_id
    assert file_repo.count() == 1


# --------------------------------------------------------------------------- the default mode


def test_the_mode_defaults_to_new_ids() -> None:
    assert inspect.signature(import_bundle).parameters["mode"].default == "new_ids"


@pytest.mark.parametrize("backend", ["file", "mongo"])
def test_without_a_mode_graphs_get_new_ids_and_can_be_imported_again(
    backend: str, file_repo: FileGraphRepository, mongo_repo: MongoGraphRepository
) -> None:
    repo = file_repo if backend == "file" else mongo_repo
    first = import_bundle(repo, _bundle(ID_A, ID_B))
    again = import_bundle(repo, _bundle(ID_A, ID_B))  # keep_ids would conflict here
    assert (first.imported, first.failed, first.errors) == (2, 0, [])
    assert (again.imported, again.failed, again.errors) == (2, 0, [])
    assert not {ID_A, ID_B} & {*first.ids, *again.ids}
    assert len({*first.ids, *again.ids}) == 4
    assert repo.count() == 4


def test_the_default_mode_still_refuses_a_bad_bundle(file_repo: FileGraphRepository) -> None:
    with pytest.raises(BundleError, match="not a sankey-studio graph bundle"):
        import_bundle(file_repo, "nope")
    assert file_repo.count() == 0


# --------------------------------------------------------------------------- BundleError home


def test_bundle_error_lives_in_errors_and_every_old_import_path_still_works() -> None:
    assert errors.BundleError is BundleError is bundle.BundleError is migrate.BundleError
    assert BundleError.__module__ == "sankey_studio.errors"
    assert (BundleError.status_code, BundleError.code) == (422, "bundle_error")
    assert issubclass(BundleError, SankeyError)
    assert "BundleError" in bundle.__all__
    assert "BundleError" in migrate.__all__
