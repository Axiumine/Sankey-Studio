"""``create_app`` refuses an ``allowed_hosts`` entry that could only fail at the first request."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sankey_studio.config import BootstrapConfig
from sankey_studio.services import Services
from sankey_studio.web import app as app_module
from sankey_studio.web.app import InvalidConfigError, check_allowed_hosts, create_app
from sankey_studio.web.security import MSG_HOST_PATTERN, host_pattern_problem
from tests.web.ids import stable_id

if TYPE_CHECKING:
    from pathlib import Path

VALID = [
    "localhost",
    "127.0.0.1",
    "[::1]",
    "[fe80::1]",
    "192.168.1.5",
    "my-host_1.local",
    "*.example.com",
    "*",
    "MixedCase.Example",
]
INVALID = [
    "",
    "foo*",
    "*foo",
    "a*b",
    "*.*.x",
    "**",
    "*.",
    "http://192.168.1.5",
    "192.168.1.5:8765",
    "localhost:80",
    "::1",
    "[::1",
    "[]",
    "a b",
    " localhost",
    "host/path",
    "user@host",
    "ho\nst",
]


@pytest.mark.parametrize("pattern", VALID)
def test_a_usable_pattern_has_no_problem(pattern: str) -> None:
    assert host_pattern_problem(pattern) is None


@pytest.mark.parametrize("pattern", INVALID, ids=stable_id)
def test_an_unusable_pattern_is_explained(pattern: str) -> None:
    assert host_pattern_problem(pattern) == MSG_HOST_PATTERN


@pytest.mark.parametrize("pattern", ["foo*", "*foo", "a*b", "*.*.x", "**"])
def test_every_pattern_starlette_asserts_on_is_refused_here_first(pattern: str) -> None:
    async def app(*_args: Any) -> None:
        return None

    with pytest.raises(AssertionError):
        TrustedHostMiddleware(app, allowed_hosts=[pattern])
    assert host_pattern_problem(pattern) == MSG_HOST_PATTERN


def test_check_allowed_hosts_names_the_first_bad_entry() -> None:
    with pytest.raises(InvalidConfigError) as raised:
        check_allowed_hosts(["localhost", "ok.example", "bad*", "worse*"])
    assert (raised.value.where, raised.value.message) == ("allowed_hosts[2]", MSG_HOST_PATTERN)
    assert str(raised.value) == f"allowed_hosts[2]: {MSG_HOST_PATTERN}"
    assert isinstance(raised.value, ValueError)


def test_check_allowed_hosts_accepts_an_empty_or_valid_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    examined: list[str] = []

    def spy(pattern: str) -> str | None:
        examined.append(pattern)
        return host_pattern_problem(pattern)

    monkeypatch.setattr(app_module, "host_pattern_problem", spy)
    check_allowed_hosts([])
    assert examined == []
    check_allowed_hosts(VALID)  # raises on a bad entry
    assert examined == VALID


@pytest.mark.parametrize(
    "host",
    [
        "10.0.0.5",
        "files.example",
        "2001:db8::1",
        "[2001:db8::1]",
        "FE80::1",
        "2001:DB8:0:0:0:0:0:1",
        "::ffff:127.0.0.1",
        "0:0:0:0:0:0:0:1",
        "127.0.0.2",
    ],
)
def test_a_bound_address_is_always_an_entry_create_app_accepts(tmp_path: Path, host: str) -> None:
    config = BootstrapConfig(data_dir=tmp_path / "data", host=host, remote_mode=True)
    app = create_app(config, services=Services.create(config))  # checks every entry first
    assert app.state.config is config


@pytest.mark.parametrize("hosts", [["foo*"], ["localhost", "*bad"], ["http://x"]])
def test_create_app_refuses_a_bad_entry_before_building_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hosts: list[str]
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError

    monkeypatch.setattr(Services, "create", forbidden)
    config = BootstrapConfig(data_dir=tmp_path / "data", allowed_hosts=hosts)
    with pytest.raises(InvalidConfigError, match=r"^allowed_hosts\[\d\]: "):
        create_app(config)
    assert not (tmp_path / "data").exists()


def test_create_app_accepts_the_star_in_remote_mode(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path, allowed_hosts=["*"], remote_mode=True)
    app = create_app(config, services=Services.create(config))
    assert app.state.config is config
