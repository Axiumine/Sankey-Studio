"""The ``sankey_studio.web.schemas`` package keeps its public import path."""

from __future__ import annotations

import pytest

from sankey_studio.web import schemas
from sankey_studio.web.schemas import folders, forms, queries, settings

NAMED_IN_THE_SPEC = [
    "ThemeQuery",
    "RenderQuery",
    "CompareQuery",
    "IdsQuery",
    "ListQuery",
    "CreateQuery",
    "ScopeQuery",
    "FolderList",
    "MoveGraphsIn",
    "EntriesQuery",
    "ExportQuery",
    "CollectionsQuery",
    "SampleQuery",
    "UploadForm",
    "SettingsIn",
    "SettingsOut",
    "MongoConnectionIn",
    "merge_settings",
]


@pytest.mark.parametrize("name", NAMED_IN_THE_SPEC)
def test_the_names_of_the_spec_are_exported(name: str) -> None:
    assert name in schemas.__all__
    assert hasattr(schemas, name)


def test_every_exported_name_exists_once_and_is_the_object_of_its_module() -> None:
    assert len(schemas.__all__) == len(set(schemas.__all__))
    for name in schemas.__all__:
        exported = getattr(schemas, name)
        homes = [
            m for m in (queries, forms, folders, settings) if getattr(m, name, None) is exported
        ]
        assert homes, name


def test_the_package_exports_exactly_what_its_modules_export() -> None:
    from_modules = {
        name for module in (queries, forms, folders, settings) for name in module.__all__
    }
    assert set(schemas.__all__) == from_modules
