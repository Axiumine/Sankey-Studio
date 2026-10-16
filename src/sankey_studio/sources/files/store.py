# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The managed sources directory: list, upload, delete and preview.

Uploads are written to a hidden ``.<random>.part`` file created ``O_EXCL`` (mode 0600), fsynced,
and then published atomically: ``os.link`` fails if the name exists (no overwrite), ``os.replace``
is used only when the caller asked to overwrite. Names are compared casefolded, so ``A.csv``
and ``a.csv`` collide; listing the directory and publishing happen under an exclusive ``flock`` on
the directory, so uploads of case variants cannot race (threads and processes alike). A filesystem
without ``flock`` publishes unserialised. Operating-system failures become ``StorageError``.

``edit_file`` is the write-back: it replaces the content of an EXISTING managed file (never
creates one) through the same fd-based checks, under the same directory lock, via a part file.
"""

from __future__ import annotations

import fcntl
import io
import itertools
import logging
import os
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sankey_studio.errors import (
    ConflictError,
    PayloadTooLargeError,
    SourceEditRefused,
    SourceNotFoundError,
    StorageError,
    UnsafeSourceError,
)
from sankey_studio.sources.files.names import clean_filename
from sankey_studio.sources.files.paths import (
    MIB,
    has_allowed_extension,
    located,
    open_binary,
    open_leaf,
    split_relative,
)
from sankey_studio.sources.files.types import SourceFileInfo
from sankey_studio.sources.formats.lines import LineReader

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import IO

    from sankey_studio.sources.files.types import SaveRequest

logger = logging.getLogger(__name__)

#: ``list_files`` scans directories up to this many levels below the sources directory.
MAX_DEPTH = 3
CHUNK_BYTES = MIB
PREVIEW_LINE_MAX = 500
PREVIEW_TOTAL_MAX = 64 * 1024
PART_SUFFIX = ".part"
PART_MODE = 0o600
_PART_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


# --------------------------------------------------------------------------- list


def _describe(directory: Path, root: Path, name: str) -> SourceFileInfo | None:
    """Info about one regular file with an allowed extension and a name the routes accept."""
    if not has_allowed_extension(name):
        return None
    path = directory / name
    try:
        info = path.lstat()
    except OSError:  # vanished while we walked
        return None
    if not stat.S_ISREG(info.st_mode):  # symlinks, sockets, FIFOs
        return None
    rel = path.relative_to(root).as_posix()
    try:
        rel.encode("utf-8")
        split_relative(rel)  # a name preview and delete would refuse (a backslash) is not offered
    except UnicodeEncodeError, UnsafeSourceError:  # not valid text, or not addressable
        return None
    return SourceFileInfo(rel, info.st_size, datetime.fromtimestamp(info.st_mtime, tz=UTC))


def list_files(sources_dir: Path) -> list[SourceFileInfo]:
    """Allowed regular files below ``sources_dir`` (depth <= 3, symlinks skipped), by name."""
    found: list[SourceFileInfo] = []
    for directory, subdirs, names in os.walk(sources_dir, followlinks=False):
        here = Path(directory)
        if len(here.relative_to(sources_dir).parts) >= MAX_DEPTH:
            subdirs.clear()
        described = (_describe(here, sources_dir, name) for name in names)
        found.extend(info for info in described if info is not None)
    return sorted(found, key=lambda info: (info.name.casefold(), info.name))


# --------------------------------------------------------------------------- delete, preview


def delete_file(sources_dir: Path, name: str) -> None:
    """Delete one managed file (same checks as reading it)."""
    with located(sources_dir, name) as (dir_fd, leaf):
        os.close(open_leaf(dir_fd, leaf, name).fd)
        try:
            os.unlink(leaf, dir_fd=dir_fd)
        except FileNotFoundError:
            raise SourceNotFoundError(f"{name}: no such file or directory") from None
        except OSError:
            raise StorageError(f"{name}: could not be deleted") from None


def _preview_lines(lines: LineReader, max_lines: int) -> list[str]:
    out: list[str] = []
    budget = PREVIEW_TOTAL_MAX
    for line in itertools.islice(lines.lines(), max(max_lines, 0)):
        if budget <= 0:
            break
        text = line.text.removesuffix("\n")[:budget]
        out.append(text)
        budget -= len(text)
    return out


def preview_file(sources_dir: Path, name: str, max_lines: int = 50) -> list[str]:
    """The first ``max_lines`` lines (each <= 500 characters, 64 KB in total) for display.

    Decoded leniently as UTF-8: a preview is for eyes, the real load decodes strictly.
    """
    with (
        open_binary(sources_dir, name) as raw,
        io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as text,
    ):
        return _preview_lines(LineReader(text, PREVIEW_LINE_MAX, name), max_lines)


# --------------------------------------------------------------------------- upload


def _write_part(fd: int, request: SaveRequest, stream: IO[bytes]) -> None:
    """Copy ``stream`` into the open ``fd`` in 1 MiB chunks, enforcing ``max_bytes``."""
    total = 0
    with os.fdopen(fd, "wb") as out:
        while chunk := stream.read(CHUNK_BYTES):
            total += len(chunk)
            if total > request.max_bytes:
                raise PayloadTooLargeError(
                    f"the upload is larger than the limit of {request.max_bytes} bytes"
                )
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())


def _existing_name(dir_fd: int, name: str) -> str | None:
    """The stored name that collides with ``name`` casefolded (an exact match wins)."""
    names = sorted(os.listdir(dir_fd))
    if name in names:
        return name
    key = name.casefold()
    return next((other for other in names if other.casefold() == key), None)


def _lock(dir_fd: int) -> None:
    """Take the directory's exclusive lock; it is released when ``dir_fd`` is closed."""
    with suppress(OSError):  # a filesystem without flock: the publish runs unserialised
        fcntl.flock(dir_fd, fcntl.LOCK_EX)


