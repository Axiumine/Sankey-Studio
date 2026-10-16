# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The operator reads the banner BEFORE the server starts: the server call blocks until shutdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio import cli

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from sankey_studio.config import BootstrapConfig


@pytest.fixture
def printed_before_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    """What the console showed at the moment the (replaced) server call began."""
    seen: list[str] = []

    def fake(_app: FastAPI, _config: BootstrapConfig) -> None:
        seen.append(capsys.readouterr().out)

    monkeypatch.setattr(cli, "_run_server", fake)
    return seen


def test_a_local_start_prints_the_address_before_serving(
    printed_before_serving: list[str], tmp_path: Path
) -> None:
    assert cli.main(["serve", "--data-dir", str(tmp_path)]) == 0
    assert printed_before_serving == [
        f"Data directory: {tmp_path}\nListening on http://127.0.0.1:8765\n"
    ]


def test_the_no_authentication_banner_is_printed_before_serving(
    printed_before_serving: list[str], tmp_path: Path
) -> None:
    argv = ["serve", "--data-dir", str(tmp_path), "--host", "192.0.2.7", "--allow-remote"]
    assert cli.main(argv) == 0
    (before,) = printed_before_serving
    assert "REMOTE MODE: NO AUTHENTICATION" in before
    assert "Accepted Host headers:" in before
