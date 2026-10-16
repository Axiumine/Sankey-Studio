# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``sankey-studio serve``: argument parsing and the configuration it builds."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from pydantic import ValidationError

from sankey_studio.cli import ServeArgs, build_config, parse_serve_args

if TYPE_CHECKING:
    from collections.abc import Sequence


class Parsed(NamedTuple):
    argv: list[str]
    args: ServeArgs


PARSED = [
    Parsed(["serve"], ServeArgs()),
    Parsed(["serve", "--host", "192.0.2.7"], ServeArgs(host="192.0.2.7")),
    Parsed(["serve", "--port", "9100"], ServeArgs(port=9100)),
    Parsed(["serve", "--data-dir", "/d"], ServeArgs(data_dir=Path("/d"))),
    Parsed(["serve", "--sources-dir", "/s"], ServeArgs(sources_dir=Path("/s"))),
    Parsed(["serve", "--allow-remote"], ServeArgs(allow_remote=True)),
    Parsed(["serve", "--allow-remote-writes"], ServeArgs(allow_remote_writes=True)),
    Parsed(
        [
            "serve",
            "--host=h",
            "--port=1",
            "--data-dir=/d",
            "--sources-dir=/s",
            "--allow-remote",
            "--allow-remote-writes",
        ],
        ServeArgs("h", 1, Path("/d"), Path("/s"), allow_remote=True, allow_remote_writes=True),
    ),
]


@pytest.mark.parametrize("case", PARSED, ids=lambda c: " ".join(c.argv))
def test_parse_serve_args(case: Parsed) -> None:
    assert parse_serve_args(case.argv) == case.args


def test_serve_args_default_to_not_given() -> None:
    args = ServeArgs()
    assert (args.host, args.port, args.data_dir, args.sources_dir) == (None, None, None, None)
    assert (args.allow_remote, args.allow_remote_writes) == (False, False)


@pytest.mark.parametrize(
    "argv",
    [[], ["bogus"], ["serve", "--port", "abc"], ["serve", "--nope"], ["serve", "extra"]],
    ids=" ".join,
)
def test_bad_usage_exits_with_status_2(
    argv: Sequence[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_serve_args(argv)
    assert exit_info.value.code == 2
    assert "usage: sankey-studio" in capsys.readouterr().err


def test_help_lists_every_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_serve_args(["serve", "--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for option in (
        "--host",
        "--port",
        "--data-dir",
        "--sources-dir",
        "--allow-remote",
        "--allow-remote-writes",
    ):
        assert option in out


def test_defaults_come_from_bootstrap_config(tmp_path: Path) -> None:
    config = build_config(ServeArgs(data_dir=tmp_path / "d"))
    assert (config.host, config.port) == ("127.0.0.1", 8765)
    assert config.data_dir == tmp_path / "d"
    assert (config.remote_mode, config.remote_writes) == (False, False)
    assert config.sources_dir is None


def test_given_options_override_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SANKEY_PORT", "9100")
    monkeypatch.setenv("SANKEY_DATA_DIR", str(tmp_path / "env"))
    from_env = build_config(ServeArgs())
    given = build_config(ServeArgs(port=9200, data_dir=tmp_path / "cli"))
    assert (from_env.port, from_env.data_dir) == (9100, tmp_path / "env")
    assert (given.port, given.data_dir) == (9200, tmp_path / "cli")


def test_the_options_fill_every_field(tmp_path: Path) -> None:
    args = ServeArgs(
        host="192.0.2.7",
        port=9300,
        data_dir=tmp_path / "d",
        sources_dir=tmp_path / "s",
        allow_remote=True,
        allow_remote_writes=True,
    )
    config = build_config(args)
    assert (config.host, config.port) == ("192.0.2.7", 9300)
    assert (config.data_dir, config.sources_dir) == (tmp_path / "d", tmp_path / "s")
    assert (config.remote_mode, config.remote_writes) == (True, True)
    assert "192.0.2.7" in config.allowed_hosts


def test_remote_mode_without_writes_is_read_only(tmp_path: Path) -> None:
    config = build_config(ServeArgs(data_dir=tmp_path, allow_remote=True))
    assert (config.remote_mode, config.remote_writes) == (True, False)
    assert config.privileged_writes_allowed is False


def test_a_flag_never_turns_an_environment_setting_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SANKEY_REMOTE_MODE", "true")
    config = build_config(ServeArgs(data_dir=tmp_path))
    assert config.remote_mode is True


@pytest.mark.parametrize(
    "args",
    [
        ServeArgs(host="192.0.2.7"),
        ServeArgs(allow_remote_writes=True),
        ServeArgs(port=0),
        ServeArgs(port=65536),
    ],
    ids=["non-loopback without --allow-remote", "writes without remote", "port 0", "port 65536"],
)
def test_the_validators_refuse_unsafe_or_invalid_options(args: ServeArgs, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        build_config(replace(args, data_dir=tmp_path))
