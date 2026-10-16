# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Which connection the Mongo tab pre-selects after "Check again": ``editor/source/model.js``.

``connectionToPreselect`` is a pure function, so it runs under ``node`` on the shipped file
(skipped when node is not installed). The rule: only a Mongo draft, only when exactly one
connection is configured, and only when the draft has no connection or one that is gone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Final

import pytest

from sankey_studio.web.app import STATIC_DIR

MODULE: Final = STATIC_DIR / "js" / "editor" / "source" / "model.js"
DRIVER: Final = """
const { connectionToPreselect } = await import(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(cases.map(([s, c]) => connectionToPreselect(s, c))));
"""
LATE: Final = [{"name": "late"}]
TWO: Final = [{"name": "a"}, {"name": "b"}]
BLANK: Final = {"type": "mongo", "connection": "", "collection": ""}


def preselected(cases: list[tuple[Any, list[dict[str, str]]]]) -> list[str | None]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run(  # noqa: S603 - fixed argv: node runs a constant script
        [node, "--input-type=module", "-e", DRIVER, MODULE.as_uri(), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (done.returncode, done.stderr) == (0, "")
    answer: list[str | None] = json.loads(done.stdout)
    return answer


def test_the_only_connection_is_chosen_for_a_draft_without_one() -> None:
    gone = {**BLANK, "connection": "removed"}
    assert preselected([(BLANK, LATE), ({"type": "mongo"}, LATE), (gone, LATE)]) == ["late"] * 3


def test_a_draft_with_a_configured_connection_is_never_changed() -> None:
    mine = {**BLANK, "connection": "late"}
    assert preselected([(mine, LATE), ({**BLANK, "connection": "a"}, TWO)]) == [None, None]


def test_several_or_no_connections_leave_the_choice_to_the_person() -> None:
    assert preselected([(BLANK, TWO), (BLANK, [])]) == [None, None]


def test_a_source_that_is_not_mongo_is_left_alone() -> None:
    manual = {"type": "manual", "links": []}
    assert preselected([(manual, LATE), (None, LATE)]) == [None, None]
