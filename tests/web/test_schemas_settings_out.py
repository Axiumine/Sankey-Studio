"""``SettingsOut``: masked URIs, no field called ``uri``, the bootstrap block, read-only hiding."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.config import BootstrapConfig
from sankey_studio.models import AppSettings, StyleSpec
from sankey_studio.services import UpdateResult
from sankey_studio.storage import CopyReport, dump_settings
from sankey_studio.util import MASKED_URI, mask_uri
from sankey_studio.web.schemas import (
    ConnectionOut,
    CopyReportOut,
    SettingsIn,
    SettingsOut,
    SettingsSaved,
    bootstrap_out,
    connection_out,
    merge_settings,
    settings_out,
    settings_saved,
)
from tests.conftest import build_connection

if TYPE_CHECKING:
    from pathlib import Path

ALPHA = "mongodb://tester:hunter2@alpha.invalid:27017/?appName=tests"
BETA = "mongodb://beta-user:s3cret@beta.invalid/db?replicaSet=rs0"


class Modes(NamedTuple):
    """The three ways to run: loopback, remote read-only and remote with writes."""

    local: BootstrapConfig
    read_only: BootstrapConfig
    writable: BootstrapConfig


@pytest.fixture
def modes(tmp_path: Path) -> Modes:
    data = tmp_path / "data"
    return Modes(
        local=BootstrapConfig(data_dir=data),
        read_only=BootstrapConfig(data_dir=data, host="10.0.0.5", remote_mode=True),
        writable=BootstrapConfig(
            data_dir=data, host="10.0.0.5", remote_mode=True, remote_writes=True
        ),
    )


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(
        mongo_connections=[
            build_connection("alpha", ALPHA, "flows"),
            build_connection("beta", BETA, None),
        ],
        storage_backend="mongo",
        storage_connection="beta",
        storage_database="graphs_db",
        theme="dark",
        default_style=StyleSpec(title="Mine"),
        max_links=1234,
        max_drawn_links=777,
        max_upload_mb=7,
        mongo_timeout_ms=4000,
    )


def keys(value: Any) -> set[str]:
    """Every key of every dict inside ``value``."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys(item)}
    return set()


# --------------------------------------------------------------------------- the connections


def test_a_connection_is_returned_masked_with_has_secret(
    modes: Modes, settings: AppSettings
) -> None:
    out = settings_out(settings, modes.local)
    assert [c.model_dump() for c in out.mongo_connections] == [
        {
            "name": "alpha",
            "uri_masked": "mongodb://tester:***@alpha.invalid:27017/?appName=tests",
            "has_secret": True,
            "default_database": "flows",
        },
        {
            "name": "beta",
            "uri_masked": "mongodb://beta-user:***@beta.invalid/db?replicaSet=rs0",
            "has_secret": True,
            "default_database": None,
        },
    ]


def test_there_is_no_field_called_uri_and_no_secret_anywhere(
    modes: Modes, settings: AppSettings
) -> None:
    dumped = settings_out(settings, modes.local).model_dump(mode="json")
    assert "uri" not in keys(dumped)
    assert "uri" not in SettingsOut.model_fields
    assert set(ConnectionOut.model_fields) == {
        "name",
        "uri_masked",
        "has_secret",
        "default_database",
    }
    text = json.dumps(dumped)
    assert "hunter2" not in text
    assert "s3cret" not in text


def test_the_masked_uri_is_what_mask_uri_gives(modes: Modes, settings: AppSettings) -> None:
    out = settings_out(settings, modes.writable)
    assert [c.uri_masked for c in out.mongo_connections] == [mask_uri(ALPHA), mask_uri(BETA)]


def test_the_other_settings_pass_through(modes: Modes, settings: AppSettings) -> None:
    out = settings_out(settings, modes.local)
    expected = settings.model_dump(exclude={"mongo_connections"})
    assert out.model_dump(exclude={"mongo_connections", "bootstrap"}) == expected
    assert out.default_style.title == "Mine"
    assert (out.storage_backend, out.storage_connection, out.storage_database) == (
        "mongo",
        "beta",
        "graphs_db",
    )


def test_no_connections_is_an_empty_list(modes: Modes) -> None:
    assert settings_out(AppSettings(), modes.local).mongo_connections == []


# --------------------------------------------------------------------------- the bootstrap block


@pytest.mark.parametrize(
    ("mode", "remote", "writes"),
    [("local", False, True), ("read_only", True, False), ("writable", True, True)],
)
def test_the_bootstrap_block_reports_the_mode(
    modes: Modes, mode: str, remote: bool, writes: bool
) -> None:
    config: BootstrapConfig = getattr(modes, mode)
    block = bootstrap_out(config)
    assert block.model_dump() == {
        "sources_dir": str(config.effective_sources_dir),
        "graphs_dir": str(config.graphs_dir),
        "remote_mode": remote,
        "writes_allowed": writes,
    }
    assert settings_out(AppSettings(), config).bootstrap == block


