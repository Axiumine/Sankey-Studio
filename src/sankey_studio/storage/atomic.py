# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Crash-safe, symlink-safe file primitives shared by the graph files and ``settings.json``.

Everything here raises plain ``OSError`` (callers map it to ``StorageError`` or ``SettingsError``
with a fixed message; see ``os_reason``). Rules:

* Writes go to a temporary sibling created with ``O_CREAT | O_EXCL | O_NOFOLLOW`` and mode 0600,
  are fsynced, replace the target with ``os.replace`` and the directory is fsynced afterwards.
* Reads open the file with ``O_NOFOLLOW`` (a symlink is refused), check ``fstat`` for a regular
  file AFTER the open (no check-then-use race) and cap the number of bytes read.
* Directories that hold secrets are created 0700; an existing one that belongs to another user
  is refused and one that group/others can write to is repaired.
"""

from __future__ import annotations

import errno
import logging
import os
import secrets
import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

FILE_MODE = 0o600
DIR_MODE = 0o700
#: Group and other write bits: a data directory that has either can be tampered with.
UNSAFE_DIR_BITS = 0o022
TMP_ATTEMPTS = 5

_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
#: ``O_NONBLOCK``: opening a FIFO named like a graph file must not hang the request.
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


class UnsafeDirectoryError(OSError):
    """The directory belongs to another user (it would let them read or replace our files)."""


def current_uid() -> int:
    """Seam for the ownership check (tests cannot ``chown`` to another user)."""
    return os.getuid()


def os_reason(exc: OSError) -> str:
    """Short, path-free text for an ``OSError`` (``strerror``, else the class name)."""
    return exc.strerror or type(exc).__name__


def _make_dirs(path: Path) -> None:
    """``mkdir -p`` where every directory this call creates is 0700."""
    if path.exists():
        return
    _make_dirs(path.parent)
    path.mkdir(mode=DIR_MODE, exist_ok=True)


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` (0700) if needed, then refuse a foreign owner and repair loose modes."""
    _make_dirs(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, "not a directory")
    if info.st_uid != current_uid():
        raise UnsafeDirectoryError(errno.EPERM, "the directory is owned by another user")
    mode = stat.S_IMODE(info.st_mode)
    if mode & UNSAFE_DIR_BITS:
        path.chmod(mode & ~UNSAFE_DIR_BITS)


def fsync_dir(directory: Path) -> None:
    fd = os.open(directory, _DIR_FLAGS)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _open_exclusive(directory: Path, name: str) -> tuple[int, Path]:
    """Open a fresh ``.<name>.<random>.tmp`` (0600); retry when the random name is taken."""
    for _ in range(TMP_ATTEMPTS):
        tmp = directory / f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            return os.open(tmp, _WRITE_FLAGS, FILE_MODE), tmp
        except FileExistsError:
            continue
    raise FileExistsError(errno.EEXIST, "no free temporary file name")


def _discard(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove the temporary file %s", tmp.name)


def _write_all(fd: int, data: bytes) -> None:
    """``os.write`` may take less than it is given (a signal, a full disk): loop till done."""
    rest = memoryview(data)
    while rest:
        rest = rest[os.write(fd, rest) :]


def _read_capped(fd: int, size: int) -> bytes:
    """Up to ``size`` bytes: fewer at the end of the file, and ``os.read`` may return less."""
    chunks: list[bytes] = []
    while size:
        chunk = os.read(fd, size)
        if not chunk:
            break
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)


def write_atomic(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` (mode 0600) so readers see the old or the new file only."""
    fd, tmp = _open_exclusive(path.parent, path.name)
    try:
        _write_all(fd, data)
        os.fsync(fd)
        tmp.replace(path)
    except BaseException:
        _discard(tmp)
        raise
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def read_file_nofollow(path: Path, limit: int) -> bytes:
    """Read a regular file of at most ``limit`` bytes; refuse symlinks, devices and big files."""
    fd = os.open(path, _READ_FLAGS)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
        data = _read_capped(fd, limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise OSError(errno.EFBIG, "the file is too large")
    return data


def check_writable(directory: Path) -> None:
    """Prove that a file can be created in ``directory`` (and remove it again)."""
    fd, tmp = _open_exclusive(directory, "ping")
    os.close(fd)
    tmp.unlink()
