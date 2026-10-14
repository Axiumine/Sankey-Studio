"""``errors`` (codes, statuses, details) and ``config`` (data dir, loopback, messages)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from sankey_studio import errors
from sankey_studio.config import BootstrapConfig, _is_loopback, default_data_dir

if TYPE_CHECKING:
    from pathlib import Path

# class name -> (HTTP status, stable code): the table API clients and the web layer rely on
ERROR_TABLE = {
    "SankeyError": (400, "sankey_error"),
    "SourceError": (422, "source_error"),
    "SourceNotFoundError": (404, "source_not_found"),
    "UnsafeSourceError": (400, "unsafe_source"),
    "GraphBuildError": (422, "graph_build_error"),
    "NoCategoriesError": (422, "no_categories"),
    "GraphTooLargeError": (413, "graph_too_large"),
    "NotFoundError": (404, "not_found"),
    "ConflictError": (409, "conflict"),
    "StorageError": (503, "storage_error"),
    "SettingsError": (422, "settings_error"),
    "BundleError": (422, "bundle_error"),
    "BusyError": (503, "busy"),
    "FolderRuleError": (422, "folder_rule"),
    "FolderNameTakenError": (409, "folder_name_taken"),
    "SourceEditRefused": (422, "source_edit_refused"),
    "SourceWriteError": (502, "source_write_failed"),
    "ExportUnavailableError": (501, "export_unavailable"),
    "ExportBusyError": (503, "export_busy"),
    "ExportTooLargeError": (422, "export_too_large"),
    "ExportFailedError": (502, "export_failed"),
    "ExportTimeoutError": (504, "export_timeout"),
    "ForbiddenError": (403, "forbidden"),
    "ReadOnlyModeError": (403, "read_only_mode"),
    "UnsupportedMediaTypeError": (415, "unsupported_media_type"),
    "PayloadTooLargeError": (413, "payload_too_large"),
}


@pytest.mark.parametrize("name", sorted(ERROR_TABLE))
def test_status_and_code_of_every_error(name: str) -> None:
    cls = getattr(errors, name)
    assert (cls.status_code, cls.code) == ERROR_TABLE[name]
    assert issubclass(cls, errors.SankeyError)


def test_every_error_class_is_in_the_table() -> None:
    declared = {
        name
        for name, obj in vars(errors).items()
        if isinstance(obj, type) and issubclass(obj, errors.SankeyError)
    }
    assert declared == set(ERROR_TABLE)


def test_error_message_and_details() -> None:
    plain = errors.SourceError("boom")
    assert (str(plain), plain.message, plain.details) == ("boom", "boom", [])
    with_details = errors.SourceError("boom", details=["a", "b"])
    assert with_details.details == ["a", "b"]
    assert errors.SourceError("x", details=[]).details == []


def test_conflict_error_carries_the_current_state() -> None:
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    err = errors.ConflictError("moved", current_revision=7, current_updated_at=when)
    assert str(err) == err.message == "moved"
    assert err.current_revision == 7
    assert err.current_updated_at is when
    assert err.details == ["revision=7", f"updated_at={when.isoformat()}"]


def test_conflict_error_keeps_caller_details_first_and_does_not_alias_them() -> None:
    given = ["note"]
    err = errors.ConflictError("moved", current_revision=2, details=given)
    assert err.details == ["note", "revision=2"]
    assert given == ["note"]
    bare = errors.ConflictError("moved")
    assert (bare.details, bare.current_revision, bare.current_updated_at) == ([], None, None)
    zero = errors.ConflictError("moved", current_revision=0)
    assert zero.details == ["revision=0"]


# --------------------------------------------------------------------------- config


def test_default_data_dir_follows_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_data_dir() == tmp_path / "xdg" / "sankey-studio"


@pytest.mark.parametrize("xdg", [None, ""])
def test_default_data_dir_falls_back_to_the_home_share_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, xdg: str | None
) -> None:
    if xdg is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", xdg)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_data_dir() == tmp_path / ".local" / "share" / "sankey-studio"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("[::1]", True),
        ("[0:0:0:0:0:0:0:1]", True),
        ("0:0:0:0:0:0:0:1", True),
        ("127.0.0.2", True),
        ("::ffff:127.0.0.1", True),
        ("0.0.0.0", False),  # noqa: S104 - wildcard bind under test
        ("::", False),
        ("10.0.0.1", False),
        ("[2001:db8::1]", False),
        ("example.com", False),
        ("LOCALHOST", False),
        ("[]", False),
        ("", False),
    ],
)
def test_is_loopback_table(host: str, expected: bool) -> None:
    assert _is_loopback(host) is expected


def messages_of(**kwargs: object) -> list[str]:
    with pytest.raises(ValidationError) as info:
        BootstrapConfig(**kwargs)  # type: ignore[arg-type]
    return [e["msg"] for e in info.value.errors(include_input=False)]


def test_guard_messages_are_exact() -> None:
    assert messages_of(host="10.0.0.1") == [
        "Value error, a non-loopback host needs remote_mode (--allow-remote)"
    ]
    assert messages_of(remote_writes=True) == [
        "Value error, remote_writes needs remote_mode (--allow-remote)"
    ]
    assert messages_of(allowed_hosts=["*"]) == [
        "Value error, allowed_hosts may only contain '*' in remote_mode"
    ]


def test_sources_dir_messages_are_exact(tmp_path: Path) -> None:
    data = tmp_path / "data"
    overlap = (
        "Value error, sources_dir must not equal or contain data_dir, graphs/ or settings.json"
    )
    for candidate in (data, tmp_path, data / "graphs"):
        assert messages_of(data_dir=data, sources_dir=candidate) == [overlap]
    assert messages_of(data_dir=data, sources_dir=data / "graphs" / "inbox") == [
        "Value error, sources_dir must not be inside graphs/"
    ]


def test_remote_mode_adds_a_named_bind_host_to_the_allowed_hosts(tmp_path: Path) -> None:
    named = BootstrapConfig(data_dir=tmp_path, host="10.0.0.5", remote_mode=True)
    assert named.allowed_hosts == ["localhost", "127.0.0.1", "[::1]", "10.0.0.5"]
    wildcard = BootstrapConfig(data_dir=tmp_path, host="0.0.0.0", remote_mode=True)  # noqa: S104 - wildcard bind under test
    assert wildcard.allowed_hosts == ["localhost", "127.0.0.1", "[::1]"]
    listed = BootstrapConfig(
        data_dir=tmp_path, host="10.0.0.5", remote_mode=True, allowed_hosts=["10.0.0.5"]
    )
    assert listed.allowed_hosts == ["10.0.0.5"]
    local = BootstrapConfig(data_dir=tmp_path, remote_mode=True)
    assert local.allowed_hosts == ["localhost", "127.0.0.1", "[::1]"]


def test_derived_paths_and_flags(tmp_path: Path) -> None:
    config = BootstrapConfig(data_dir=tmp_path)
    assert config.settings_file == tmp_path / "settings.json"
    assert config.graphs_dir == tmp_path / "graphs"
    assert config.default_sources_dir == tmp_path / "sources"
    assert config.effective_sources_dir == tmp_path / "sources"
    assert config.is_loopback is True
    custom = BootstrapConfig(data_dir=tmp_path / "d", sources_dir=tmp_path / "s")
    assert custom.effective_sources_dir == tmp_path / "s"
    assert custom.default_sources_dir == tmp_path / "d" / "sources"


@pytest.mark.parametrize(
    ("remote_mode", "remote_writes", "allowed"),
    [(False, False, True), (True, False, False), (True, True, True)],
)
def test_privileged_writes_flag(remote_mode: bool, remote_writes: bool, allowed: bool) -> None:
    config = BootstrapConfig(
        host="10.0.0.5" if remote_mode else "127.0.0.1",
        remote_mode=remote_mode,
        remote_writes=remote_writes,
    )
    assert config.privileged_writes_allowed is allowed


@pytest.mark.parametrize("port", [1, 65535])
def test_port_limits_accept_the_edges(port: int) -> None:
    assert BootstrapConfig(port=port).port == port


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_port_limits_refuse_the_outside(port: int) -> None:
    with pytest.raises(ValidationError):
        BootstrapConfig(port=port)
