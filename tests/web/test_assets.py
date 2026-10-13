"""``web/assets.py``: the ``?v=<digest>`` of every static link a page carries."""

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
    from pathlib import Path

    from tests.web.conftest import WebApp

BROWSER: Final = {"Accept": "text/html"}
VERSION: Final = re.compile(r"\?v=([0-9a-f]{12})$")


@pytest.fixture
def static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "css").mkdir()
    monkeypatch.setattr(assets, "STATIC_DIR", tmp_path)
    return tmp_path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def test_the_url_carries_the_first_twelve_hex_characters_of_the_content_digest(
    static_dir: Path,
) -> None:
    (static_dir / "css" / "a.css").write_bytes(b"body{}")
    url = assets.static_url("css/a.css")
    assert url == f"/static/css/a.css?v={digest(b'body{}')}"
    assert len(digest(b"body{}")) == assets.DIGEST_LENGTH == 12


def test_a_changed_file_gets_a_new_version(static_dir: Path) -> None:
    path = static_dir / "css" / "a.css"
    path.write_bytes(b"one")
    first = assets.static_url("css/a.css")
    assert assets.static_url("css/a.css") == first
    path.write_bytes(b"two!")
    assert assets.static_url("css/a.css") == f"/static/css/a.css?v={digest(b'two!')}"


def test_the_digest_follows_the_modification_time_and_the_size(static_dir: Path) -> None:
    path = static_dir / "css" / "a.css"
    path.write_bytes(b"aaa")
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    first = assets.static_url("css/a.css")
    path.write_bytes(b"bbb")
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert assets.static_url("css/a.css") == first, "same stat: the digest is not read again"
    os.utime(path, ns=(2_000_000_000, 2_000_000_000))
    assert assets.static_url("css/a.css") == f"/static/css/a.css?v={digest(b'bbb')}"
    path.write_bytes(b"cccc")
    os.utime(path, ns=(2_000_000_000, 2_000_000_000))
    assert assets.static_url("css/a.css") == f"/static/css/a.css?v={digest(b'cccc')}"


@pytest.mark.parametrize("name", ["css/missing.css", "css", "../outside.css", "css/../../x.css"])
def test_a_name_that_is_not_a_file_of_the_directory_gets_the_plain_url(
    static_dir: Path, name: str
) -> None:
    (static_dir.parent / "outside.css").write_text("x", encoding="utf-8")
    assert assets.static_url(name) == f"/static/{name}"


def test_an_unreadable_file_gets_the_plain_url(static_dir: Path) -> None:
    path = static_dir / "css" / "a.css"
    path.write_text("x", encoding="utf-8")
    path.chmod(0)
    try:
        readable = os.access(path, os.R_OK)
        assert assets.static_url("css/a.css") == (
            f"/static/css/a.css?v={digest(b'x')}" if readable else "/static/css/a.css"
        )
    finally:
        path.chmod(0o600)


def test_the_page_templates_link_every_static_file_with_its_digest(web: WebApp) -> None:
    graph_id = save(web, "Budget", *PLAIN).id
    for path in ["/", "/graphs/new", "/settings", f"/graphs/{graph_id}", "/nope"]:
        refs = static_refs(web.client.get(path, headers=BROWSER).text)
        assert len(refs) >= 7, path
        for ref in refs:
            match = VERSION.search(ref)
            assert match, (path, ref)
            served = web.client.get(ref)
            assert match.group(1) == digest(served.content), (path, ref)
            assert unversioned(ref).startswith("/static/"), ref
