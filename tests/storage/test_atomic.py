# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``storage.atomic``: atomic writes, nofollow reads, private directories."""

from __future__ import annotations

import errno
import logging
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.storage import atomic
from sankey_studio.storage.atomic import (
    UnsafeDirectoryError,
    check_writable,
    ensure_private_dir,
    fsync_dir,
    os_reason,
    read_file_nofollow,
    write_atomic,
)
from tests.storage.support import mode_of, umask

if TYPE_CHECKING:
    from collections.abc import Callable


def _hidden(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.startswith("."))


# --------------------------------------------------------------------------- write_atomic


@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
def test_written_files_are_0600_whatever_the_umask(tmp_path: Path, mask: int) -> None:
    target = tmp_path / "f.json"
    with umask(mask):
        write_atomic(target, b"hello")
    assert target.read_bytes() == b"hello"
    assert mode_of(target) == 0o600


def test_a_rewrite_replaces_the_content_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "f.json"
    write_atomic(target, b"one")
    write_atomic(target, b"two")
    assert target.read_bytes() == b"two"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.json"]


def test_a_symlink_at_the_target_is_replaced_not_followed(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_text("keep")
    target = tmp_path / "f.json"
    target.symlink_to(victim)
    write_atomic(target, b"new")
    assert victim.read_text() == "keep"
    assert not target.is_symlink()
    assert target.read_bytes() == b"new"


class _Names:
    """A ``token_hex`` replacement that hands out a fixed sequence (and counts the calls)."""

    def __init__(self, *names: str) -> None:
        self.names = list(names)
        self.calls = 0

    def __call__(self, nbytes: int) -> str:
        assert nbytes == 8
        value = self.names[min(self.calls, len(self.names) - 1)]
        self.calls += 1
        return value


def test_a_taken_temporary_name_is_retried_and_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = tmp_path / "victim"
    victim.write_text("keep")
    (tmp_path / ".f.json.dead.tmp").symlink_to(victim)  # a planted symlink at the first name
    names = _Names("dead", "beef")
    monkeypatch.setattr("sankey_studio.storage.atomic.secrets.token_hex", names)
    write_atomic(tmp_path / "f.json", b"data")
    assert names.calls == 2
    assert victim.read_text() == "keep"
    assert (tmp_path / "f.json").read_bytes() == b"data"


def test_running_out_of_temporary_names_fails_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".f.json.dead.tmp").write_text("taken")
    names = _Names("dead")
    monkeypatch.setattr("sankey_studio.storage.atomic.secrets.token_hex", names)
    with pytest.raises(FileExistsError):
        write_atomic(tmp_path / "f.json", b"data")
    assert names.calls == atomic.TMP_ATTEMPTS == 5
    assert not (tmp_path / "f.json").exists()
    assert (tmp_path / ".f.json.dead.tmp").read_text() == "taken"


def _raiser(error: OSError) -> Callable[..., Any]:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    return fail


def test_an_fsync_failure_keeps_the_old_file_and_removes_the_temporary_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.json"
    write_atomic(target, b"old")
    monkeypatch.setattr(
        "sankey_studio.storage.atomic.os.fsync", _raiser(OSError(errno.EIO, "disk"))
    )
    with pytest.raises(OSError, match="disk"):
        write_atomic(target, b"new")
    assert target.read_bytes() == b"old"
    assert _hidden(tmp_path) == []


def test_a_replace_failure_keeps_the_old_file_and_removes_the_temporary_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.json"
    write_atomic(target, b"old")
    monkeypatch.setattr(Path, "replace", _raiser(PermissionError(errno.EACCES, "denied")))
    with pytest.raises(PermissionError):
        write_atomic(target, b"new")
    assert target.read_bytes() == b"old"
    assert _hidden(tmp_path) == []


def test_an_open_failure_propagates_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sankey_studio.storage.atomic.os.open", _raiser(PermissionError(errno.EACCES, "denied"))
    )
    with pytest.raises(PermissionError):
        write_atomic(tmp_path / "f.json", b"x")
    assert list(tmp_path.iterdir()) == []


