# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Safe access to files under the managed sources directory.

Every operation (read, preview, delete, list) goes through here. The rules:

* the extension is on the casefolded allow-list ``ALLOWED_EXTENSIONS``;
* the relative path has no ``..``, empty or ``.`` segments, no backslash, no NUL, is not absolute;
* components below the sources directory are opened one by one with ``O_NOFOLLOW`` relative to
  the parent descriptor, so a symlink anywhere on the path is refused and a swap between the
  check and the open cannot redirect us;
* the file is opened ``O_NONBLOCK`` (a FIFO cannot hang us) and ``fstat`` must say "regular file";
* reads go through ``BoundedReader``, which counts bytes (a file may grow after the check).

Failures: ``UnsafeSourceError`` (escape, symlink, device, FIFO, extension), ``SourceNotFoundError``
(missing), ``SourceError`` (too big, unreadable). The sources directory itself is the operator's
and may be reached through a symlink.
"""

from __future__ import annotations

import errno
import io
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

from sankey_studio.errors import SankeyError, SourceError, SourceNotFoundError, UnsafeSourceError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _typeshed import WriteableBuffer

ALLOWED_EXTENSIONS = frozenset({".csv", ".tsv", ".txt", ".json", ".ndjson", ".sankey"})
MIB = 1024 * 1024
#: ``max_bytes`` meaning "no limit" (the file is only checked to be regular).
UNLIMITED = sys.maxsize

_ROOT_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
#: What ``open`` reports for a symlink (or a non-directory) met with ``O_NOFOLLOW``/``O_DIRECTORY``.
_LINK_ERRNOS = frozenset({errno.ELOOP, errno.ENOTDIR, errno.EMLINK})


class OpenedFile(NamedTuple):
    """A descriptor that ``fstat`` confirmed to be a regular file, and its size."""

    fd: int
    size: int


def split_relative(rel: str) -> list[str]:
    """The segments of a relative POSIX path, or ``UnsafeSourceError``."""
    if not rel or rel.startswith("/") or "\\" in rel or "\0" in rel:
        raise UnsafeSourceError("path must be a relative POSIX path inside the sources directory")
    parts = rel.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafeSourceError("path must not contain '.', '..' or empty segments")
    return parts


def has_allowed_extension(name: str) -> bool:
    """True when the casefolded extension of ``name`` is on the allow-list."""
    return PurePosixPath(name).suffix.casefold() in ALLOWED_EXTENSIONS


def check_extension(name: str) -> None:
    """Refuse a file whose (casefolded) extension is not on the allow-list."""
    if not has_allowed_extension(name):
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UnsafeSourceError(f"only files with these extensions are allowed: {allowed}")


def _open_error(exc: OSError, rel: str) -> SankeyError:
    if isinstance(exc, FileNotFoundError):
        return SourceNotFoundError(f"{rel}: no such file or directory")
    if exc.errno in _LINK_ERRNOS:
        return UnsafeSourceError(f"{rel}: symbolic links and non-directories are not followed")
    return SourceError(f"{rel}: cannot be opened")


def _open_at(name: str | Path, flags: int, dir_fd: int | None, rel: str) -> int:
    try:
        return os.open(name, flags, dir_fd=dir_fd)
    except OSError as exc:
        raise _open_error(exc, rel) from None


def open_parent(sources_dir: Path, parts: list[str], rel: str) -> int:
    """A descriptor of the directory that holds ``parts[-1]``; nothing on the way is a symlink."""
    fd = _open_at(sources_dir, _ROOT_FLAGS, None, rel)
    try:
        for part in parts[:-1]:
            child = _open_at(part, _DIR_FLAGS, fd, rel)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def located(sources_dir: Path, rel: str) -> Iterator[tuple[int, str]]:
    """Validate ``rel`` and yield ``(parent directory fd, file name)``; the fd is closed after."""
    parts = split_relative(rel)
    check_extension(parts[-1])
    dir_fd = open_parent(sources_dir, parts, rel)
    try:
        yield dir_fd, parts[-1]
    finally:
        os.close(dir_fd)


def open_leaf(dir_fd: int, leaf: str, rel: str) -> OpenedFile:
    """Open ``leaf`` in ``dir_fd`` and make sure it is a regular file. The caller closes the fd."""
    fd = _open_at(leaf, _FILE_FLAGS, dir_fd, rel)
    try:
        info = os.fstat(fd)
    except OSError:
        os.close(fd)
        raise SourceError(f"{rel}: cannot be read") from None
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise UnsafeSourceError(f"{rel}: not a regular file")
    return OpenedFile(fd, info.st_size)


def resolve_source_path(sources_dir: Path, rel: str) -> Path:
    """Validate ``rel`` (extension, no escape, no symlink, regular file) and return its path.

    The returned path is for display; read through ``open_binary`` (a path can be swapped later).
    """
    with located(sources_dir, rel) as (dir_fd, leaf):
        os.close(open_leaf(dir_fd, leaf, rel).fd)
    return sources_dir / rel


def format_limit(size: int) -> str:
    """A byte limit for messages: whole megabytes as 'N MB', anything else in bytes."""
    return f"{size // MIB} MB" if size % MIB == 0 else f"{size} bytes"


class BoundedReader(io.RawIOBase):
    """Reads a descriptor and refuses to deliver more than ``max_bytes`` bytes in total."""

    def __init__(self, fd: int, max_bytes: int, rel: str) -> None:
        super().__init__()
        self._fd = fd
        self._max = max_bytes
        self._left = max_bytes
        self._rel = rel

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: WriteableBuffer) -> int:
        view = memoryview(buffer).cast("B")
        try:
            data = os.read(self._fd, len(view))
        except OSError:
            raise SourceError(f"{self._rel}: cannot be read") from None
        self._left -= len(data)
        if self._left < 0:
            raise SourceError(f"{self._rel}: file is larger than {format_limit(self._max)}")
        view[: len(data)] = data
        return len(data)

    def close(self) -> None:
        if not self.closed:
            os.close(self._fd)
        super().close()


def open_binary(sources_dir: Path, rel: str, max_bytes: int = UNLIMITED) -> io.BufferedReader:
    """A buffered binary reader over the checked file; it never delivers more than ``max_bytes``."""
    with located(sources_dir, rel) as (dir_fd, leaf):
        opened = open_leaf(dir_fd, leaf, rel)
    if opened.size > max_bytes:
        os.close(opened.fd)
        raise SourceError(f"{rel}: file is larger than {format_limit(max_bytes)}")
    return io.BufferedReader(BoundedReader(opened.fd, max_bytes, rel))
