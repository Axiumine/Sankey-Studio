# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``main`` fails fast, with a short message and status 2, on a configuration that cannot run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NamedTuple

import pytest
from fastapi.testclient import TestClient

from sankey_studio import cli
from sankey_studio.cli import ServeArgs, build_config
from sankey_studio.web.app import InvalidConfigError

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from sankey_studio.config import BootstrapConfig

LEVELS: Final = "critical, error, warning, info, debug, trace"
HOSTS_MSG: Final = (
    "must be a bare host name or address: no scheme, port or path, a wildcard only as "
    "'*.example.com', an IPv6 address in brackets"
)
ENV_MSG: Final = (
    "a SANKEY_* environment value could not be parsed; list values such as "
    "SANKEY_ALLOWED_HOSTS must be a JSON array, for example "
    "SANKEY_ALLOWED_HOSTS='[\"192.168.1.5\"]'"
)
HEADER: Final = "sankey-studio: invalid configuration\n"
STARS: Final = "*" * 72
WILDCARD_V4: Final = "0.0.0.0"  # noqa: S104 - the wildcard bind under test


class Served(NamedTuple):
    app: FastAPI
    config: BootstrapConfig


class Result(NamedTuple):
    out: str
    err: str
    status: int


@dataclass
class Cli:
    """Runs ``main`` with a recording uvicorn seam, ``--data-dir`` in ``tmp_path``."""

    data_dir: Path
    monkeypatch: pytest.MonkeyPatch
    capsys: pytest.CaptureFixture[str]
    served: list[Served]

    def run(self, *options: str, **env: str) -> Result:
        for name, value in env.items():
            self.monkeypatch.setenv(f"SANKEY_{name.upper()}", value)
        status = cli.main(["serve", "--data-dir", str(self.data_dir), *options])
        captured = self.capsys.readouterr()
        return Result(captured.out, captured.err, status)


@pytest.fixture
def tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Cli:
    served: list[Served] = []
    monkeypatch.setattr(cli, "_run_server", lambda app, config: served.append(Served(app, config)))
    return Cli(tmp_path, monkeypatch, capsys, served)


# --------------------------------------------------------------------------- environment


@pytest.mark.parametrize("value", ["192.168.1.5", "a,b", "not-json-hunter2", "{"])
def test_an_unparsable_environment_value_exits_2_without_a_traceback(tool: Cli, value: str) -> None:
    result = tool.run(allowed_hosts=value)
    assert result == Result("", f"{HEADER}  environment: {ENV_MSG}\n", 2)
    assert tool.served == []


def test_the_environment_hint_works_when_followed(tool: Cli) -> None:
    assert tool.run(allowed_hosts='["localhost", "192.168.1.5"]').status == 0
    # the bound address is always accepted, whatever the list says
    assert tool.served[0].config.allowed_hosts == ["localhost", "192.168.1.5", "127.0.0.1"]


# --------------------------------------------------------------------------- log level


@pytest.mark.parametrize("level", ["banana", "", "warn", "verbose", "info "])
def test_an_unknown_log_level_exits_2_before_anything_is_printed_or_bound(
    tool: Cli, level: str
) -> None:
    result = tool.run(log_level=level)
    assert result == Result("", f"{HEADER}  log_level: must be one of {LEVELS}\n", 2)
    assert tool.served == []


@pytest.mark.parametrize(
    "level", ["critical", "error", "warning", "info", "debug", "trace", "INFO", "Debug"]
)
def test_every_uvicorn_log_level_is_accepted_in_any_case(tool: Cli, level: str) -> None:
    assert tool.run(log_level=level).status == 0
    assert tool.served[0].config.log_level == level


def test_build_config_raises_the_log_level_problem_for_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SANKEY_LOG_LEVEL", "banana")
    with pytest.raises(InvalidConfigError) as raised:
        build_config(ServeArgs(data_dir=tmp_path))
    assert (raised.value.where, raised.value.message) == ("log_level", f"must be one of {LEVELS}")


# --------------------------------------------------------------------------- allowed hosts


class BadHosts(NamedTuple):
    env: str
    where: str


