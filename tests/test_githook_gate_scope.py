# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Files no check reads (Markdown, ``docs/`` images) do not void a stamp.

A stamp is keyed by the tree of the pushed commit without those files (``scoped_key``): a README
edit or a new screenshot leaves the key, and so every stamp, as it was. Nothing else does: code,
tests, config, a Markdown file under ``src/``, an image anywhere but ``docs/``, a changed mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts import githook_push as push
from scripts.githook_plan import CHECK_ORDER, is_inert, scoped_key

from tests.githook_support import Case, Rig, case_id, commit_file, make_rig, push_line

if TYPE_CHECKING:
    from pathlib import Path

INERT = [
    Case("README.md", True, "the README"),
    Case("CHANGELOG.md", True, "the changelog"),
    Case("CLAUDE.md", True, "the working agreement"),
    Case("docs/ui.md", True, "a doc"),
    Case("docs/screenshots/editor-light.png", True, "a README screenshot"),
    Case("docs/screenshots/gallery/01-library.PNG", True, "the case of the suffix is ignored"),
    Case("docs/screenshots/a.jpg", True, "jpg"),
    Case("docs/screenshots/a.jpeg", True, "jpeg"),
    Case("docs/screenshots/a.gif", True, "gif"),
    Case("docs/screenshots/a.webp", True, "webp"),
    Case(".claude/skills/gitnexus-cli/SKILL.md", True, "a skill file"),
    Case("src/sankey_studio/notes.md", False, "Markdown inside src ships with the package"),
    Case("src/sankey_studio/web/static/img/logo.png", False, "an image the app serves"),
    Case("tests/fixtures/shot.png", False, "an image outside docs"),
    Case("docs/diagram.svg", False, "svg is text, a test may read it"),
    Case("docs/extra.py", False, "code under docs"),
    Case("docs/screenshots/readme.txt", False, "text under docs"),
    Case("LICENSE", False, "the license is a build input"),
    Case("Makefile", False, "the Makefile"),
    Case("pyproject.toml", False, "the project file"),
    Case("scripts/tool.py", False, "code"),
    Case("docs/md", False, "a name that only ends in md"),
]


@pytest.mark.parametrize("case", INERT, ids=case_id)
def test_which_files_no_check_reads(case: Case[str, bool]) -> None:
    assert is_inert(case.given) is case.expected


def entry(path: str, sha: str = "a" * 40, mode: str = "100644") -> str:
    return f"{mode} blob {sha}\t{path}"


BASE = [entry("a.py"), entry("README.md"), entry("docs/screenshots/x.png")]


def test_the_key_ignores_inert_files_their_content_and_the_order() -> None:
    key = scoped_key(BASE)
    assert scoped_key([entry("README.md", "b" * 40), *BASE[::-1]]) == key  # edited README, order
    assert scoped_key([*BASE, entry("docs/screenshots/gallery/new.png")]) == key  # a new image
    assert scoped_key([entry("a.py")]) == key  # no inert file at all
    assert scoped_key([*BASE, ""]) == key  # the empty piece after the last NUL


CHANGED = [
    pytest.param([entry("a.py", "b" * 40), *BASE[1:]], id="the content of code"),
    pytest.param([entry("a.py", mode="100755"), *BASE[1:]], id="the mode of code"),
    pytest.param([*BASE, entry("b.py")], id="a new code file"),
    pytest.param(BASE[1:], id="a deleted code file"),
    pytest.param([*BASE, entry("src/x/notes.md")], id="Markdown inside src"),
    pytest.param([*BASE, entry("tests/shot.png")], id="an image outside docs"),
]


@pytest.mark.parametrize("entries", CHANGED)
def test_any_other_change_gives_another_key(entries: list[str]) -> None:
    assert scoped_key(entries) != scoped_key(BASE)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def stamped_everywhere(rig: Rig) -> str:
    first = rig.tree()
    rig.stamp_all(CHECK_ORDER, first)
    return first


def commit_at(rig: Rig, name: str, text: str = "new\n") -> str:
    path = rig.repo.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    commit_file(rig.repo.root, name, text)
    return rig.tree()


DOCS_ONLY = [
    pytest.param("README.md", id="a new README"),
    pytest.param("docs/ui.md", id="an edited doc"),
    pytest.param("docs/screenshots/gallery/01-library.png", id="a new screenshot"),
    pytest.param("deep/er/NOTES.md", id="Markdown anywhere but src"),
]


@pytest.mark.parametrize("name", DOCS_ONLY)
def test_a_change_to_inert_files_keeps_every_stamp(rig: Rig, name: str) -> None:
    first = stamped_everywhere(rig)
    second = commit_at(rig, name)
    assert second != first  # a real new tree
    assert rig.gate.scoped(second) == rig.gate.scoped(first)
    assert all(rig.stamped(name, second) for name in CHECK_ORDER)


CODE = [
    pytest.param("a.py", id="new code"),
    pytest.param("src/sankey_studio/notes.md", id="Markdown inside src"),
    pytest.param("Makefile", id="the Makefile"),
    pytest.param("LICENSE.txt", id="a license text file"),
    pytest.param("src/img/logo.png", id="an image the app serves"),
]


@pytest.mark.parametrize("name", CODE)
def test_a_change_to_anything_else_voids_every_stamp(rig: Rig, name: str) -> None:
    first = stamped_everywhere(rig)
    second = commit_at(rig, name)
    assert not any(rig.stamped(name, second) for name in CHECK_ORDER)
    assert all(rig.stamped(name, first) for name in CHECK_ORDER)  # the old tree keeps its own


def test_a_push_after_a_docs_only_commit_has_nothing_left_to_run(rig: Rig) -> None:
    stamped_everywhere(rig)
    commit_at(rig, "docs/screenshots/gallery/01-library.png")
    commit_at(rig, "README.md", "# Sankey Studio\n")
    sha = rig.git("rev-parse", "HEAD")
    text = push_line("refs/heads/main", sha, "refs/heads/main")
    assert push.pre_push(rig.gate, "origin", text) == 0
    assert rig.runner.calls == []
    assert "every required check has a stamp for the pushed tree(s)" in rig.text


def test_the_key_of_a_tree_is_asked_of_git_once(rig: Rig) -> None:
    tree = rig.tree()
    assert tree not in rig.gate._scoped
    key = rig.gate.scoped(tree)
    assert rig.gate._scoped == {tree: key}
    assert rig.gate.scoped(tree) == key == rig.gate.repo.scoped_tree(tree)
