# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``support.rs_env``: where the replica-set suite finds its URI (environment, else dotenv file).

Only ``SANKEY_TEST_MONGO_RS_URI`` is taken from the file; another key (the Qodana token lives
there) is never returned. All inputs below are made up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import REAL_MONGO_RS_ENV
from tests.e2e.support.rs_env import ENV_FILE, rs_uri, value_from_env_file

if TYPE_CHECKING:
    from pathlib import Path

URI = "mongodb://u:p@h1:27017,h2:27017/db?replicaSet=rs0&authSource=db"
KEY = REAL_MONGO_RS_ENV


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"{KEY}={URI}\n", URI),
        (f'{KEY}="{URI}"\n', URI),
        (f"{KEY}='{URI}'\n", URI),
        (f"export {KEY}={URI}\n", URI),
        (f"  {KEY} = {URI}  \n", URI),
        (f"{KEY}={URI} # my lab set\n", URI),
        (f'{KEY}="{URI} # kept"\n', f"{URI} # kept"),
        (f'{KEY}="{URI}" # my lab set\n', URI),
        (f"{KEY}='{URI}'   # my lab set\n", URI),
        (f'{KEY}="unterminated\n', '"unterminated'),
        (f"{KEY}=mongodb://old\n{KEY}={URI}\n", URI),
        (f"# {KEY}={URI}\n", None),
        (f"OTHER_KEY={URI}\n{KEY}_X={URI}\n", None),
        (f"{KEY}=\n", None),
        (f"{KEY}=''\n", None),
        (f"{KEY}\n", None),
        ("", None),
    ],
)
def test_the_value_of_the_one_key_is_read(tmp_path: Path, text: str, expected: str | None) -> None:
    path = tmp_path / "dotenv"
    path.write_text(text, encoding="utf-8")
    assert value_from_env_file(path, KEY) == expected


def test_other_keys_of_the_file_are_never_returned(tmp_path: Path) -> None:
    path = tmp_path / "dotenv"
    path.write_text(f"SECRET_TOKEN=abc\n{KEY}={URI}\n", encoding="utf-8")
    assert value_from_env_file(path, "SECRET_TOKEN") == "abc"  # the reader is key-driven...
    assert rs_uri({}, path) == URI  # ...and rs_uri only ever asks for its own key


def test_a_missing_or_unreadable_file_is_no_value(tmp_path: Path) -> None:
    assert value_from_env_file(tmp_path / "absent", KEY) is None
    binary = tmp_path / "binary"
    binary.write_bytes(b"\xff\xfe\x00")
    assert value_from_env_file(binary, KEY) is None
    assert value_from_env_file(tmp_path, KEY) is None  # a directory


def test_the_environment_wins_over_the_file(tmp_path: Path) -> None:
    path = tmp_path / "dotenv"
    path.write_text(f"{KEY}=mongodb://from-file\n", encoding="utf-8")
    assert rs_uri({KEY: URI}, path) == URI
    assert rs_uri({KEY: ""}, path) == "mongodb://from-file"
    assert rs_uri({}, path) == "mongodb://from-file"
    assert rs_uri({}, tmp_path / "absent") is None


def test_the_process_environment_is_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(KEY, URI)
    assert rs_uri(path=tmp_path / "absent") == URI
    monkeypatch.delenv(KEY)
    assert rs_uri(path=tmp_path / "absent") is None


def test_the_file_is_looked_for_in_the_repository_root() -> None:
    assert ENV_FILE.name == ".env"
    assert (ENV_FILE.parent / "pyproject.toml").is_file()
