# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``library/folders-data.js buildIndex``: the lookups over the list of collections.

The index is pure, so it runs under ``node`` against the real module. It must answer for ANY list
the server may hold: a parent that is not in the list reads as the top level, and a cycle (two
racing moves can leave A below B and B below A behind) is cut so that every folder is reachable
and no walk loops.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Final, NamedTuple

import pytest

from sankey_studio.web.app import STATIC_DIR

MODULE: Final = STATIC_DIR / "js" / "library" / "folders-data.js"
NODE: Final = shutil.which("node")
DRIVER: Final = """
const { buildIndex } = await import(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
const ids = (list) => list.map((item) => item.id);
const out = cases.map((items) => {
  const index = buildIndex(items);
  const keys = [null, ...items.map((item) => item.id), "unknown"];
  const by = (fn) => Object.fromEntries(keys.map((key) => [String(key), fn(key)]));
  return {
    children: by((key) => ids(index.childrenOf(key))),
    path: by((key) => ids(index.pathOf(key))),
    depth: by((key) => index.depthOf(key)),
    height: by((key) => index.heightOf(key)),
    below: by((key) => (key === null ? [] : ids(index.descendantsOf(key)))),
    has: by((key) => index.has(key)),
    name: by((key) => index.get(key)?.name ?? null),
  };
});
process.stdout.write(JSON.stringify(out));
"""


def folder(folder_id: str, parent: str | None = None) -> dict[str, Any]:
    return {"id": folder_id, "name": f"name {folder_id}", "parent_id": parent}


class Case(NamedTuple):
    label: str
    items: list[dict[str, Any]]
    children: dict[str, list[str]]  # the key `"null"` is the top level
    path: dict[str, list[str]]
    depth: dict[str, int]
    height: dict[str, int]


CASES = [
    Case(
        "empty list",
        [],
        {"null": [], "unknown": []},
        {"unknown": []},
        {"null": 0, "unknown": 0},
        {},
    ),
    Case(
        "a tree keeps the list order",
        [folder("a"), folder("d"), folder("b", "a"), folder("c", "b"), folder("e", "a")],
        {"null": ["a", "d"], "a": ["b", "e"], "b": ["c"], "c": [], "unknown": []},
        {"c": ["a", "b", "c"], "d": ["d"], "e": ["a", "e"], "null": [], "unknown": []},
        {"null": 0, "a": 1, "c": 3, "d": 1, "e": 2, "unknown": 0},
        {"a": 3, "b": 2, "c": 1, "d": 1, "e": 1},
    ),
    Case(
        "a parent that is not in the list reads as the top level",
        [folder("x", "gone"), folder("y", "x")],
        {"null": ["x"], "x": ["y"], "y": []},
        {"x": ["x"], "y": ["x", "y"]},
        {"x": 1, "y": 2},
        {"x": 2, "y": 1},
    ),
    Case(
        "a folder below itself is a top-level one",
        [folder("s", "s")],
        {"null": ["s"], "s": []},
        {"s": ["s"]},
        {"s": 1},
        {"s": 1},
    ),
    Case(
        "a cycle is cut where the first walk comes back on itself",
        [folder("a", "b"), folder("b", "a")],
        {"null": ["a"], "a": ["b"], "b": []},
        {"a": ["a"], "b": ["a", "b"]},
        {"a": 1, "b": 2},
        {"a": 2, "b": 1},
    ),
    Case(
        "a tail that leads into a cycle stays below it and the cycle is cut once",
        [folder("t", "a"), folder("a", "b"), folder("b", "c"), folder("c", "a")],
        {"null": ["a"], "a": ["t", "c"], "b": [], "c": ["b"], "t": []},
        {"t": ["a", "t"], "b": ["a", "c", "b"], "c": ["a", "c"]},
        {"t": 2, "a": 1, "b": 3, "c": 2},
        {"a": 3, "t": 1, "c": 2, "b": 1},
    ),
]