def test_the_graphs_dir_shown_is_the_graphs_folder_of_the_data_dir(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path / "data", sources_dir=tmp_path / "elsewhere")
    assert bootstrap_out(config).graphs_dir == str(tmp_path / "data" / "graphs")


def test_the_sources_dir_shown_is_the_effective_one(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path / "data", sources_dir=tmp_path / "elsewhere")
    assert bootstrap_out(config).sources_dir == str(tmp_path / "elsewhere")
    default = BootstrapConfig(data_dir=tmp_path / "data")
    assert bootstrap_out(default).sources_dir == str(tmp_path / "data" / "sources")


# --------------------------------------------------------------------------- read-only mode


def test_remote_read_only_mode_hides_hosts_and_user_names(
    modes: Modes, settings: AppSettings
) -> None:
    out = settings_out(settings, modes.read_only)
    assert [c.uri_masked for c in out.mongo_connections] == [MASKED_URI, MASKED_URI]
    assert [(c.name, c.has_secret) for c in out.mongo_connections] == [
        ("alpha", True),
        ("beta", True),
    ]
    assert [c.default_database for c in out.mongo_connections] == ["flows", None]
    text = out.model_dump_json()
    for hidden in ("alpha.invalid", "beta.invalid", "tester", "beta-user", "appName", "replicaSet"):
        assert hidden not in text


@pytest.mark.parametrize("mode", ["local", "writable"])
def test_other_modes_show_the_masked_uri(modes: Modes, settings: AppSettings, mode: str) -> None:
    out = settings_out(settings, getattr(modes, mode))
    assert out.mongo_connections[0].uri_masked == mask_uri(ALPHA)


def test_connection_out_follows_the_flag() -> None:
    conn = build_connection("alpha", ALPHA, "flows")
    assert connection_out(conn, hide_hosts=False).uri_masked == mask_uri(ALPHA)
    assert connection_out(conn, hide_hosts=True).uri_masked == "mongodb://***"
    assert connection_out(conn, hide_hosts=True).has_secret is True


# --------------------------------------------------------------------------- round trips


@pytest.mark.parametrize("mode", ["local", "read_only", "writable"])
def test_a_get_answer_sent_back_keeps_every_secret(
    modes: Modes, settings: AppSettings, mode: str
) -> None:
    body = settings_out(settings, getattr(modes, mode)).model_dump(mode="json")
    merged = merge_settings(settings, SettingsIn.model_validate(body))
    assert dump_settings(merged) == dump_settings(settings)


def test_a_get_answer_is_a_valid_put_body_after_a_rename(
    modes: Modes, settings: AppSettings
) -> None:
    body = settings_out(settings, modes.local).model_dump(mode="json")
    body["mongo_connections"][0]["previous_name"] = "alpha"
    body["mongo_connections"][0]["name"] = "renamed"
    body["storage_connection"] = "beta"
    merged = merge_settings(settings, SettingsIn.model_validate(body))
    assert {c.name: c.uri.get_secret_value() for c in merged.mongo_connections} == {
        "renamed": ALPHA,
        "beta": BETA,
    }


# --------------------------------------------------------------------------- the PUT answer


def test_the_put_answer_carries_the_settings_and_no_report_without_a_copy(
    modes: Modes, settings: AppSettings
) -> None:
    saved = settings_saved(UpdateResult(settings), modes.local)
    assert isinstance(saved, SettingsSaved)
    assert saved.settings == settings_out(settings, modes.local)
    assert saved.copy_report is None
    assert saved.model_dump(mode="json")["copy_report"] is None


def test_the_put_answer_lists_the_copy_report(modes: Modes, settings: AppSettings) -> None:
    ids = ("a" * 32, "b" * 32)
    report = CopyReport(5, 2, 3, ids, folders=4, folders_skipped=1)
    saved = settings_saved(UpdateResult(settings, report), modes.local)
    assert isinstance(saved.copy_report, CopyReportOut)
    assert saved.copy_report.model_dump() == {
        "copied": 5,
        "skipped": 2,
        "unreadable": 3,
        "unreadable_ids": ["a" * 32, "b" * 32],
        "folders": 4,
        "folders_skipped": 1,
    }


def test_the_put_answer_has_no_secret_either(modes: Modes, settings: AppSettings) -> None:
    saved = settings_saved(UpdateResult(settings, CopyReport(1, 0)), modes.local)
    assert "uri" not in keys(saved.model_dump(mode="json"))
    assert "hunter2" not in saved.model_dump_json()
    assert saved.copy_report is not None
    assert saved.copy_report.unreadable_ids == []