def test_a_failed_cleanup_is_logged_and_the_original_error_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "sankey_studio.storage.atomic.os.fsync", _raiser(OSError(errno.EIO, "disk"))
    )
    monkeypatch.setattr(Path, "unlink", _raiser(PermissionError(errno.EACCES, "denied")))
    with (
        caplog.at_level(logging.WARNING, logger=atomic.logger.name),
        pytest.raises(OSError, match="disk"),
    ):
        write_atomic(tmp_path / "f.json", b"x")
    [record] = caplog.records
    assert record.getMessage().startswith("Could not remove the temporary file .f.json.")
    assert record.levelno == logging.WARNING


def test_fsync_dir_syncs_a_directory_descriptor_and_closes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def spy(fd: int) -> None:
        assert stat.S_ISDIR(os.fstat(fd).st_mode)
        seen.append(fd)

    monkeypatch.setattr("sankey_studio.storage.atomic.os.fsync", spy)
    fsync_dir(tmp_path)
    [fd] = seen
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(fd)  # closed again


def test_fsync_dir_closes_the_descriptor_when_fsync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def fail(fd: int) -> None:
        seen.append(fd)
        raise OSError(errno.EIO, "disk")

    monkeypatch.setattr("sankey_studio.storage.atomic.os.fsync", fail)
    with pytest.raises(OSError, match="disk"):
        fsync_dir(tmp_path)
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(seen[0])


# --------------------------------------------------------------------------- read_file_nofollow


class Size(NamedTuple):
    size: int
    limit: int
    ok: bool


@pytest.mark.parametrize(
    "case",
    [
        Size(0, 10, True),
        Size(9, 10, True),
        Size(10, 10, True),
        Size(11, 10, False),
        Size(100, 10, False),
    ],
)
def test_the_size_cap_is_inclusive(tmp_path: Path, case: Size) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"x" * case.size)
    if case.ok:
        assert read_file_nofollow(path, case.limit) == b"x" * case.size
        return
    with pytest.raises(OSError, match="too large") as info:
        read_file_nofollow(path, case.limit)
    assert info.value.errno == errno.EFBIG


def test_a_missing_file_is_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_file_nofollow(tmp_path / "missing", 10)


def test_a_symlink_is_refused(tmp_path: Path) -> None:
    (tmp_path / "real").write_text("secret")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(OSError, match="symbolic links") as info:
        read_file_nofollow(tmp_path / "link", 100)
    assert info.value.errno == errno.ELOOP


def test_a_dangling_symlink_is_refused_too(tmp_path: Path) -> None:
    (tmp_path / "link").symlink_to(tmp_path / "nowhere")
    with pytest.raises(OSError, match="symbolic links") as info:
        read_file_nofollow(tmp_path / "link", 100)
    assert info.value.errno == errno.ELOOP


