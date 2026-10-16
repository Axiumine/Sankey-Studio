# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""F2 (click a node to add a flow), run with node on the shipped files (no browser).

Covered: which end of the new flow the clicked node becomes (``prefillFor``), when the dialog is not
opened (no engine, no row, a source that names nothing to edit: a toast instead), the default click
of ``node-actions.js`` and the dialog title (``titleFor``). The dialog itself is checked in a real
browser by ``tests/e2e/ui/test_chart_node_click_ui.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from sankey_studio.web.app import STATIC_DIR

JS: Final = STATIC_DIR / "js"
NODE: Final = shutil.which("node")
DRIVER: Final = Path(__file__).parent / "static_node_flow.mjs"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    assert NODE is not None
    done = subprocess.run(  # noqa: S603 - fixed argv: node on the repo's own driver and files
        [NODE, str(DRIVER), str(JS)], capture_output=True, text=True, check=False, timeout=60
    )
    assert (done.returncode, done.stderr) == (0, "")
    data: dict[str, Any] = json.loads(done.stdout)
    return data


def test_a_sink_gets_a_flow_that_ends_at_it_and_every_other_node_one_that_starts_there(
    result: dict[str, Any],
) -> None:
    prefill = result["prefill"]
    assert prefill["sink"] == {"target": "Rent", "node": "Rent", "direction": "to"}
    assert prefill["source"] == {"source": "Salary", "node": "Salary", "direction": "from"}
    assert prefill["middle"] == {"source": "Budget", "node": "Budget", "direction": "from"}


def test_only_an_exact_zero_outflow_makes_a_sink(result: dict[str, Any]) -> None:
    prefill = result["prefill"]
    assert prefill["noNumbers"]["direction"] == "from"
    assert prefill["nullOut"]["direction"] == "from"


def test_a_hostile_node_name_is_passed_on_untouched(result: dict[str, Any]) -> None:
    hostile = result["prefill"]["hostile"]
    assert hostile["target"] == hostile["node"] == "<img src=x onerror=alert(1)>"


def test_nothing_opens_without_an_engine_or_a_named_node(result: dict[str, Any]) -> None:
    assert result["nothing"] == {
        "noEdits": None,
        "noStore": None,
        "noNode": None,
        "noName": None,
        "none": None,
    }


def test_a_source_that_names_nothing_to_edit_gets_a_toast_instead_of_the_dialog(
    result: dict[str, Any],
) -> None:
    assert result["blocked"] == {
        "file": None,
        "mongo": None,
        "toasts": ["Choose a file first.", "Choose a collection first."],
    }


def test_the_default_click_of_the_chart_needs_an_engine_and_a_row(result: dict[str, Any]) -> None:
    assert result["click"] == ["Choose a file first."]


def test_the_title_names_the_node_and_follows_the_direction(result: dict[str, Any]) -> None:
    titles = result["titles"]
    assert titles["plain"] == titles["none"] == "Add a flow"
    assert titles["from"] == "Add a flow from Budget"
    assert titles["to"] == "Add a flow into Rent"
    assert titles["unknown"] == "Add a flow from Rent"
    assert titles["bidi"] == "Add a flow into ab"


def test_a_long_node_name_is_cut_in_the_title_at_sixty_characters(result: dict[str, Any]) -> None:
    titles = result["titles"]
    assert titles["exact"] == len("Add a flow from ") + 60
    assert titles["long"] == f"Add a flow from {'n' * 60}..."
