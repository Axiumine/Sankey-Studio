"""``main``: the banner, configuration errors, the uvicorn seam and ``python -m sankey_studio``."""

from __future__ import annotations

import runpy
import sys
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
import uvicorn
from fastapi import FastAPI

from sankey_studio import cli
from sankey_studio.config import BootstrapConfig

if TYPE_CHECKING:
    from pathlib import Path

STARS = "*" * 72


class Served(NamedTuple):
    app: FastAPI
    config: BootstrapConfig


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[Served]:
    """Replaces the uvicorn seam: records what would have been served."""
    calls: list[Served] = []
    monkeypatch.setattr(cli, "_run_server", lambda app, config: calls.append(Served(app, config)))
    return calls


def test_a_local_start_prints_the_data_dir_and_address(
    served: list[Served], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["serve", "--data-dir", str(tmp_path / "d")]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"Data directory: {tmp_path / 'd'}\nListening on http://127.0.0.1:8765\n"
    assert captured.err == ""
    (call,) = served
    assert isinstance(call.app, FastAPI)
    assert call.app.state.config is call.config
    assert (call.config.host, call.config.port) == ("127.0.0.1", 8765)


def test_the_port_option_reaches_the_server(served: list[Served], tmp_path: Path) -> None:
    assert cli.main(["serve", "--data-dir", str(tmp_path), "--port", "9444"]) == 0
    assert served[0].config.port == 9444


def test_remote_mode_prints_a_loud_banner_and_says_writes_are_off(
    served: list[Served], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["serve", "--data-dir", str(tmp_path), "--host", "192.0.2.7", "--allow-remote"]
    assert cli.main(argv) == 0
    assert capsys.readouterr().out == (
        f"Data directory: {tmp_path}\n"
        "Listening on http://192.0.2.7:8765\n"
        f"{STARS}\n"
        "* REMOTE MODE: NO AUTHENTICATION. Anyone who can reach this address can\n"
        "* use the app. Bound to http://192.0.2.7:8765; changes are DISABLED (read-only).\n"
        f"{STARS}\n"
        "Accepted Host headers: localhost, 127.0.0.1, [::1], 192.0.2.7\n"
        'Any other host in the URL gets "400 Invalid host header". To accept more, set\n'
        "SANKEY_ALLOWED_HOSTS to the JSON list of ALL accepted hosts, for example:\n"
        "  SANKEY_ALLOWED_HOSTS='"
        '["localhost", "127.0.0.1", "[::1]", "192.0.2.7", "192.168.1.5"]\'\n'
    )
    assert served[0].config.privileged_writes_allowed is False


def test_remote_writes_are_announced(
    served: list[Served], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["serve", "--data-dir", str(tmp_path), "--allow-remote", "--allow-remote-writes"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "NO AUTHENTICATION" in out
    assert "Bound to http://127.0.0.1:8765; changes are ENABLED." in out
    assert served[0].config.privileged_writes_allowed is True


class Shown(NamedTuple):
    host: str
    shown: str


@pytest.mark.parametrize(
    "case", [Shown("::1", "[::1]"), Shown("[::1]", "[::1]"), Shown("localhost", "localhost")]
)
def test_an_ipv6_address_is_shown_in_brackets(
    served: list[Served], tmp_path: Path, capsys: pytest.CaptureFixture[str], case: Shown
) -> None:
    assert cli.main(["serve", "--data-dir", str(tmp_path), "--host", case.host]) == 0
    assert f"Listening on http://{case.shown}:8765\n" in capsys.readouterr().out
    assert len(served) == 1


def test_a_configuration_error_prints_location_and_message_and_exits_2(
    served: list[Served], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["serve", "--data-dir", str(tmp_path), "--host", "192.0.2.7"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "sankey-studio: invalid configuration\n"
        "  config: Value error, a non-loopback host needs remote_mode (--allow-remote)\n"
    )
    assert served == []


def test_a_field_error_names_the_field(
    served: list[Served], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["serve", "--data-dir", str(tmp_path), "--port", "0"]) == 2
    assert capsys.readouterr().err == (
        "sankey-studio: invalid configuration\n  port: Input should be greater than or equal to 1\n"
    )
    assert served == []


def test_the_environment_uri_is_never_printed(
    served: list[Served],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SANKEY_MONGO_URI", "mongodb://admin:hunter2@db.invalid:27017/")
    assert cli.main(["serve", "--data-dir", str(tmp_path), "--port", "0"]) == 2
    captured = capsys.readouterr()
    assert "hunter2" not in captured.out + captured.err
    assert "Traceback" not in captured.err
    assert "mongodb" not in captured.err
    assert served == []


def test_run_server_starts_one_uvicorn_worker_with_a_concurrency_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    config = BootstrapConfig(data_dir=tmp_path, host="[::1]", port=9555, log_level="WARNING")
    app = FastAPI()
    cli._run_server(app, config)
    assert calls == [
        (
            (app,),
            {
                "host": "::1",
                "port": 9555,
                "workers": 1,
                "log_level": "warning",
                "limit_concurrency": 100,
                "proxy_headers": False,
                "server_header": False,
                "ws": "none",
            },
        )
    ]


def test_python_dash_m_runs_the_same_entry_point(
    served: list[Served], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["sankey-studio", "serve", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("sankey_studio", run_name="__main__")
    assert exit_info.value.code == 0
    assert len(served) == 1


def test_python_dash_m_passes_the_exit_status_on(
    served: list[Served], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["sankey-studio", "serve", "--port", "0"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("sankey_studio", run_name="__main__")
    assert exit_info.value.code == 2
    assert served == []
