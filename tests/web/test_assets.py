# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``web/assets.py``: the ``/static/v-<digest>/`` prefix of every static link a page carries."""

from __future__ import annotations

import hashlib
import os
import re
from typing import TYPE_CHECKING, Final

import pytest

from sankey_studio.web import assets
from tests.web.test_pages_support import unversioned
from tests.web.test_routes_graphs_support import PLAIN, save
from tests.web.test_static_policy import static_refs

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from tests.web.conftest import WebApp

BROWSER: Final = {"Accept": "text/html"}
VERSIONED: Final = re.compile(r"^/static/v-([0-9a-f]{12})/")


@pytest.fixture
def static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    (tmp_path / "css").mkdir()
    monkeypatch.setattr(assets, "STATIC_DIR", tmp_path)
    assets.tree_version.cache_clear()
    yield tmp_path
    assets.tree_version.cache_clear()


def digest(*files: tuple[str, bytes]) -> str:
    """What ``tree_version`` computes for ``files`` (relative path, content), in path order."""
    data = b"".join(name.encode() + b"\0" + content + b"\0" for name, content in sorted(files))
    return hashlib.sha256(data).hexdigest()[:12]


def test_the_url_carries_the_first_twelve_hex_characters_of_the_tree_digest(
    static_dir: Path,
) -> None:
    (static_dir / "css" / "a.css").write_bytes(b"body{}")
    (static_dir / "b.js").write_bytes(b"x")
    version = digest(("b.js", b"x"), ("css/a.css", b"body{}"))
    assert assets.static_url("css/a.css") == f"/static/v-{version}/css/a.css"
    assert assets.static_url("missing.css") == f"/static/v-{version}/missing.css"
    assert len(version) == assets.DIGEST_LENGTH == 12


def test_the_version_is_computed_once_per_process(static_dir: Path) -> None:
    path = static_dir / "css" / "a.css"
    path.write_bytes(b"one")
    first = assets.static_url("css/a.css")
    path.write_bytes(b"two")
    assert assets.static_url("css/a.css") == first, "cached: the tree is read once"
    assets.tree_version.cache_clear()
    assert assets.static_url("css/a.css") == f"/static/v-{digest(('css/a.css', b'two'))}/css/a.css"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ({"a.css": b"one"}, {"a.css": b"two"}),
        ({"a.css": b"one"}, {"b.css": b"one"}),
        ({"a.css": b"one"}, {"a.css": b"one", "c.css": b""}),
        ({"ab": b"c"}, {"a": b"bc"}),
    ],
)
def test_any_change_of_a_name_or_a_content_is_a_new_version(
    tmp_path: Path, before: dict[str, bytes], after: dict[str, bytes]
) -> None:
    versions = []
    for index, files in enumerate((before, after)):
        root = tmp_path / str(index)
        root.mkdir()
        for name, content in files.items():
            (root / name).write_bytes(content)
        versions.append(assets.tree_version(root))
    assert versions[0] != versions[1]


def test_an_unreadable_file_counts_by_its_name(static_dir: Path) -> None:
    path = static_dir / "css" / "a.css"
    path.write_text("x", encoding="utf-8")
    path.chmod(0)
    try:
        readable = os.access(path, os.R_OK)
        expected = hashlib.sha256(b"css/a.css\0" + (b"x" if readable else b"\0unreadable") + b"\0")
        assert assets.tree_version(static_dir) == expected.hexdigest()[:12]
    finally:
        path.chmod(0o600)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("v-0123456789ab/css/a.css", "css/a.css"),
        ("v-0123456789ab/a.css", "a.css"),
        ("css/a.css", "css/a.css"),
        ("v-0123456789ab", "v-0123456789ab"),
        ("v-0123456789a/css/a.css", "v-0123456789a/css/a.css"),
        ("v-0123456789abc/css/a.css", "v-0123456789abc/css/a.css"),
        ("v-0123456789AB/css/a.css", "v-0123456789AB/css/a.css"),
        ("x-0123456789ab/css/a.css", "x-0123456789ab/css/a.css"),
        ("css/v-0123456789ab/a.css", "css/v-0123456789ab/a.css"),
    ],
)
def test_only_a_leading_version_segment_is_dropped(path: str, expected: str) -> None:
    assert assets.unversioned(path.replace("/", os.sep)) == expected.replace("/", os.sep)


def test_the_page_templates_link_every_static_file_under_the_current_version(
    web: WebApp,
) -> None:
    graph_id = save(web, "Budget", *PLAIN).id
    version = assets.tree_version(assets.STATIC_DIR)
    for path in ["/", "/graphs/new", "/settings", f"/graphs/{graph_id}", "/nope"]:
        refs = static_refs(web.client.get(path, headers=BROWSER).text)
        assert len(refs) >= 7, path
        for ref in refs:
            match = VERSIONED.match(ref)
            assert match, (path, ref)
            assert match.group(1) == version, (path, ref)
            plain = web.client.get(unversioned(ref))
            assert web.client.get(ref).content == plain.content, (path, ref)
