"""``library/folder-rules.js``: why a place cannot take a graph or a collection.

The Move dialog and the drag and drop both ask this pure module, so the sentences and the order of
the checks are pinned here, with both sides of every limit. It runs under ``node`` against the real
module, like ``test_static_folders_data.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Final, NamedTuple

import pytest

from sankey_studio.web.app import STATIC_DIR

LIBRARY: Final = STATIC_DIR / "js" / "library"
NODE: Final = shutil.which("node")
DRIVER: Final = """
const data = await import(process.argv[1]);
const rules = await import(process.argv[2]);
const [folders, asks, parents] = JSON.parse(process.argv[3]);
const index = data.buildIndex(folders);
const answers = asks.map(({ current, moving, target, depth }) => {
  const options = { index, moving: moving === null ? null : index.get(moving) };
  if (current !== "unset") {
    options.current = current;
  }
  return rules.createRules(options)(target, depth ?? undefined);
});
process.stdout.write(JSON.stringify({
  answers,
  parents: parents.map((id) => rules.parentOf(index, id)),
  texts: [rules.REASON_INSIDE, rules.REASON_HERE, rules.REASON_DEEP],
}));
"""
INSIDE: Final = "inside the collection being moved"
HERE: Final = "already here"
DEEP: Final = "too deep (at most 8 levels)"


def folder(folder_id: str, parent: str | None = None) -> dict[str, Any]:
    return {"id": folder_id, "name": f"name {folder_id}", "parent_id": parent}


TREE: Final = [folder("a"), folder("b", "a"), folder("c", "b"), folder("d"), folder("e", "a")]
CHAIN: Final = [folder(f"l{n}", f"l{n - 1}" if n > 1 else None) for n in range(1, 9)]
TALL: Final = [folder("m"), folder("m2", "m"), folder("s")]  # "m" is two levels tall, "s" one


class Ask(NamedTuple):
    label: str
    current: str | None
    moving: str | None
    target: str | None
    expected: str | None
    depth: int | None = None


UNSET: Final = "unset"  # `current` left out: several graphs from unknown places
GRAPHS = [
    Ask("graph: the open collection is already here", "a", None, "a", HERE),
    Ask("graph: a child of the open collection is fine", "a", None, "b", None),
    Ask("graph: the library from inside a collection is fine", "a", None, None, None),
    Ask("graph: the library from the top level is already here", None, None, None, HERE),
    Ask("graph: a collection from the top level is fine", None, None, "a", None),
    Ask("graphs of unknown places: nothing is already here", UNSET, None, "a", None),
    Ask("graphs of unknown places: the library is a place too", UNSET, None, None, None),
    Ask("graphs have no depth rule", "d", None, "c", None, depth=99),
]
FOLDERS = [
    Ask("folder: onto itself", "a", "b", "b", INSIDE),
    Ask("folder: onto a descendant", "a", "b", "c", INSIDE),
    Ask("folder: onto its parent", "a", "b", "a", HERE),
    Ask("folder: to the library", "a", "b", None, None),
    Ask("folder: to a sibling branch", "a", "b", "d", None),
    Ask("folder: to another child of its parent", "a", "b", "e", None),
    Ask("folder at the top: the library is already here", None, "a", None, HERE),
    Ask("folder at the top: onto its own child", None, "a", "b", INSIDE),
    Ask("folder at the top: the check for itself wins over the place", None, "a", "a", INSIDE),
    Ask("an explicit depth beats the index", "a", "b", "d", DEEP, depth=8),
]
LIMITS = [
    Ask("two levels tall fits below level 6", None, "m", "l6", None),
    Ask("two levels tall does not fit below level 7", None, "m", "l7", DEEP),
    Ask("two levels tall does not fit below level 8", None, "m", "l8", DEEP),
    Ask("one level tall fits below level 7", None, "s", "l7", None),
    Ask("one level tall does not fit below level 8", None, "s", "l8", DEEP),
    Ask("the library is never too deep", "l1", "m", None, None),
]


def run_node(folders: list[dict[str, Any]], asks: list[Ask], parents: list[str]) -> dict[str, Any]:
    if NODE is None:
        pytest.fail("node is needed for the static tests")
    payload = [
        folders,
        [
            {"current": a.current, "moving": a.moving, "target": a.target, "depth": a.depth}
            for a in asks
        ],
        parents,
    ]
    result = subprocess.run(  # noqa: S603 - fixed argv: node runs a constant script
        [
            NODE,
            "--input-type=module",
            "-e",
            DRIVER,
            (LIBRARY / "folders-data.js").as_uri(),
            (LIBRARY / "folder-rules.js").as_uri(),
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    answer: dict[str, Any] = json.loads(result.stdout)
    return answer


def check(folders: list[dict[str, Any]], asks: list[Ask]) -> None:
    answers = run_node(folders, asks, [])["answers"]
    for ask, got in zip(asks, answers, strict=True):
        assert got == ask.expected, ask.label


def test_the_sentences_are_the_ones_the_move_dialog_shows() -> None:
    assert run_node([], [], [])["texts"] == [INSIDE, HERE, DEEP]


def test_graphs_are_only_refused_the_place_they_are_in() -> None:
    check(TREE, GRAPHS)


def test_a_collection_is_refused_itself_its_descendants_and_its_own_parent() -> None:
    check(TREE, FOLDERS)


def test_the_depth_limit_counts_the_height_of_the_collection_being_moved() -> None:
    check([*CHAIN, *TALL], LIMITS)


def test_parent_of_reads_the_place_a_collection_is_drawn_under() -> None:
    ids = ["a", "b", "c", "e", "unknown"]
    assert run_node(TREE, [], ids)["parents"] == [None, "a", "b", "a", None]
