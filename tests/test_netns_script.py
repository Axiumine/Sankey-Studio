# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``scripts/netns.sh``: the e2e suites run where no docker interface of another project is seen.

Chrome aborts its requests in flight with ``net::ERR_NETWORK_CHANGED`` whenever an interface of
the machine comes or goes. The script runs the command in a network namespace with a working
loopback and nothing else; where no namespace can be made it runs the command in the host network
and says so, which these tests reach by hiding ``unshare``.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.githook_support import REPO_ROOT
from tests.test_githook_gate_wiring import make_dry_run

if TYPE_CHECKING:
    from pathlib import Path

SCRIPT = REPO_ROOT / "scripts" / "netns.sh"
BASH = shutil.which("bash") or "/bin/bash"
FALLBACK = "netns.sh: no private network namespace here; running in the host network"
INTERFACES = "import socket; print(*sorted(name for _, name in socket.if_nameindex()))"
LOOPBACK = (
    "import socket\n"
    "server = socket.create_server(('127.0.0.1', 0))\n"
    "socket.create_connection(server.getsockname()).close()\n"
    "print('connected')\n"
)
NO_LEAK = "import os; print(os.environ.get('SANKEY_NETNS', 'unset'))"
FIRST_ARGUMENT = "import sys; print(sys.argv[1])"


def run(
    code: str, *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """The script around ``python -c CODE ARGUMENTS`` (absolute interpreter: PATH may be empty)."""
    return subprocess.run(  # noqa: S603 - fixed argv, a throw-away namespace
        [BASH, str(SCRIPT), sys.executable, "-c", code, *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=env,
    )


def host_interfaces() -> list[str]:
    return sorted(name for _, name in socket.if_nameindex())


def without_unshare(tmp_path: Path) -> dict[str, str]:
    """An environment whose PATH holds nothing: ``unshare`` and ``ip`` cannot be found."""
    return {"PATH": str(tmp_path)}


def test_the_command_sees_the_loopback_only_or_else_the_host_interfaces() -> None:
    done = run(INTERFACES)
    private = FALLBACK not in done.stderr
    assert done.returncode == 0
    assert done.stdout.split() == (["lo"] if private else host_interfaces())


def test_the_loopback_of_the_namespace_is_up() -> None:
    done = run(LOOPBACK)
    assert (done.returncode, done.stdout.strip()) == (0, "connected")


def test_the_exit_status_of_the_command_is_the_exit_status_of_the_script() -> None:
    assert run("import sys; sys.exit(7)").returncode == 7


def test_an_argument_with_a_space_stays_one_argument() -> None:
    assert run(FIRST_ARGUMENT, "a  b").stdout == "a  b\n"


def test_the_marker_of_the_script_does_not_reach_the_command() -> None:
    assert run(NO_LEAK).stdout == "unset\n"


def test_without_unshare_the_command_runs_in_the_host_network_and_the_script_says_so(
    tmp_path: Path,
) -> None:
    done = run(INTERFACES, env=without_unshare(tmp_path))
    assert done.returncode == 0
    assert done.stderr.strip() == FALLBACK
    assert done.stdout.split() == host_interfaces()


def test_without_unshare_the_exit_status_and_the_marker_are_the_same(tmp_path: Path) -> None:
    env = without_unshare(tmp_path)
    assert run("import sys; sys.exit(3)", env=env).returncode == 3
    assert run(NO_LEAK, env=env).stdout == "unset\n"


@pytest.mark.parametrize("target", ["e2e-shard-1", "e2e-shard-5", "e2e-serial"])
def test_the_offline_e2e_targets_run_through_the_script(target: str) -> None:
    assert "scripts/netns.sh uv run pytest tests/e2e " in make_dry_run(target)


@pytest.mark.parametrize("target", ["e2e-mongo", "e2e-mongo-rs"])
def test_the_real_mongodb_targets_keep_the_host_network(target: str) -> None:
    assert "netns.sh" not in make_dry_run(target)