BAD_HOSTS = [
    BadHosts('["foo*"]', "allowed_hosts[0]"),
    BadHosts('["localhost", "*foo"]', "allowed_hosts[1]"),
    BadHosts('["a", "b", "http://192.168.1.5"]', "allowed_hosts[2]"),
    BadHosts('["192.168.1.5:8765"]', "allowed_hosts[0]"),
    BadHosts('[""]', "allowed_hosts[0]"),
]


@pytest.mark.parametrize("case", BAD_HOSTS, ids=lambda c: c.env)
def test_an_unusable_allowed_hosts_entry_exits_2_naming_its_position(
    tool: Cli, case: BadHosts
) -> None:
    result = tool.run(allowed_hosts=case.env)
    assert result == Result("", f"{HEADER}  {case.where}: {HOSTS_MSG}\n", 2)
    assert tool.served == []


def test_a_rejected_host_entry_is_never_echoed(tool: Cli) -> None:
    result = tool.run(allowed_hosts='["hunter2*"]')
    assert result.status == 2
    assert "hunter2" not in result.out + result.err
    assert tool.served == []


# --------------------------------------------------------------------------- the banner


class Wild(NamedTuple):
    host: str
    accepted: list[str]


LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
#: ``BootstrapConfig`` auto-allows a bound address, except wildcards: ``0.0.0.0`` is not a ``Host``.
WILDCARDS = [
    Wild(WILDCARD_V4, LOCAL_HOSTS),
    Wild("::", LOCAL_HOSTS),
    Wild("[::]", LOCAL_HOSTS),
    Wild("[0.0.0.0]", LOCAL_HOSTS),
    Wild("0:0:0:0:0:0:0:0", LOCAL_HOSTS),
    Wild("::ffff:0.0.0.0", LOCAL_HOSTS),
]


@pytest.mark.parametrize("case", WILDCARDS, ids=lambda c: c.host)
def test_a_wildcard_bind_names_no_url_and_says_how_to_allow_hosts(tool: Cli, case: Wild) -> None:
    result = tool.run("--host", case.host, "--allow-remote", "--port", "9100")
    example = json.dumps([*case.accepted, "192.168.1.5"])
    assert result.status == 0
    assert result.out == (
        f"Data directory: {tool.data_dir}\n"
        "Listening on all interfaces, port 9100\n"
        f"{STARS}\n"
        "* REMOTE MODE: NO AUTHENTICATION. Anyone who can reach this address can\n"
        "* use the app. Bound to all interfaces, port 9100; changes are DISABLED (read-only).\n"
        f"{STARS}\n"
        "source writes: DISABLED\n"
        f"Accepted Host headers: {', '.join(case.accepted)}\n"
        'Any other host in the URL gets "400 Invalid host header". To accept more, set\n'
        "SANKEY_ALLOWED_HOSTS to the JSON list of ALL accepted hosts, for example:\n"
        f"  SANKEY_ALLOWED_HOSTS='{example}'\n"
    )
    assert len(tool.served) == 1


def test_the_wildcard_bind_answers_its_accepted_hosts_and_refuses_the_old_banner_address(
    tool: Cli,
) -> None:
    assert tool.run("--host", WILDCARD_V4, "--allow-remote").status == 0
    app = tool.served[0].app
    with TestClient(app, base_url="http://localhost:8765") as accepted:
        assert accepted.get("/nope").status_code == 404
    with TestClient(app, base_url=f"http://{WILDCARD_V4}:8765") as refused:
        response = refused.get("/nope")
    assert (response.status_code, response.text) == (400, "Invalid host header")


def test_a_star_in_allowed_hosts_is_announced_as_any_host(tool: Cli) -> None:
    result = tool.run("--host", "192.0.2.7", "--allow-remote", allowed_hosts='["*"]')
    assert result.status == 0
    tail = (
        f"{STARS}\nsource writes: DISABLED\n"
        "Accepted Host headers: any (allowed_hosts contains '*')\n"
    )
    assert result.out.endswith(tail)
    assert len(tool.served) == 1