def test_a_directory_is_not_a_regular_file(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    with pytest.raises(OSError, match="not a regular file") as info:
        read_file_nofollow(tmp_path / "d", 100)
    assert info.value.errno == errno.EINVAL


def test_a_fifo_is_refused_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(OSError, match="not a regular file"):
        read_file_nofollow(tmp_path / "pipe", 100)


# --------------------------------------------------------------------------- ensure_private_dir


def test_missing_directories_are_created_0700_all_the_way_down(tmp_path: Path) -> None:
    leaf = tmp_path / "a" / "b" / "c"
    with umask(0o022):
        ensure_private_dir(leaf)
    for directory in (tmp_path / "a", tmp_path / "a" / "b", leaf):
        assert mode_of(directory) == 0o700


class Mode(NamedTuple):
    before: int
    after: int


@pytest.mark.parametrize(
    "case",
    [
        Mode(0o700, 0o700),
        Mode(0o755, 0o755),  # readable by others is fine: our files are 0600
        Mode(0o777, 0o755),  # world-writable: repaired
        Mode(0o770, 0o750),  # group-writable: repaired
        Mode(0o702, 0o700),  # other-writable only
        Mode(0o720, 0o700),  # group-writable only
    ],
)
def test_loose_modes_are_repaired_and_the_rest_is_left_alone(tmp_path: Path, case: Mode) -> None:
    directory = tmp_path / "data"
    directory.mkdir()
    directory.chmod(case.before)
    ensure_private_dir(directory)
    assert mode_of(directory) == case.after


def test_ensure_is_idempotent(tmp_path: Path) -> None:
    ensure_private_dir(tmp_path / "d")
    ensure_private_dir(tmp_path / "d")
    assert mode_of(tmp_path / "d") == 0o700


def test_a_directory_owned_by_someone_else_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(atomic, "current_uid", lambda: os.getuid() + 1)
    with pytest.raises(UnsafeDirectoryError, match="owned by another user") as info:
        ensure_private_dir(tmp_path)
    assert info.value.errno == errno.EPERM
    assert isinstance(info.value, OSError)


def test_a_regular_file_is_not_a_directory(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x")
    with pytest.raises(NotADirectoryError):
        ensure_private_dir(tmp_path / "f")


def test_the_owner_check_uses_the_real_uid(tmp_path: Path) -> None:
    assert atomic.current_uid() == os.getuid()
    assert tmp_path.stat().st_uid == atomic.current_uid()


# --------------------------------------------------------------------------- misc


def test_check_writable_leaves_nothing_behind(tmp_path: Path) -> None:
    check_writable(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_check_writable_reports_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sankey_studio.storage.atomic.os.open", _raiser(PermissionError(errno.EACCES, "denied"))
    )
    with pytest.raises(PermissionError):
        check_writable(tmp_path)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (OSError(errno.EACCES, "Permission denied"), "Permission denied"),
        (FileNotFoundError(errno.ENOENT, "No such file or directory"), "No such file or directory"),
        (OSError("plain"), "OSError"),
        (FileExistsError(), "FileExistsError"),
        (UnsafeDirectoryError(errno.EPERM, "mine"), "mine"),
    ],
)
def test_os_reason_is_path_free_text(error: OSError, reason: str) -> None:
    assert os_reason(error) == reason


def test_constants() -> None:
    assert atomic.FILE_MODE == 0o600
    assert atomic.DIR_MODE == 0o700
    assert atomic.UNSAFE_DIR_BITS == 0o022


def test_write_syncs_the_file_then_the_directory_and_stages_in_a_hidden_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = os.fsync
    events: list[tuple[str, list[str]]] = []

    def spy(fd: int) -> None:
        kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        events.append((kind, sorted(p.name for p in tmp_path.iterdir())))
        real_fsync(fd)

    monkeypatch.setattr("sankey_studio.storage.atomic.os.fsync", spy)
    write_atomic(tmp_path / "f.json", b"data")
    assert [kind for kind, _ in events] == ["file", "dir"]
    staged = events[0][1]  # while the file is fsynced only the hidden temporary exists
    assert len(staged) == 1
    assert staged[0].startswith(".f.json.")
    assert staged[0].endswith(".tmp")
    assert events[1][1] == ["f.json"]  # the directory is synced after the replace


def test_a_directory_created_by_someone_else_in_the_meantime_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``exists()`` said no, then another process made it: ``mkdir`` must not fail."""
    target = tmp_path / "raced"
    target.mkdir()
    real_exists = Path.exists

    def lying(self: Path, *, follow_symlinks: bool = True) -> bool:
        return False if self == target else real_exists(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "exists", lying)
    ensure_private_dir(target)
    assert target.is_dir()


def test_a_temporary_file_that_is_already_gone_is_not_worth_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_replace = Path.replace

    def moved_then_failed(self: Path, target: Path) -> Path:
        real_replace(self, target)
        raise OSError(errno.EIO, "failed after the move")

    monkeypatch.setattr(Path, "replace", moved_then_failed)
    with (
        caplog.at_level(logging.WARNING, logger=atomic.logger.name),
        pytest.raises(OSError, match="after the move"),
    ):
        write_atomic(tmp_path / "f.json", b"x")
    assert caplog.records == []
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


def test_the_writability_probe_is_a_hidden_ping_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names: list[str] = []
    real_open = os.open

    def spy(path: Any, flags: int, mode: int = 0o777) -> int:
        names.append(Path(path).name)
        return real_open(path, flags, mode)

    monkeypatch.setattr("sankey_studio.storage.atomic.os.open", spy)
    check_writable(tmp_path)
    [name] = names
    assert name.startswith(".ping.")
    assert name.endswith(".tmp")
