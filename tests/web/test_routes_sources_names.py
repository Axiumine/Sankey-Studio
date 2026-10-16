# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Every name ``GET /sources/files`` lists can be previewed and deleted (newline, space, UTF-8)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

import pytest
from starlette.convertors import CONVERTOR_TYPES, PathConvertor

from sankey_studio.web.routers.sources import NewlinePathConvertor, router
from tests.web.test_routes_sources_support import FILES, error_of, listed, put_file

if TYPE_CHECKING:
    from pathlib import Path

    from tests.web.conftest import AppFactory, WebApp

#: Names an operator can plant: the newline is what ``.*`` could not match.
NAMES: Final = [
    "a\nb.csv",
    "\nleading.csv",
    "two\n\nlines.tsv",
    "sub/a\nb.json",
    "a\nb/c.csv",
    "my file.csv",
    "  padded  .csv",
    "ünï côdé 日本語.csv",
    "sub dir/ü 1.tsv",
    "emoji \U0001f4c8.txt",
    "a\rb.csv",
    "a\N{LINE SEPARATOR}b.csv",
    "tab\there.csv",
    "100%.csv",
    "plus+sign?.csv",
    "hash#tag.csv",
]
CONTENT: Final = b"left,right,1\nsecond,line,2\n"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([router])


def url_of(name: str) -> str:
    """The request path of ``name`` the way a browser sends it (percent-encoded, ``/`` kept)."""
    return f"{FILES}/{quote(name, safe='/')}"


@pytest.mark.parametrize("name", NAMES, ids=repr)
def test_a_listed_name_can_be_previewed_and_deleted(web: WebApp, name: str) -> None:
    put_file(web, name, CONTENT)
    assert listed(web.client) == [name]

    preview = web.client.get(f"{url_of(name)}/preview")
    assert preview.status_code == 200
    assert preview.json() == {"name": name, "lines": ["left,right,1", "second,line,2"]}

    deleted = web.client.delete(url_of(name))
    assert (deleted.status_code, deleted.content) == (204, b"")
    assert listed(web.client) == []
    assert web.client.get(f"{url_of(name)}/preview").status_code == 404


def test_every_name_at_once_is_listed_and_addressable(web: WebApp) -> None:
    for name in NAMES:
        put_file(web, name, CONTENT)
    names = listed(web.client)
    assert sorted(names) == sorted(NAMES)
    for name in names:
        assert web.client.get(f"{url_of(name)}/preview").status_code == 200
    for name in names:
        assert web.client.delete(url_of(name)).status_code == 204
    assert listed(web.client) == []


def test_a_name_with_a_backslash_is_not_listed_because_preview_and_delete_refuse_it(
    web: WebApp,
) -> None:
    put_file(web, "ok.csv", CONTENT)
    put_file(web, "a\\b.csv", CONTENT)
    put_file(web, "dir\\x/f.csv", CONTENT)
    assert listed(web.client) == ["ok.csv"]
    refused = web.client.get(f"{url_of('a' + chr(92) + 'b.csv')}/preview")
    assert (refused.status_code, error_of(refused)["code"]) == (400, "unsafe_source")


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_a_missing_name_with_a_newline_reaches_the_handler(web: WebApp, method: str) -> None:
    """A 404 ``source_not_found`` comes from the file layer; a routing miss is ``not_found``."""
    suffix = "/preview" if method == "GET" else ""
    response = web.client.request(method, f"{url_of('gone\nfile.csv')}{suffix}")
    assert response.status_code == 404
    assert error_of(response)["code"] == "source_not_found"


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_an_unknown_extension_with_a_newline_is_still_refused_by_the_file_layer(
    web: WebApp, method: str
) -> None:
    suffix = "/preview" if method == "GET" else ""
    response = web.client.request(method, f"{url_of('a\nb.exe')}{suffix}")
    assert response.status_code == 400
    assert error_of(response)["code"] == "unsafe_source"


def test_a_newline_cannot_be_used_to_leave_the_sources_directory(
    web: WebApp, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_bytes(b"top,secret,1\n")
    put_file(web, "a.csv")
    for probe in ("..\n/secret.csv", "sub\n/../../secret.csv", "a\n/../../secret.csv"):
        response = web.client.delete(url_of(probe))
        assert response.status_code in {400, 404}
    assert secret.read_bytes() == b"top,secret,1\n"
    assert listed(web.client) == ["a.csv"]


# --------------------------------------------------------------------------- the convertor

MATCHES: Final = [
    "",
    "a",
    "a.csv",
    "a/b/c.csv",
    "a\nb",
    "\n",
    "\n\n",
    "a b",
    "ü",
    "\r",
    "\N{LINE SEPARATOR}",
]


def test_the_path_key_is_the_newline_aware_convertor() -> None:
    convertor = CONVERTOR_TYPES["path"]
    assert type(convertor) is NewlinePathConvertor
    assert isinstance(convertor, PathConvertor)


@pytest.mark.parametrize("value", MATCHES, ids=repr)
def test_the_convertor_matches_the_whole_value(value: str) -> None:
    pattern = re.compile(NewlinePathConvertor.regex)
    assert pattern.fullmatch(value) is not None
    assert NewlinePathConvertor().convert(value) == value
    assert NewlinePathConvertor().to_string(value) == value


def test_the_route_templates_and_openapi_paths_are_unchanged(web: WebApp) -> None:
    templates = {route.path for route in router.routes if hasattr(route, "path")}
    assert f"{FILES}/{{name:path}}" in templates
    assert f"{FILES}/{{name:path}}/preview" in templates
    paths = web.app.openapi()["paths"]
    assert f"{FILES}/{{name}}" in paths
    assert f"{FILES}/{{name}}/preview" in paths
