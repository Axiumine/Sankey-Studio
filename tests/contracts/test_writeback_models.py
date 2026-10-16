# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``WriteBackPref``, ``write_back`` on sources, ``extra_links``, ``node_order``, ``folder_id``."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from sankey_studio.models import (
    GraphDefinition,
    GraphSummary,
    Link,
    ManualSource,
    MongoSource,
    StyleSpec,
    TextSource,
    TransformSpec,
    WriteBackPref,
)

KEY = "file:budget/2025.csv"
PREF: dict[str, Any] = {"mode": "source", "target": KEY}
NOW = "2026-01-02T03:04:05+00:00"
ID = "1" * 32
LINK = {"source": "a", "target": "b", "value": 1}
DEFINITION: dict[str, Any] = {
    "name": "n",
    "source": {"type": "manual"},
    "id": ID,
    "created_at": NOW,
    "updated_at": NOW,
}


def names(count: int) -> list[str]:
    return [f"n{i}" for i in range(count)]


@pytest.mark.parametrize("mode", ["source", "graph"])
def test_a_preference_names_a_mode_and_a_target(mode: str) -> None:
    pref = WriteBackPref.model_validate({**PREF, "mode": mode})
    assert (pref.mode, pref.target) == (mode, KEY)


@pytest.mark.parametrize("mode", ["", "ask", "SOURCE", None])
def test_a_preference_refuses_other_modes(mode: Any) -> None:
    with pytest.raises(ValidationError):
        WriteBackPref.model_validate({**PREF, "mode": mode})


@pytest.mark.parametrize(("length", "ok"), [(1, True), (399, True), (400, True), (401, False)])
def test_the_target_key_is_bounded(length: int, *, ok: bool) -> None:
    body = {**PREF, "target": "k" * length}
    if ok:
        assert len(WriteBackPref.model_validate(body).target) == length
    else:
        with pytest.raises(ValidationError):
            WriteBackPref.model_validate(body)


@pytest.mark.parametrize("target", ["", "   "])
def test_an_empty_target_key_is_refused(target: str) -> None:
    with pytest.raises(ValidationError):
        WriteBackPref.model_validate({**PREF, "target": target})


@pytest.mark.parametrize("missing", ["mode", "target"])
def test_a_preference_needs_both_fields_and_forbids_others(missing: str) -> None:
    with pytest.raises(ValidationError):
        WriteBackPref.model_validate({k: v for k, v in PREF.items() if k != missing})
    with pytest.raises(ValidationError):
        WriteBackPref.model_validate({**PREF, "extra": 1})


SOURCES: list[tuple[type, dict[str, Any]]] = [
    (TextSource, {"content": "a,b,1"}),
    (TextSource, {"origin": "file", "path": "a.csv"}),
    (MongoSource, {"connection": "c", "collection": "events"}),
]


@pytest.mark.parametrize(("model", "base"), SOURCES)
def test_text_and_mongo_sources_keep_a_preference(model: Any, base: dict[str, Any]) -> None:
    assert model.model_validate(base).write_back is None
    source = model.model_validate({**base, "write_back": PREF})
    assert source.write_back == WriteBackPref.model_validate(PREF)
    assert model.model_validate(source.model_dump()) == source
    with pytest.raises(ValidationError):
        model.model_validate({**base, "write_back": {"mode": "source"}})


def test_an_inline_text_source_stores_a_preference_it_will_ignore() -> None:
    source = TextSource.model_validate({"content": "x", "write_back": PREF})
    assert source.origin == "inline"
    assert source.write_back is not None


def test_a_manual_source_has_no_preference() -> None:
    assert "write_back" not in ManualSource.model_fields
    with pytest.raises(ValidationError):
        ManualSource.model_validate({"type": "manual", "write_back": PREF})