def _publish(dir_fd: int, part: str, name: str, overwrite: bool) -> str:
    """Move the finished ``part`` file to ``name``; returns the name it was stored under."""
    _lock(dir_fd)  # the collision check and the publish below are one step
    existing = _existing_name(dir_fd, name)
    if existing is not None and not overwrite:
        raise ConflictError(f"a file named '{existing}' already exists")
    final = existing or name
    if overwrite:
        os.replace(part, final, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        return final
    try:
        os.link(part, final, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
    except FileExistsError:  # lost a race against another upload of the same name
        raise ConflictError(f"a file named '{final}' already exists") from None
    return final


def _save_in(dir_fd: int, name: str, request: SaveRequest, stream: IO[bytes]) -> SourceFileInfo:
    part = f".{secrets.token_hex(8)}{PART_SUFFIX}"
    fd = os.open(
        part, _PART_FLAGS, PART_MODE, dir_fd=dir_fd
    )  # O_EXCL: never ours to remove if it fails
    try:
        _write_part(fd, request, stream)
        final = _publish(dir_fd, part, name, request.overwrite)
        info = os.stat(final, dir_fd=dir_fd, follow_symlinks=False)
    finally:
        with suppress(OSError):
            os.unlink(part, dir_fd=dir_fd)
    return SourceFileInfo(final, info.st_size, datetime.fromtimestamp(info.st_mtime, tz=UTC))


def save_stream(request: SaveRequest, stream: IO[bytes]) -> SourceFileInfo:
    """Store an upload under ``request.sources_dir`` and return its info.

    ``PayloadTooLargeError`` once ``request.max_bytes`` is exceeded, ``ConflictError`` when the
    name is taken (``overwrite=False``; casefolded), ``StorageError`` on an OS failure. With
    ``overwrite=True`` a file whose name differs only in case is replaced under ITS name.
    ``stream`` is any binary file object (a ``SpooledTemporaryFile``, ``UploadFile.file``): it is
    read from its current position and left open.
    """
    name = clean_filename(request.filename)  # fail before touching the disk
    try:
        request.sources_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        dir_fd = os.open(request.sources_dir, _DIR_FLAGS)
        try:
            return _save_in(dir_fd, name, request, stream)
        finally:
            os.close(dir_fd)
    except OSError:
        raise StorageError("the upload could not be stored") from None


# --------------------------------------------------------------------------- write-back


@dataclass(frozen=True, slots=True)
class FileEdit:
    """Arguments of ``read_text`` / ``edit_file``: the file ``name`` below ``sources_dir``.

    ``encoding`` decodes and re-encodes the content; ``max_bytes`` is the largest file handled.
    """

    sources_dir: Path
    name: str
    encoding: str
    max_bytes: int


def _read_all(fd: int, request: FileEdit) -> bytes:
    """The whole file through a bounded loop (it may have grown since ``fstat``)."""
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := os.read(fd, CHUNK_BYTES):
            total += len(chunk)
            if total > request.max_bytes:
                raise SourceEditRefused("file_too_large")
            chunks.append(chunk)
    except OSError:
        raise SourceEditRefused("unreadable") from None
    return b"".join(chunks)


def _decode(data: bytes, encoding: str) -> str:
    """Strict decode: ``bytes.decode`` keeps every line ending as it is on disk."""
    try:
        return data.decode(encoding)
    except UnicodeDecodeError, LookupError:
        raise SourceEditRefused("unreadable") from None


def _encode(text: str, encoding: str) -> bytes:
    """Encode BEFORE any part file exists: a character the encoding lacks refuses the edit."""
    try:
        return text.encode(encoding)
    except UnicodeEncodeError:
        raise SourceEditRefused("unrepresentable") from None


#: ``(inode, size, mtime_ns, ctime_ns)``: what proves the file is the one that was read.
type Stamp = tuple[int, int, int, int]


def _stamp(info: os.stat_result) -> Stamp:
    return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_leaf(dir_fd: int, leaf: str, request: FileEdit) -> tuple[str, Stamp, int]:
    """Decoded text, the stamp and the permission bits of the existing regular file ``leaf``."""
    opened = open_leaf(dir_fd, leaf, request.name)
    try:
        if opened.size > request.max_bytes:
            raise SourceEditRefused("file_too_large")
        info = os.fstat(opened.fd)
        data = _read_all(opened.fd, request)
    finally:
        os.close(opened.fd)
    return _decode(data, request.encoding), _stamp(info), stat.S_IMODE(info.st_mode)


def read_text(request: FileEdit) -> str:
    """The decoded content of the file, for a dry run (no lock, nothing written).

    ``SourceEditRefused`` with reason ``file_too_large`` or ``unreadable``; the path errors of
    ``located``/``open_leaf`` (``UnsafeSourceError``, ``SourceNotFoundError``) pass through.
    """
    with located(request.sources_dir, request.name) as (dir_fd, leaf):
        return _read_leaf(dir_fd, leaf, request)[0]


def _current_stamp(dir_fd: int, leaf: str) -> Stamp | None:
    try:
        return _stamp(os.stat(leaf, dir_fd=dir_fd, follow_symlinks=False))
    except FileNotFoundError:  # removed or renamed away meanwhile
        return None


def _write_and_replace(dir_fd: int, leaf: str, payload: bytes, before: tuple[Stamp, int]) -> None:
    """Write the part file, check the stamp once more, then replace ``leaf`` atomically."""
    stamp, mode = before
    part = f".{secrets.token_hex(8)}{PART_SUFFIX}"
    fd = os.open(part, _PART_FLAGS, PART_MODE, dir_fd=dir_fd)  # O_EXCL: ours to remove
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fchmod(out.fileno(), mode)
            os.fsync(out.fileno())
        if _current_stamp(dir_fd, leaf) != stamp:
            raise ConflictError("The file changed while it was being edited")
        os.replace(part, leaf, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    finally:
        with suppress(OSError):
            os.unlink(part, dir_fd=dir_fd)


def edit_file(request: FileEdit, rewrite: Callable[[str], str]) -> int:
    """Replace the content of the existing managed file by ``rewrite(content)``; bytes written.

    Under the directory lock: read (bounded, strict decode), ``rewrite`` (pure; a
    ``SourceEditRefused`` leaves the file alone), encode, write a ``.part`` file with the same
    permission bits, re-check the ``(inode, size, mtime, ctime)`` stamp, then ``os.replace`` and
    fsync the directory. ``ConflictError`` when the file changed meanwhile; ``StorageError`` (no
    path in the message) on an OS failure. Ownership and ACLs are not preserved and a hard link
    to the file is broken by the replace.
    """
    with located(request.sources_dir, request.name) as (dir_fd, leaf):
        _lock(dir_fd)
        text, stamp, mode = _read_leaf(dir_fd, leaf, request)
        payload = _encode(rewrite(text), request.encoding)
        try:
            _write_and_replace(dir_fd, leaf, payload, (stamp, mode))
        except OSError:
            raise StorageError("the file could not be written") from None
    logger.info("source write: file=%r bytes=%d", request.name, len(payload))
    return len(payload)
