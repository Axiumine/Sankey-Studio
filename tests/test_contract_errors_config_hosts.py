"""``config``: which bind addresses are wildcards and how a bound address is allowed as a Host."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.config import BootstrapConfig, _host_entries, is_wildcard

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
WILDCARDS = [
    "0.0.0.0",  # noqa: S104 - wildcard bind under test
    "::",
    "",
    "[::]",
    "[0.0.0.0]",
    "[]",
    "0:0:0:0:0:0:0:0",
    "[0:0:0:0:0:0:0:0]",
    "0::0",
    "::ffff:0.0.0.0",
]
NOT_WILDCARDS = [
    "127.0.0.1",
    "localhost",
    "::1",
    "[::1]",
    "0.0.0.1",
    "::2",
    "10.0.0.5",
    "2001:db8::1",
    "[2001:db8::1]",
    "::ffff:127.0.0.1",
    "example.com",
    "[example.com]",
    " ",
]


@pytest.mark.parametrize("host", WILDCARDS)
def test_every_spelling_of_the_any_address_is_a_wildcard(host: str) -> None:
    assert is_wildcard(host) is True


@pytest.mark.parametrize("host", NOT_WILDCARDS)
def test_a_named_address_is_not_a_wildcard(host: str) -> None:
    assert is_wildcard(host) is False


class Entries(NamedTuple):
    host: str
    entries: list[str]


ENTRIES = [
    Entries("localhost", ["localhost"]),
    Entries("MyHost.Example", ["MyHost.Example"]),
    Entries("10.0.0.5", ["10.0.0.5"]),
    Entries("127.0.0.2", ["127.0.0.2"]),
    Entries("[example]", ["[example]"]),
    Entries("2001:db8::1", ["[2001:db8::1]"]),
    Entries("[2001:db8::1]", ["[2001:db8::1]"]),
    Entries("FE80::1", ["[fe80::1]"]),
    Entries("[FE80::1]", ["[fe80::1]"]),
    Entries("2001:DB8:0:0:0:0:0:1", ["[2001:db8:0:0:0:0:0:1]", "[2001:db8::1]"]),
    Entries("0:0:0:0:0:0:0:1", ["[0:0:0:0:0:0:0:1]", "[::1]"]),
    Entries("::ffff:127.0.0.1", ["[::ffff:127.0.0.1]"]),
]


@pytest.mark.parametrize("case", ENTRIES, ids=lambda c: c.host)
def test_a_bound_host_is_listed_as_a_host_header_spells_it(case: Entries) -> None:
    assert _host_entries(case.host) == case.entries


class Listed(NamedTuple):
    options: dict[str, Any]
    allowed: list[str]


LISTED = [
    # remote: the named or IP address is added, IPv6 in brackets
    Listed({"host": "10.0.0.5"}, [*DEFAULT_HOSTS, "10.0.0.5"]),
    Listed({"host": "2001:db8::1"}, [*DEFAULT_HOSTS, "[2001:db8::1]"]),
    Listed({"host": "[2001:db8::1]"}, [*DEFAULT_HOSTS, "[2001:db8::1]"]),
    Listed({"host": "FE80::1"}, [*DEFAULT_HOSTS, "[fe80::1]"]),
    Listed(
        {"host": "2001:DB8:0:0:0:0:0:1"},
        [*DEFAULT_HOSTS, "[2001:db8:0:0:0:0:0:1]", "[2001:db8::1]"],
    ),
    Listed({"host": "files.example"}, [*DEFAULT_HOSTS, "files.example"]),
    # remote: nothing is added twice, in any letter case
    Listed({"host": "files.example", "allowed_hosts": ["FILES.example"]}, ["FILES.example"]),
    Listed({"host": "2001:db8::1", "allowed_hosts": ["[2001:DB8::1]"]}, ["[2001:DB8::1]"]),
    Listed(
        {"host": "2001:DB8:0:0:0:0:0:1", "allowed_hosts": ["[2001:db8::1]"]},
        ["[2001:db8::1]", "[2001:db8:0:0:0:0:0:1]"],
    ),
    # remote: a wildcard bind adds nothing
    Listed({"host": "0.0.0.0"}, DEFAULT_HOSTS),  # noqa: S104 - wildcard bind under test
    Listed({"host": "::"}, DEFAULT_HOSTS),
    Listed({"host": "[::]"}, DEFAULT_HOSTS),
    Listed({"host": "0:0:0:0:0:0:0:0"}, DEFAULT_HOSTS),
    Listed({"host": "::ffff:0.0.0.0"}, DEFAULT_HOSTS),
    Listed({"host": ""}, DEFAULT_HOSTS),
]


@pytest.mark.parametrize("case", LISTED, ids=lambda c: str(c.options))
def test_a_remote_bind_is_added_to_the_allowed_hosts_once(tmp_path: Path, case: Listed) -> None:
    config = BootstrapConfig(data_dir=tmp_path, remote_mode=True, **case.options)
    assert config.allowed_hosts == case.allowed


LOCAL = [
    # a loopback bind outside the defaults is accepted without remote mode
    Listed({"host": "127.0.0.2"}, [*DEFAULT_HOSTS, "127.0.0.2"]),
    Listed({"host": "127.255.255.254"}, [*DEFAULT_HOSTS, "127.255.255.254"]),
    Listed({"host": "::ffff:127.0.0.1"}, [*DEFAULT_HOSTS, "[::ffff:127.0.0.1]"]),
    Listed({"host": "0:0:0:0:0:0:0:1"}, [*DEFAULT_HOSTS, "[0:0:0:0:0:0:0:1]"]),
    Listed({"host": "[0:0:0:0:0:0:0:1]"}, [*DEFAULT_HOSTS, "[0:0:0:0:0:0:0:1]"]),
    # the defaults stay as they are
    Listed({}, DEFAULT_HOSTS),
    Listed({"host": "127.0.0.1"}, DEFAULT_HOSTS),
    Listed({"host": "localhost"}, DEFAULT_HOSTS),
    Listed({"host": "::1"}, DEFAULT_HOSTS),
    Listed({"host": "[::1]"}, DEFAULT_HOSTS),
    # an explicit list keeps its order; the bound address follows it
    Listed({"allowed_hosts": ["files.example"]}, ["files.example", "127.0.0.1"]),
    Listed({"host": "localhost", "allowed_hosts": ["LOCALHOST"]}, ["LOCALHOST"]),
    Listed(
        {"host": "127.0.0.2", "allowed_hosts": ["files.example"]}, ["files.example", "127.0.0.2"]
    ),
]


@pytest.mark.parametrize("case", LOCAL, ids=lambda c: str(c.options))
def test_a_loopback_bind_is_allowed_without_remote_mode(tmp_path: Path, case: Listed) -> None:
    config = BootstrapConfig(data_dir=tmp_path, **case.options)
    assert config.allowed_hosts == case.allowed
    assert config.remote_mode is False