def test_a_local_start_does_not_print_the_host_hint(tool: Cli) -> None:
    result = tool.run()
    assert result.out == (f"Data directory: {tool.data_dir}\nListening on http://127.0.0.1:8765\n")
    assert len(tool.served) == 1


def remote_banner(data_dir: Path, address: str, accepted: list[str], example: list[str]) -> str:
    """The whole output of a read-only remote start bound to the URL ``address``."""
    return (
        f"Data directory: {data_dir}\n"
        f"Listening on {address}\n"
        f"{STARS}\n"
        "* REMOTE MODE: NO AUTHENTICATION. Anyone who can reach this address can\n"
        f"* use the app. Bound to {address}; changes are DISABLED (read-only).\n"
        f"{STARS}\n"
        "source writes: DISABLED\n"
        f"Accepted Host headers: {', '.join(accepted)}\n"
        'Any other host in the URL gets "400 Invalid host header". To accept more, set\n'
        "SANKEY_ALLOWED_HOSTS to the JSON list of ALL accepted hosts, for example:\n"
        f"  SANKEY_ALLOWED_HOSTS='{json.dumps(example)}'\n"
    )


def host_status(app: FastAPI, host: str) -> int:
    """Status of a request to an unknown path that carries ``Host: host``: 404 = host accepted."""
    with TestClient(app) as client:
        return client.get("/nope", headers={"Host": host}).status_code


# --------------------------------------------------------------------------- IPv6 binds


@pytest.mark.parametrize("host", ["2001:db8::1", "[2001:db8::1]"])
def test_a_bare_or_bracketed_ipv6_bind_starts_and_answers_its_bracketed_host(
    tool: Cli, host: str
) -> None:
    result = tool.run("--host", host, "--allow-remote")
    accepted = [*LOCAL_HOSTS, "[2001:db8::1]"]
    assert result == Result(
        remote_banner(
            tool.data_dir,
            "http://[2001:db8::1]:8765",
            accepted,
            [*accepted, "192.168.1.5"],
        ),
        "",
        0,
    )
    app = tool.served[0].app
    assert tool.served[0].config.allowed_hosts == accepted
    assert host_status(app, "[2001:db8::1]:8765") == 404
    assert host_status(app, "[2001:DB8::1]:8765") == 404
    assert host_status(app, "[2001:db8::2]:8765") == 400


def test_an_ipv6_bind_is_also_accepted_in_the_canonical_form_a_browser_sends(tool: Cli) -> None:
    assert tool.run("--host", "2001:DB8:0:0:0:0:0:1", "--allow-remote").status == 0
    config = tool.served[0].config
    assert config.allowed_hosts == [*LOCAL_HOSTS, "[2001:db8:0:0:0:0:0:1]", "[2001:db8::1]"]
    assert host_status(tool.served[0].app, "[2001:db8::1]:8765") == 404


# --------------------------------------------------------------------------- loopback binds


class Bound(NamedTuple):
    host: str
    shown: str
    accepted: list[str]


LOOPBACKS = [
    Bound("127.0.0.2", "127.0.0.2", ["127.0.0.2:8765", "127.0.0.2"]),
    Bound("127.255.255.254", "127.255.255.254", ["127.255.255.254:8765"]),
    Bound("::ffff:127.0.0.1", "[::ffff:127.0.0.1]", ["[::ffff:127.0.0.1]:8765"]),
    Bound("0:0:0:0:0:0:0:1", "[0:0:0:0:0:0:0:1]", ["[0:0:0:0:0:0:0:1]:8765", "[::1]:8765"]),
]


@pytest.mark.parametrize("case", LOOPBACKS, ids=lambda c: c.host)
def test_any_loopback_bind_answers_the_host_its_banner_names(tool: Cli, case: Bound) -> None:
    result = tool.run("--host", case.host)
    assert result == Result(
        f"Data directory: {tool.data_dir}\nListening on http://{case.shown}:8765\n", "", 0
    )
    app = tool.served[0].app
    for accepted in case.accepted:
        assert host_status(app, accepted) == 404
    assert host_status(app, "127.0.0.3:8765") == 400