def run_node(cases: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    assert NODE is not None
    result = subprocess.run(  # noqa: S603 - fixed argv: node runs a constant script
        [NODE, "--input-type=module", "-e", DRIVER, MODULE.as_uri(), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    answers: list[dict[str, Any]] = json.loads(result.stdout)
    return answers


@pytest.fixture(scope="module")
def answers() -> list[dict[str, Any]]:
    if NODE is None:
        pytest.fail("node is needed for the static tests")
    return run_node([case.items for case in CASES])


@pytest.mark.parametrize("position", range(len(CASES)), ids=[case.label for case in CASES])
def test_the_lookups_answer_for_every_shape_of_list(
    answers: list[dict[str, Any]], position: int
) -> None:
    case, answer = CASES[position], answers[position]
    for key, expected in case.children.items():
        assert answer["children"][key] == expected, f"children of {key}"
    for key, expected in case.path.items():
        assert answer["path"][key] == expected, f"path of {key}"
    for key, level in case.depth.items():
        assert answer["depth"][key] == level, f"depth of {key}"
    for key, levels in case.height.items():
        assert answer["height"][key] == levels, f"height of {key}"


def test_descendants_exclude_the_folder_itself_and_follow_the_tree(
    answers: list[dict[str, Any]],
) -> None:
    tree = answers[1]["below"]
    assert tree["a"] == ["b", "c", "e"]
    assert tree["b"] == ["c"]
    assert tree["c"] == []
    assert tree["unknown"] == []
    assert answers[4]["below"] == {"a": ["b"], "b": [], "null": [], "unknown": []}


def test_has_and_get_know_only_the_listed_folders(answers: list[dict[str, Any]]) -> None:
    tree = answers[1]
    assert [tree["has"][key] for key in ("a", "e", "unknown", "null")] == [True, True, False, False]
    assert tree["name"]["a"] == "name a"
    assert tree["name"]["unknown"] is None


def test_a_thousand_folders_in_a_line_are_walked_without_a_stack_overflow() -> None:
    items = [folder("f0")] + [folder(f"f{n}", f"f{n - 1}") for n in range(1, 1000)]
    answer = run_node([items])[0]
    assert answer["depth"]["f999"] == 1000
    assert answer["height"]["f0"] == 1000
    assert len(answer["below"]["f0"]) == 999


# ------------------------------------------------------------------------------ address and scope

LIBRARY: Final = STATIC_DIR / "js" / "library"
SCOPE_DRIVER: Final = """
const state = await import(process.argv[1]);
const data = await import(process.argv[2]);
const names = await import(process.argv[3]);
const [queries, states, labels] = JSON.parse(process.argv[4]);
const picked = state.createSelection();
picked.toggle("one", "First");
picked.toggle("two", "Second");
picked.toggle("one");
process.stdout.write(JSON.stringify({
  read: queries.map((search) => state.readQuery(search)),
  write: states.map((item) => state.queryString(item)),
  scoped: states.map((item) => state.isScoped(item)),
  scope: states.map((item) => data.scopeQuery(item)),
  label: labels.map((name) => names.folderLabel(name)),
  ids: ["a".repeat(32), "A".repeat(32), "a".repeat(31), "g".repeat(32), null].map(state.isFolderId),
  picked: picked.items(),
}));
"""
ID: Final = "0123456789abcdef" * 2
RLO: Final = chr(0x202E)
BELL: Final = chr(7)
ZWSP: Final = chr(0x200B)  # a zero-width space: invisible
PAGE: Final = {"folder": "", "q": "", "tag": "", "sort": "updated-desc", "page": 1}
STATES: Final = [
    PAGE,
    {**PAGE, "folder": ID},
    {**PAGE, "folder": ID, "q": "rent", "tag": "demo", "sort": "name-asc", "page": 3},
    {**PAGE, "tag": "demo"},
    {**PAGE, "q": "rent", "folder": ID},
]


def run_scope(queries: list[str], labels: list[str]) -> dict[str, Any]:
    assert NODE is not None
    argv = [
        NODE,
        "--input-type=module",
        "-e",
        SCOPE_DRIVER,
        (LIBRARY / "state.js").as_uri(),
        (LIBRARY / "data.js").as_uri(),
        (LIBRARY / "names.js").as_uri(),
        json.dumps([queries, STATES, labels]),
    ]
    result = subprocess.run(  # noqa: S603 - fixed argv: node runs a constant script
        argv, capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr
    answer: dict[str, Any] = json.loads(result.stdout)
    return answer


@pytest.fixture(scope="module")
def scoped() -> dict[str, Any]:
    queries = [
        "",
        f"?folder={ID}",
        f"?folder={ID}&q=rent&page=2",
        f"?folder={ID.upper()}",
        f"?folder={ID[:31]}",
        f"?folder={ID}0",
        "?folder=../etc/passwd",
        "?folder=root",
        "?folder=",
    ]
    labels = ["Finance", f"{RLO}{BELL}", f"A{RLO}B{BELL}", f" {ZWSP} ", "x" * 100]
    return run_scope(queries, labels)


@pytest.mark.parametrize(
    ("position", "folder"),
    [(0, ""), (1, ID), (2, ID), (3, ""), (4, ""), (5, ""), (6, ""), (7, ""), (8, "")],
    ids=[
        "none",
        "an id",
        "an id with a search",
        "upper case",
        "one short",
        "one long",
        "a path",
        "the word root",
        "empty",
    ],
)
def test_the_address_names_a_collection_only_by_a_well_formed_id(
    scoped: dict[str, Any], position: int, folder: str
) -> None:
    assert scoped["read"][position]["folder"] == folder


def test_the_collection_travels_with_the_rest_of_the_query(scoped: dict[str, Any]) -> None:
    assert (scoped["read"][2]["q"], scoped["read"][2]["page"]) == ("rent", 2)
    assert scoped["write"] == [
        "",
        f"?folder={ID}",
        f"?folder={ID}&q=rent&tag=demo&sort=name-asc&page=3",
        "?tag=demo",
        f"?folder={ID}&q=rent",
    ]


def test_the_list_follows_the_collection_until_a_search_or_a_tag_is_set(
    scoped: dict[str, Any],
) -> None:
    assert scoped["scoped"] == [True, True, False, False, False]
    assert scoped["scope"] == [
        {"folder": "root"},
        {"folder": ID},
        {"q": "rent", "tag": "demo"},
        {"q": "", "tag": "demo"},
        {"q": "rent", "tag": ""},
    ]


def test_a_collection_with_nothing_to_see_in_its_name_is_untitled(scoped: dict[str, Any]) -> None:
    assert scoped["label"] == [
        "Finance",
        "Untitled collection",
        "AB",
        "Untitled collection",
        "x" * 100,
    ]


def test_ids_have_the_shape_of_the_api_and_the_selection_lists_what_is_picked(
    scoped: dict[str, Any],
) -> None:
    assert scoped["ids"] == [True, False, False, False, False]
    assert scoped["picked"] == [{"id": "two", "name": "Second"}]
