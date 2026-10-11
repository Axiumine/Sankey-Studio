"""The exact arguments the storage code hands to pydantic and to its own helpers.

Each stand-in answers differently for a wrong argument, so a changed literal (``mode="json"``, a
dropped ``include_input=False``) shows up in the result instead of passing unnoticed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from pydantic import SecretStr

from sankey_studio.models import SCHEMA_VERSION
from sankey_studio.storage.common import validation_lines
from sankey_studio.storage.mongo_store import _changes, _encode
from sankey_studio.storage.settings_store import dump_settings
from tests.storage.support import ID_A, NOW, create_data

if TYPE_CHECKING:
    from pydantic import ValidationError

    from sankey_studio.models import AppSettings, GraphDefinition, GraphUpdate
    from sankey_studio.storage import MongoGraphRepository


class _Errors:
    """A ``ValidationError`` stand-in that records how ``errors`` was called."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def errors(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.kwargs = kwargs
        return [{"loc": ("a", 0), "msg": "first"}, {"loc": (), "msg": "second"}]


def _dump(mode: str) -> dict[str, Any]:
    """What ``model_dump`` returns; ``mode`` is echoed so a wrong mode is visible."""
    return {"mode": mode}


def test_validation_lines_never_ask_for_input_context_or_url() -> None:
    errors = _Errors()
    lines = validation_lines(cast("ValidationError", errors), "root")
    assert errors.kwargs == {
        "include_input": False,
        "include_context": False,
        "include_url": False,
    }
    assert lines == ["a.0: first", "root: second"]


def test_a_stored_graph_is_dumped_in_json_mode() -> None:
    graph = SimpleNamespace(
        id=ID_A,
        created_at=NOW,
        updated_at=NOW,
        model_dump=lambda *, mode: {"id": "dropped", **_dump(mode)},
    )
    doc = _encode(cast("GraphDefinition", graph))
    assert doc == {"mode": "json", "_id": ID_A, "created_at": NOW, "updated_at": NOW}


def test_an_update_is_dumped_in_json_mode() -> None:
    data = SimpleNamespace(revision=4, model_dump=lambda *, mode: _dump(mode))
    changes = _changes(cast("GraphUpdate", data), NOW)
    assert changes == {
        "mode": "json",
        "schema_version": SCHEMA_VERSION,
        "revision": 5,
        "updated_at": NOW,
    }


def test_settings_are_dumped_in_json_mode_with_the_real_uris() -> None:
    connection = SimpleNamespace(uri=SecretStr("mongodb://real.invalid/"))
    settings = SimpleNamespace(
        mongo_connections=[connection],
        model_dump=lambda *, mode: {**_dump(mode), "mongo_connections": [{"uri": "**********"}]},
    )
    doc = dump_settings(cast("AppSettings", settings))
    assert doc == {"mode": "json", "mongo_connections": [{"uri": "mongodb://real.invalid/"}]}


def test_a_new_mongo_repository_creates_its_indexes_on_the_first_write(
    mongo_repo: MongoGraphRepository,
) -> None:
    assert mongo_repo._indexed is False
    mongo_repo.create(create_data())
    assert mongo_repo._indexed is True