def test_a_loopback_bind_stays_accepted_next_to_a_custom_host_list(tool: Cli) -> None:
    assert tool.run("--host", "127.0.0.2", allowed_hosts='["files.local"]').status == 0
    assert tool.served[0].config.allowed_hosts == ["files.local", "127.0.0.2"]
    assert host_status(tool.served[0].app, "127.0.0.2:8765") == 404


# --------------------------------------------------------------------------- the example


def test_the_example_does_not_repeat_the_bound_host(tool: Cli) -> None:
    result = tool.run("--host", "192.168.1.5", "--allow-remote")
    accepted = [*LOCAL_HOSTS, "192.168.1.5"]
    assert result == Result(
        remote_banner(tool.data_dir, "http://192.168.1.5:8765", accepted, accepted), "", 0
    )
    assert '"192.168.1.5", "192.168.1.5"' not in result.out


def test_the_example_does_not_repeat_a_listed_host(tool: Cli) -> None:
    result = tool.run("--host", "10.0.0.5", "--allow-remote", allowed_hosts='["192.168.1.5"]')
    accepted = ["192.168.1.5", "10.0.0.5"]
    assert result == Result(
        remote_banner(tool.data_dir, "http://10.0.0.5:8765", accepted, accepted), "", 0
    )


# --------------------------------------------------------------------------- the seed URI

SECRET: Final = "hunter2"
SEED_PREFIX: Final = f"mongodb://admin:{SECRET}@db.invalid"


class BadSeed(NamedTuple):
    uri: str
    reason: str


BAD_SEEDS = [
    BadSeed(f"{SEED_PREFIX}/?tlsInsecure=true", "uri option 'tlsInsecure' is not allowed"),
    BadSeed(f"{SEED_PREFIX}/?tlsCAFile=/etc/{SECRET}", "uri option 'tlsCAFile' is not allowed"),
    BadSeed(f"{SEED_PREFIX}/?authMechanism=GSSAPI", "uri option 'authMechanism' is not allowed"),
    BadSeed(
        f"http://admin:{SECRET}@db.invalid/", "uri must start with mongodb:// or mongodb+srv://"
    ),
    BadSeed("", "uri must start with mongodb:// or mongodb+srv://"),
    BadSeed(f"{SEED_PREFIX}:{SECRET}/", "uri is not a valid MongoDB connection string"),
    BadSeed("**********", "uri is a masked placeholder; enter the real connection string"),
]


@pytest.mark.parametrize("case", BAD_SEEDS, ids=lambda c: c.reason)
def test_a_seed_uri_the_settings_would_refuse_exits_2_before_serving(
    tool: Cli, case: BadSeed
) -> None:
    result = tool.run(mongo_uri=case.uri)
    assert result == Result("", f"{HEADER}  mongo_uri: {case.reason}\n", 2)
    assert tool.served == []


@pytest.mark.parametrize("case", BAD_SEEDS[:-1], ids=lambda c: c.reason)
def test_a_refused_seed_uri_never_reaches_the_console(tool: Cli, case: BadSeed) -> None:
    result = tool.run(mongo_uri=case.uri)
    shown = result.out + result.err
    assert SECRET not in shown
    assert "db.invalid" not in shown
    assert "Traceback" not in shown


def test_a_good_seed_uri_starts_without_being_printed(tool: Cli) -> None:
    result = tool.run(mongo_uri=f"{SEED_PREFIX}:27017/")
    assert result == Result(
        f"Data directory: {tool.data_dir}\nListening on http://127.0.0.1:8765\n", "", 0
    )
    assert len(tool.served) == 1


def test_no_seed_uri_is_not_checked(tool: Cli) -> None:
    assert tool.run().status == 0
    assert tool.served[0].config.mongo_uri is None


def test_build_config_raises_the_seed_problem_for_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SANKEY_MONGO_URI", f"{SEED_PREFIX}/?tlsInsecure=true")
    with pytest.raises(InvalidConfigError) as raised:
        build_config(ServeArgs(data_dir=tmp_path))
    assert (raised.value.where, raised.value.message) == (
        "mongo_uri",
        "uri option 'tlsInsecure' is not allowed",
    )
    assert SECRET not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
