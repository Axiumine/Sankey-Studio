# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``editor/source/columns.js roleIndexes`` mirrors ``sources/formats/csv_rows.py`` (F3).

The table is the JS twin of ``CATEGORIES`` in ``tests/sources/test_text_csv_columns.py``: without
a header the category is the fourth column unless detection is off, a category column is given
or an explicit pick already reads column 4. The function is pure, so it runs under ``node``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest

from sankey_studio.models import TextSource
from sankey_studio.sources.formats.csv_rows import resolve_columns
from sankey_studio.sources.rewrite.parsing import make_job
from sankey_studio.web.app import STATIC_DIR

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext

MODULE: Final = STATIC_DIR / "js" / "editor" / "source" / "columns.js"
NODE: Final = shutil.which("node")
DRIVER: Final = """
const { roleIndexes } = await import(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(cases.map(([spec, cells]) => roleIndexes(spec, cells))));
"""
NO_HEADER: Final = {"has_header": False}


class Case(NamedTuple):
    spec: dict[str, Any]
    cells: list[str]
    expected: dict[str, int]


def idx(source: int, target: int, value: int, category: int) -> dict[str, int]:
    return {"source": source, "target": target, "value": value, "category": category}


HEADED = ["source", "target", "value", "category"]
CASES = [
    # headerless: the fourth column is the category
    Case(NO_HEADER, list("abcd"), idx(0, 1, 2, 3)),
    Case(NO_HEADER, list("abc"), idx(0, 1, 2, 3)),  # fewer cells: the label judges that
    Case(NO_HEADER, list("abcde"), idx(0, 1, 2, 3)),
    Case({**NO_HEADER, "detect_category": False}, list("abcd"), idx(0, 1, 2, -1)),
    Case({**NO_HEADER, "category_column": 2}, list("abcd"), idx(0, 1, 2, 2)),
    # explicit picks that already read column 4 keep it
    Case({**NO_HEADER, "source_column": 3, "value_column": 0}, list("abcd"), idx(3, 1, 0, -1)),
    Case({**NO_HEADER, "target_column": 3, "value_column": 1}, list("abcd"), idx(0, 3, 1, -1)),
    Case({**NO_HEADER, "value_column": 3}, list("abcd"), idx(0, 1, 3, -1)),
    # headed text is unchanged
    Case({}, HEADED, idx(0, 1, 2, 3)),
    Case({}, ["source", "target", "value"], idx(0, 1, 2, -1)),
    Case({"detect_category": False}, HEADED, idx(0, 1, 2, -1)),
    Case({"category_column": "value"}, HEADED, idx(0, 1, 2, 2)),
    Case({}, ["Category", "Value", "Target", "Source"], idx(3, 2, 1, 0)),
]


def computed(cases: list[Case]) -> list[dict[str, int]]:
    done = subprocess.run(  # noqa: S603 - fixed argv: node runs a constant script
        [
            str(NODE),
            "--input-type=module",
            "-e",
            DRIVER,
            MODULE.as_uri(),
            json.dumps([[c.spec, c.cells] for c in cases]),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (done.returncode, done.stderr) == (0, "")
    answer: list[dict[str, int]] = json.loads(done.stdout)
    return answer


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_role_indexes_follow_the_server_rules() -> None:
    assert computed(CASES) == [case.expected for case in CASES]


@pytest.mark.parametrize("case", CASES, ids=[str(i) for i in range(len(CASES))])
def test_the_expected_indexes_are_what_the_server_resolves(
    source_ctx: SourceContext, case: Case
) -> None:
    spec = TextSource.model_validate({"content": "x", **case.spec})
    job = make_job(spec, "x", source_ctx)
    columns = resolve_columns(job, case.cells if spec.has_header else None)
    got = {
        "source": columns.source,
        "target": columns.target,
        "value": columns.value,
        "category": -1 if columns.category is None else columns.category,
    }
    assert got == case.expected
