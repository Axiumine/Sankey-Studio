"""``editor/source/overlays.js``: the graph-only edits a source change may drop.

``OVERLAYS`` is the one list of the edits that live in the graph, not in its data
(``transform.entry_categories``, ``transform.extra_links``, ``style.node_order``). The counting
and the removal are pure functions of the store, so they run under ``node`` against the real
store module.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Final, NamedTuple

import pytest

from sankey_studio.web.app import STATIC_DIR

JS: Final = STATIC_DIR / "js" / "editor"
NODE: Final = shutil.which("node")
DRIVER: Final = """
const overlays = await import(process.argv[1]);
const { createStore, initialState } = await import(process.argv[2]);
const cases = JSON.parse(process.argv[3]);
const out = cases.map((patches) => {
  const store = createStore(initialState());
  for (const [path, value] of patches) { store.patch(path, value); }
  const before = overlays.overlaySummary(store.get());
  store.patch("status.dirty", false, { clean: true });
  overlays.clearOverlays(store);
  const after = overlays.overlaySummary(store.get());
  return { before, after, dirty: store.get().status.dirty, draft: store.get().draft,
           paths: overlays.OVERLAYS.map((item) => item.path.join(".")) };
});
process.stdout.write(JSON.stringify(out));
"""
CATEGORIES: Final = [
    "draft.transform.entry_categories",
    [{"source": "a", "target": "b", "category": "x"}],
]
LINKS: Final = ["draft.transform.extra_links", [{"source": "a", "target": "c", "value": 1}]]
ORDER: Final = ["draft.style.node_order", ["a", "b"]]


class Case(NamedTuple):
    patches: list[list[Any]]
    total: int
    text: str


def many(entry: list[Any], times: int) -> list[Any]:
    return [entry[0], entry[1] * times]


CASES = [
    Case([], 0, ""),
    Case([CATEGORIES], 1, "1 category edit"),
    Case([many(CATEGORIES, 3)], 3, "3 category edits"),
    Case([LINKS], 1, "1 added entry"),
    Case([many(LINKS, 2)], 2, "2 added entries"),
    Case([ORDER], 2, "a custom node order"),
    Case(
        [many(CATEGORIES, 2), LINKS, ORDER],
        5,
        "2 category edits, 1 added entry, a custom node order",
    ),
    Case([["draft.transform.entry_categories", []]], 0, ""),
]


def run_node(cases: list[list[list[Any]]]) -> list[dict[str, Any]]:
    assert NODE is not None
    result = subprocess.run(  # noqa: S603 - fixed argv: node runs a constant script
        [
            NODE,
            "--input-type=module",
            "-e",
            DRIVER,
            (JS / "source" / "overlays.js").as_uri(),
            (JS / "store.js").as_uri(),
            json.dumps(cases),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (result.returncode, result.stderr) == (0, "")
    answer: list[dict[str, Any]] = json.loads(result.stdout)
    return answer


@pytest.fixture(scope="module")
def answers() -> list[dict[str, Any]]:
    return run_node([case.patches for case in CASES])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("index", range(len(CASES)))
def test_the_summary_counts_items_and_names_each_kind(
    answers: list[dict[str, Any]], index: int
) -> None:
    case = CASES[index]
    assert answers[index]["before"] == {"count": case.total, "text": case.text}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("index", range(len(CASES)))
def test_clearing_removes_every_overlay_and_only_them(
    answers: list[dict[str, Any]], index: int
) -> None:
    answer = answers[index]
    assert answer["after"] == {"count": 0, "text": ""}
    assert answer["draft"]["source"] == {
        "type": "text",
        "origin": "inline",
        "format": "auto",
        "content": "",
    }
    assert answer["dirty"] is (CASES[index].total > 0)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_list_names_the_three_graph_level_fields(answers: list[dict[str, Any]]) -> None:
    assert answers[0]["paths"] == [
        "draft.transform.entry_categories",
        "draft.transform.extra_links",
        "draft.style.node_order",
    ]
