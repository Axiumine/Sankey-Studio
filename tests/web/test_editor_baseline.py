# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The editor's "is it still the saved graph?" form: ``static/js/editor/meta/baseline.js``.

The module is plain JavaScript, so these tests run it under ``node`` (skipped when node is not
installed). They pin two things: the table of server defaults the module drops equals the defaults
of the pydantic models (a changed default fails here, not in somebody's browser), and the form
treats a cleared field, a ``null`` and a default as the same graph while a null that means
something (a count-only Mongo source, a cleared entry category) stays.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.models import MongoSource, StyleSpec, TextSource, TransformSpec
from sankey_studio.models.style import DonutStyle
from sankey_studio.web.app import STATIC_DIR

if TYPE_CHECKING:
    from pydantic import BaseModel

MODULE: Final = STATIC_DIR / "js" / "editor" / "meta" / "baseline.js"
DRIVER: Final = """
const { DEFAULTS, tidyDraft, savedForm } = await import(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const out = input.drafts.map((draft) => tidyDraft(structuredClone(draft)));
const saved = savedForm({ draft: input.drafts[0], meta: input.meta });
process.stdout.write(JSON.stringify({ defaults: DEFAULTS, out, saved }));
"""
TEXT: Final = {"type": "text", "origin": "inline", "content": "a,b,1"}
SERVER_TEXT: Final = {
    **TEXT,
    "path": None,
    "format": "auto",
    "delimiter": None,
    "has_header": True,
    "source_column": None,
    "category_column": None,
    "detect_category": True,
    "encoding": "utf-8",
}
FORM: Final = {
    "type": "text",
    "content": "a,b,1",
}  # what TEXT comes to: the default origin is dropped
META: Final = {"name": "", "description": "", "tags": []}


def run_node(drafts: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    payload = json.dumps({"drafts": drafts, "meta": meta or META})
    result = subprocess.run(  # noqa: S603 - fixed argv: node runs a constant script
        [node, "--input-type=module", "-e", DRIVER, MODULE.as_uri(), payload],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (result.returncode, result.stderr) == (0, "")
    answer: dict[str, Any] = json.loads(result.stdout)
    return answer


def model_default(model: type[BaseModel], key: str) -> object:
    return model.model_fields[key].default


def test_the_default_table_equals_the_model_defaults() -> None:
    defaults = run_node([{}])["defaults"]
    models: dict[str, tuple[type[BaseModel], ...]] = {
        "source": (TextSource, MongoSource),
        "transform": (TransformSpec,),
        "style": (StyleSpec,),
        "style.donut": (DonutStyle,),
    }
    assert set(defaults) == set(models)
    for section, table in defaults.items():
        for key, value in table.items():
            owners = [m for m in models[section] if key in m.model_fields]
            assert owners, (section, key)
            assert all(model_default(m, key) == value for m in owners), (section, key)


def test_a_server_answer_and_a_cleared_draft_have_the_same_form() -> None:
    server = {
        "source": SERVER_TEXT,
        "transform": {"top_links": None, "hide_nodes": [], "merge_nodes": {}, "on_cycle": "error"},
        "style": {"title": None, "height": 560, "donut": {"hole": 0.58}},
    }
    cleared = {"source": TEXT, "transform": {}, "style": {}}
    assert run_node([server, cleared])["out"] == [{"source": FORM}, {"source": FORM}]


def test_a_value_that_is_not_the_default_stays() -> None:
    edited = {
        "source": {**TEXT, "delimiter": ";", "has_header": False},
        "transform": {"top_links": 7},
        "style": {"height": 700, "title": "T"},
    }
    kept = {**edited, "source": {**FORM, "delimiter": ";", "has_header": False}}
    assert run_node([edited])["out"] == [kept]


def test_a_null_that_means_something_stays() -> None:
    counting = {
        "source": {
            "type": "mongo",
            "connection": "c",
            "collection": "x",
            "value_field": None,
            "database": None,
        }
    }
    named = {
        "source": {"type": "mongo", "connection": "c", "collection": "x", "value_field": "value"}
    }
    cleared = {
        "source": TEXT,
        "transform": {"entry_categories": [{"source": "a", "target": "b", "category": None}]},
    }
    out = run_node([counting, named, cleared])["out"]
    assert out[0] == {
        "source": {"type": "mongo", "connection": "c", "collection": "x", "value_field": None}
    }
    assert out[1] == {"source": {"type": "mongo", "connection": "c", "collection": "x"}}
    assert out[2]["transform"] == {
        "entry_categories": [{"source": "a", "target": "b", "category": None}]
    }


def test_a_manual_row_without_a_category_has_no_category_key() -> None:
    server = {
        "source": {
            "type": "manual",
            "links": [{"source": "A", "target": "B", "value": 5, "category": None}],
        }
    }
    typed = {
        "source": {
            "type": "manual",
            "links": [{"source": "A", "target": "B", "value": 5, "category": ""}],
        }
    }
    plain = {"source": {"type": "manual", "links": [{"source": "A", "target": "B", "value": 5}]}}
    assert run_node([server, typed, plain])["out"] == [plain, plain, plain]


def test_the_saved_form_pairs_the_draft_with_the_name_description_and_tags() -> None:
    meta = {"name": "Budget", "description": "", "tags": []}
    answer = run_node([{"source": TEXT}], meta)
    assert answer["saved"] == {"draft": {"source": FORM}, "meta": {"name": "Budget"}}


def test_a_node_name_that_looks_like_a_prototype_key_survives() -> None:
    draft = {"source": TEXT, "transform": {"merge_nodes": json.loads('{"__proto__": "x"}')}}
    assert run_node([draft])["out"][0]["transform"] == {"merge_nodes": {"__proto__": "x"}}


def test_a_server_answer_with_the_new_default_fields_has_the_same_form() -> None:
    server = {
        "source": {**SERVER_TEXT, "write_back": None},
        "transform": {"extra_links": []},
        "style": {"node_order": []},
    }
    assert run_node([server, {"source": TEXT}])["out"] == [{"source": FORM}, {"source": FORM}]


def test_a_stored_write_back_preference_stays_on_both_sides() -> None:
    pref = {"mode": "source", "target": "file:budget/2025.csv"}
    loaded = {"source": {**SERVER_TEXT, "write_back": pref}}
    typed = {"source": {**TEXT, "write_back": pref}}
    kept = {"source": {**FORM, "write_back": pref}}
    assert run_node([loaded, typed])["out"] == [kept, kept]


def test_extra_links_with_a_null_category_match_the_ones_without() -> None:
    link = {"source": "A", "target": "B", "value": 5}
    server = {"source": TEXT, "transform": {"extra_links": [{**link, "category": None}]}}
    typed = {"source": TEXT, "transform": {"extra_links": [{**link, "category": ""}]}}
    plain = {"source": TEXT, "transform": {"extra_links": [link]}}
    out = run_node([server, typed, plain])["out"]
    assert out == [{"source": FORM, "transform": {"extra_links": [link]}}] * 3


def test_a_stored_node_order_stays() -> None:
    draft = {"source": TEXT, "style": {"node_order": ["b", "a"]}}
    assert run_node([draft])["out"][0]["style"] == {"node_order": ["b", "a"]}