@pytest.mark.parametrize("count", [0, 1, 1_999, 2_000])
def test_extra_links_up_to_the_limit_are_accepted(count: int) -> None:
    links = [{**LINK, "value": i + 1} for i in range(count)]
    assert len(TransformSpec.model_validate({"extra_links": links}).extra_links) == count


def test_one_extra_link_over_the_limit_is_refused() -> None:
    with pytest.raises(ValidationError):
        TransformSpec.model_validate({"extra_links": [LINK] * 2_001})


def test_extra_links_default_empty_and_are_links() -> None:
    assert TransformSpec().extra_links == []
    spec = TransformSpec.model_validate({"extra_links": [{**LINK, "category": None}]})
    assert spec.extra_links == [Link.model_validate(LINK)]
    assert spec.extra_links[0].category is None
    assert TransformSpec.model_validate(spec.model_dump()) == spec


@pytest.mark.parametrize("bad", [{**LINK, "value": 0}, {**LINK, "source": ""}, {"source": "a"}])
def test_an_extra_link_is_validated_like_a_link(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TransformSpec.model_validate({"extra_links": [bad]})


@pytest.mark.parametrize("count", [0, 1, 4_999, 5_000])
def test_node_order_up_to_the_limit_is_accepted(count: int) -> None:
    assert len(StyleSpec.model_validate({"node_order": names(count)}).node_order) == count


def test_one_node_over_the_limit_is_refused() -> None:
    with pytest.raises(ValidationError):
        StyleSpec.model_validate({"node_order": names(5_001)})


def test_node_order_refuses_a_repeated_name_with_a_fixed_message() -> None:
    with pytest.raises(ValidationError) as caught:
        StyleSpec.model_validate({"node_order": ["a", "b", "a"]})
    [error] = caught.value.errors(include_input=False, include_context=False, include_url=False)
    assert error["msg"] == "Value error, node_order must not repeat a node name"
    assert StyleSpec.model_validate({"node_order": ["a", "A"]}).node_order == ["a", "A"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 201, "a\0b"])
def test_node_order_names_are_node_names(name: str) -> None:
    with pytest.raises(ValidationError):
        StyleSpec.model_validate({"node_order": [name]})


def test_node_order_defaults_empty_and_keeps_its_order() -> None:
    assert StyleSpec().node_order == []
    style = StyleSpec.model_validate({"node_order": ["z", "a", "m"]})
    assert style.node_order == ["z", "a", "m"]
    assert StyleSpec.model_validate(style.model_dump()) == style


def test_assigning_a_repeating_order_is_refused_and_keeps_the_old_one() -> None:
    style = StyleSpec(node_order=["a"])
    with pytest.raises(ValidationError):
        style.node_order = ["b", "b"]
    assert style.node_order == ["a"]


def test_folder_id_defaults_to_the_top_level() -> None:
    assert GraphDefinition.model_validate(DEFINITION).folder_id is None
    summary = {
        "id": ID,
        "name": "n",
        "description": "",
        "tags": [],
        "source_type": "manual",
        "revision": 1,
        "updated_at": NOW,
    }
    assert GraphSummary.model_validate(summary).folder_id is None


@pytest.mark.parametrize("folder", [ID, "a" * 32])
def test_a_folder_id_of_the_right_shape_is_kept(folder: str) -> None:
    assert GraphDefinition.model_validate({**DEFINITION, "folder_id": folder}).folder_id == folder


@pytest.mark.parametrize("folder", ["", "0" * 31, "0" * 33, "G" * 32, "A" * 32, "root"])
def test_a_folder_id_of_another_shape_is_refused(folder: str) -> None:
    with pytest.raises(ValidationError):
        GraphDefinition.model_validate({**DEFINITION, "folder_id": folder})
    with pytest.raises(ValidationError):
        GraphSummary.model_validate(
            {
                "id": ID,
                "name": "n",
                "description": "",
                "tags": [],
                "source_type": "manual",
                "revision": 1,
                "updated_at": NOW,
                "folder_id": folder,
            }
        )
