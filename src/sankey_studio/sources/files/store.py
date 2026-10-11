"""The managed sources directory: list, upload, delete and preview.

Uploads are written to a hidden ``.<random>.part`` file created ``O_EXCL`` (mode 0600), fsynced,
and then published atomically: ``os.link`` fails if the name exists (no overwrite), ``os.replace``
is used only when the caller asked to overwrite. Names are compared casefolded, so ``A.csv``
and ``a.csv`` collide; listing the directory and publishing happen under an exclusive ``flock`` on
the directory, so uploads of case variants cannot race (threads and processes alike). A filesystem
without ``flock`` publishes unserialised. Operating-system failures become ``StorageError``.
"""

from __future__ import annotations

import fcntl
import io
import itertools
import os
import secrets
import stat
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sankey_studio.errors import (
    ConflictError,
    PayloadTooLargeError,
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
    from typing import IO

    from sankey_studio.sources.files.types import SaveRequest

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
