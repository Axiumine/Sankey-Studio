"""``--allow-source-writes`` / ``SANKEY_SOURCE_WRITES``: field, validator, property, CLI, banner."""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from sankey_studio import cli
from sankey_studio.config import BootstrapConfig

REMOTE_HOST = "192.0.2.7"


def make(*, remote_mode: bool, remote_writes: bool, source_writes: bool) -> BootstrapConfig:
    return BootstrapConfig(
        host=REMOTE_HOST if remote_mode else "127.0.0.1",
        remote_mode=remote_mode,
        remote_writes=remote_writes,
        source_writes=source_writes,
    )


def test_source_writes_is_off_by_default() -> None:
    assert BootstrapConfig().source_writes is False


def test_the_environment_variable_turns_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "SANKEY_HOST": "192.0.2.7",
        "SANKEY_REMOTE_MODE": "true",
        "SANKEY_REMOTE_WRITES": "true",
        "SANKEY_SOURCE_WRITES": "true",
    }.items():
        monkeypatch.setenv(name, value)
    assert BootstrapConfig().source_writes is True


@pytest.mark.parametrize(
    ("remote_mode", "remote_writes", "source_writes", "allowed"),
    [
        (False, False, False, True),
        (True, False, False, False),
        (True, True, False, False),
        (True, True, True, True),
    ],
    ids=["loopback", "remote read-only", "remote writes only", "remote with source writes"],
)
def test_source_writes_allowed_truth_table(
    *, remote_mode: bool, remote_writes: bool, source_writes: bool, allowed: bool
) -> None:
    config = make(remote_mode=remote_mode, remote_writes=remote_writes, source_writes=source_writes)
    assert config.source_writes_allowed is allowed


@pytest.mark.parametrize(
    ("remote_mode", "remote_writes", "source_writes"),
    [flags for flags in itertools.product([False, True], repeat=3) if flags[2] and not flags[1]],
)
def test_source_writes_needs_remote_writes(
    *, remote_mode: bool, remote_writes: bool, source_writes: bool
) -> None:
    with pytest.raises(ValidationError) as caught:
        make(remote_mode=remote_mode, remote_writes=remote_writes, source_writes=source_writes)
    messages = [e["msg"] for e in caught.value.errors(include_input=False, include_url=False)]
    assert "Value error, source_writes needs remote_writes (--allow-remote-writes)" in messages


def test_the_flag_is_parsed_and_defaults_to_false() -> None:
    assert cli.parse_serve_args(["serve"]).allow_source_writes is False
    assert cli.parse_serve_args(["serve", "--allow-source-writes"]).allow_source_writes is True


def test_the_help_names_the_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parse_serve_args(["serve", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "--allow-source-writes" in out
    assert "with --allow-remote-writes: also allow writing edits back to MongoDB sources" in out


def test_build_config_sets_the_field_only_when_asked() -> None:
    base = cli.ServeArgs(host=REMOTE_HOST, allow_remote=True, allow_remote_writes=True)
    asked = cli.ServeArgs(
        host=REMOTE_HOST, allow_remote=True, allow_remote_writes=True, allow_source_writes=True
    )
    assert cli.build_config(base).source_writes is False
    assert cli.build_config(asked).source_writes is True


def test_build_config_refuses_the_flag_without_remote_writes() -> None:
    args = cli.ServeArgs(host="192.0.2.7", allow_remote=True, allow_source_writes=True)
    with pytest.raises(ValidationError, match="source_writes needs remote_writes"):
        cli.build_config(args)


@pytest.mark.parametrize(("flag", "word"), [(False, "DISABLED"), (True, "ENABLED")])
def test_the_remote_banner_states_source_writes(
    capsys: pytest.CaptureFixture[str], *, flag: bool, word: str
) -> None:
    config = BootstrapConfig(
        host="192.0.2.7", remote_mode=True, remote_writes=flag, source_writes=flag
    )
    cli._announce(config)
    lines = capsys.readouterr().out.splitlines()
    assert f"source writes: {word}" in lines
    assert lines.index(f"source writes: {word}") == lines.index("*" * 72, 4) + 1


def test_a_local_start_prints_no_source_writes_line(capsys: pytest.CaptureFixture[str]) -> None:
    cli._announce(BootstrapConfig())
    assert "source writes" not in capsys.readouterr().out
