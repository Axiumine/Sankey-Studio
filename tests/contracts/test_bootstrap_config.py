# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests: ``BootstrapConfig`` (environment, hosts, data dirs, secret hygiene)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sankey_studio.config import BootstrapConfig


def test_defaults_are_hermetic_and_local() -> None:
    config = BootstrapConfig()
    assert config.mongo_uri is None  # conftest scrubs SANKEY_* so a developer env never leaks in
    assert config.is_loopback
    assert config.data_dir.is_absolute()
    assert config.data_dir.name == "sankey-studio"
    assert config.effective_sources_dir == config.data_dir / "sources"
    assert config.privileged_writes_allowed is True
    assert "*" not in config.allowed_hosts


def test_developer_sankey_env_cannot_leak_into_tests() -> None:
    """A real ``SANKEY_MONGO_URI`` in the shell must not seed a connection during the suite."""
    env = {
        **os.environ,
        "SANKEY_MONGO_URI": "mongodb://real:pw@127.0.0.1:27017/",
        "SANKEY_PORT": "1",
    }
    node = "tests/contracts/test_bootstrap_config.py::test_defaults_are_hermetic_and_local"
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", node],
        cwd=Path(__file__).parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-600:]


URI_WITH_PASSWORD = "mongodb://u:hunter2@db.internal:27017/?appName=x"


@pytest.mark.parametrize(
    "env",
    [
        {"SANKEY_HOST": "0.0.0.0"},  # noqa: S104 - model validator: the whole input dict is echoed
        {"SANKEY_PORT": "0"},  # field validator
        {"SANKEY_PORT": "not-a-number"},
        {"SANKEY_REMOTE_WRITES": "true"},
        {"SANKEY_ALLOWED_HOSTS": '["*"]'},
    ],
)
def test_bootstrap_errors_never_echo_an_env_seeded_uri(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    monkeypatch.setenv("SANKEY_MONGO_URI", URI_WITH_PASSWORD)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError) as info:
        BootstrapConfig()
    # pydantic truncates long inputs in the middle, which can still show a fragment of the secret:
    # assert on the mechanism (no echoed input at all), not only on the one password.
    assert "input_value" not in str(info.value)
    assert "hunter2" not in str(info.value)
    assert "hunter2" not in repr(info.value)
    safe = info.value.errors(include_input=False, include_url=False)
    assert "hunter2" not in json.dumps(safe, default=str)
    assert all("input" not in item for item in safe)


def test_bootstrap_errors_never_echo_a_keyword_uri() -> None:
    with pytest.raises(ValidationError) as info:
        BootstrapConfig(host="0.0.0.0", mongo_uri=URI_WITH_PASSWORD)  # type: ignore[arg-type]  # noqa: S104 - wildcard bind under test
    assert "input_value" not in str(info.value)
    assert "hunter2" not in str(info.value)
    assert "remote_mode" in str(info.value)  # the reason is still reported


def test_bootstrap_config_hides_its_uri_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANKEY_MONGO_URI", URI_WITH_PASSWORD)
    config = BootstrapConfig()
    assert config.mongo_uri is not None
    assert config.mongo_uri.get_secret_value() == URI_WITH_PASSWORD
    assert "hunter2" not in repr(config)
    assert "hunter2" not in str(config)
    assert "hunter2" not in config.model_dump_json()


def test_env_is_read_with_the_sankey_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("SANKEY_PORT", "9001")
    monkeypatch.setenv("SANKEY_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("SANKEY_SOURCES_DIR", str(tmp_path / "inbox"))
    config = BootstrapConfig()
    assert config.port == 9001
    assert config.data_dir == (tmp_path / "d").resolve()
    assert config.effective_sources_dir == (tmp_path / "inbox").resolve()


def test_data_dirs_are_made_absolute(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    config = BootstrapConfig(data_dir="rel/data", sources_dir="rel/in")  # type: ignore[arg-type]
    assert config.data_dir == (tmp_path / "rel" / "data").resolve()
    assert config.effective_sources_dir == (tmp_path / "rel" / "in").resolve()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::"])  # noqa: S104 - binds under test
def test_non_loopback_host_needs_remote_mode(host: str) -> None:
    with pytest.raises(ValidationError, match="remote_mode"):
        BootstrapConfig(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_loopback_hosts_need_nothing(host: str) -> None:
    assert BootstrapConfig(host=host).is_loopback


def test_remote_mode_is_read_only_until_writes_are_enabled() -> None:
    config = BootstrapConfig(host="192.168.1.5", remote_mode=True)
    assert config.privileged_writes_allowed is False
    assert "192.168.1.5" in config.allowed_hosts  # the bound address is added, not "*"
    assert "*" not in config.allowed_hosts
    writable = BootstrapConfig(host="192.168.1.5", remote_mode=True, remote_writes=True)
    assert writable.privileged_writes_allowed is True
    wildcard = BootstrapConfig(host="0.0.0.0", remote_mode=True)  # noqa: S104 - wildcard bind under test
    assert "0.0.0.0" not in wildcard.allowed_hosts  # noqa: S104 - wildcard bind under test


def test_remote_writes_and_wildcard_hosts_need_remote_mode() -> None:
    with pytest.raises(ValidationError, match="remote_mode"):
        BootstrapConfig(remote_writes=True)
    with pytest.raises(ValidationError, match="'\\*'"):
        BootstrapConfig(allowed_hosts=["*"])
    assert (
        "*" in BootstrapConfig(host="10.0.0.2", remote_mode=True, allowed_hosts=["*"]).allowed_hosts
    )


def test_sources_dir_may_not_expose_settings_or_graphs(tmp_path: Any) -> None:
    data = tmp_path / "data"
    bad = [
        data,  # equals data_dir: settings.json would be readable
        tmp_path,  # contains data_dir
        data / "graphs",
        data / "graphs" / "sub",
        "/",
    ]
    for candidate in bad:
        with pytest.raises(ValidationError, match="sources_dir"):
            BootstrapConfig(data_dir=data, sources_dir=candidate)
    ok = BootstrapConfig(data_dir=data, sources_dir=tmp_path / "elsewhere")
    assert ok.effective_sources_dir == (tmp_path / "elsewhere").resolve()
    assert BootstrapConfig(data_dir=data, sources_dir=data / "inbox").sources_dir is not None
