# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``resolve_source_path`` and the fd-based walk: traversal, symlinks, FIFOs, swaps, OS errors."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceError, SourceNotFoundError, UnsafeSourceError
from sankey_studio.sources.files import ALLOWED_EXTENSIONS, resolve_source_path
from sankey_studio.sources.files.paths import (
    check_extension,
    has_allowed_extension,
    located,
    open_leaf,
    split_relative,
)
from tests.sources.idtools import safe_id
from tests.sources.text_support import open_fd_count

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def touch(root: Path, rel: str, data: str = "source,target,value\na,b,1\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- split_relative


def test_split_relative_accepts_plain_relative_paths() -> None:
    assert split_relative("a.csv") == ["a.csv"]
    assert split_relative("d/e/f.csv") == ["d", "e", "f.csv"]
    assert split_relative("d.d/..x/.hidden.csv") == ["d.d", "..x", ".hidden.csv"]


SHAPE = "path must be a relative POSIX path inside the sources directory"
SEGMENTS = "path must not contain '.', '..' or empty segments"
BAD_PATHS = [
    ("", SHAPE),
    ("/etc/passwd", SHAPE),
    ("/a.csv", SHAPE),
    ("a\\b.csv", SHAPE),
    ("a\0.csv", SHAPE),
    ("..", SEGMENTS),
    ("../a.csv", SEGMENTS),
    ("a/../b.csv", SEGMENTS),
    ("a/..", SEGMENTS),
    (".", SEGMENTS),
    ("./a.csv", SEGMENTS),
    ("a/./b.csv", SEGMENTS),
    ("a//b.csv", SEGMENTS),
    ("a/", SEGMENTS),
]


@pytest.mark.parametrize(
    ("rel", "message"), BAD_PATHS, ids=[safe_id(repr(p)) for p, _ in BAD_PATHS]
)
def test_split_relative_refuses_with_the_exact_message(rel: str, message: str) -> None:
    with pytest.raises(UnsafeSourceError) as info:
        split_relative(rel)
    assert str(info.value) == message


# --------------------------------------------------------------------------- extensions


@pytest.mark.parametrize("ext", sorted(ALLOWED_EXTENSIONS))
def test_every_allowed_extension_in_both_cases(ext: str) -> None:
    for name in (f"a{ext}", f"a{ext.upper()}", f"A.b{ext}"):
        assert has_allowed_extension(name)
        check_extension(name)


@pytest.mark.parametrize(
    "name", ["a", "a.", ".csv", "a.csvx", "a.xcsv", "a.exe", "csv", "a.csv.bak"]
)
def test_other_extensions_are_refused(name: str) -> None:
    assert not has_allowed_extension(name)
    with pytest.raises(UnsafeSourceError, match=r"^only files with these extensions are allowed: "):
        check_extension(name)


# --------------------------------------------------------------------------- resolve


def test_resolve_returns_the_path_of_a_regular_file(text_root: Path) -> None:
    touch(text_root, "a.csv")
    touch(text_root, "d/e/b.TSV")
    assert resolve_source_path(text_root, "a.csv") == text_root / "a.csv"
    assert resolve_source_path(text_root, "d/e/b.TSV") == text_root / "d/e/b.TSV"


class Failure(NamedTuple):
    rel: str
    error: type[Exception]
    message: str


def test_a_missing_file_is_not_found(text_root: Path) -> None:
    with pytest.raises(SourceNotFoundError) as info:
        resolve_source_path(text_root, "gone.csv")
    assert str(info.value) == "gone.csv: no such file or directory"


def test_a_missing_directory_on_the_way_is_not_found(text_root: Path) -> None:
    with pytest.raises(SourceNotFoundError) as info:
        resolve_source_path(text_root, "no/such/a.csv")
    assert str(info.value) == "no/such/a.csv: no such file or directory"


def test_a_missing_sources_directory_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(SourceNotFoundError, match=r"a\.csv: no such file or directory"):
        resolve_source_path(tmp_path / "absent", "a.csv")


def test_the_extension_is_checked_before_the_disk_is_touched(tmp_path: Path) -> None:
    with pytest.raises(UnsafeSourceError, match=r"^only files with these"):
        resolve_source_path(tmp_path / "absent", "a.exe")


def test_traversal_is_refused_before_the_disk_is_touched(tmp_path: Path) -> None:
    with pytest.raises(UnsafeSourceError, match=r"^path must not contain"):
        resolve_source_path(tmp_path / "absent", "../a.csv")


LINK = "symbolic links and non-directories are not followed"


def test_a_symlinked_file_is_refused(text_root: Path, tmp_path: Path) -> None:
    secret = touch(tmp_path, "secret.csv")
    (text_root / "link.csv").symlink_to(secret)
    with pytest.raises(UnsafeSourceError) as info:
        resolve_source_path(text_root, "link.csv")
    assert str(info.value) == f"link.csv: {LINK}"


def test_a_dangling_symlink_is_refused_as_unsafe_not_missing(
    text_root: Path, tmp_path: Path
) -> None:
    (text_root / "dangling.csv").symlink_to(tmp_path / "nowhere.csv")
    with pytest.raises(UnsafeSourceError, match=LINK):
        resolve_source_path(text_root, "dangling.csv")


def test_a_symlinked_directory_on_the_way_is_refused(text_root: Path, tmp_path: Path) -> None:
    touch(tmp_path / "outside", "a.csv")
    (text_root / "d").symlink_to(tmp_path / "outside")
    with pytest.raises(UnsafeSourceError) as info:
        resolve_source_path(text_root, "d/a.csv")
    assert str(info.value) == f"d/a.csv: {LINK}"


def test_a_symlink_two_levels_down_is_refused(text_root: Path, tmp_path: Path) -> None:
    touch(tmp_path / "outside", "a.csv")
    (text_root / "x").mkdir()
    (text_root / "x" / "y").symlink_to(tmp_path / "outside")
    with pytest.raises(UnsafeSourceError, match=LINK):
        resolve_source_path(text_root, "x/y/a.csv")


def test_a_file_in_the_place_of_a_directory_is_refused(text_root: Path) -> None:
    touch(text_root, "f.csv")
    with pytest.raises(UnsafeSourceError, match=LINK):
        resolve_source_path(text_root, "f.csv/a.csv")


def test_a_directory_is_not_a_regular_file(text_root: Path) -> None:
    (text_root / "d.csv").mkdir()
    with pytest.raises(UnsafeSourceError) as info:
        resolve_source_path(text_root, "d.csv")
    assert str(info.value) == "d.csv: not a regular file"


def test_a_fifo_is_refused_without_blocking(text_root: Path) -> None:
    os.mkfifo(text_root / "pipe.csv")
    with pytest.raises(UnsafeSourceError) as info:
        resolve_source_path(text_root, "pipe.csv")
    assert str(info.value) == "pipe.csv: not a regular file"


def test_a_device_is_refused(text_root: Path) -> None:
    if not Path("/dev/null").exists():
        pytest.skip("needs /dev/null")
    (text_root / "null.csv").symlink_to("/dev/null")
    with pytest.raises(UnsafeSourceError):
        resolve_source_path(text_root, "null.csv")


def test_the_sources_directory_itself_may_be_a_symlink(text_root: Path, tmp_path: Path) -> None:
    touch(text_root, "a.csv")
    alias = tmp_path / "alias"
    alias.symlink_to(text_root)
    assert resolve_source_path(alias, "a.csv") == alias / "a.csv"


# --------------------------------------------------------------------------- swaps


def test_a_directory_swapped_for_a_symlink_after_the_walk_is_not_followed(
    text_root: Path, tmp_path: Path
) -> None:
    touch(text_root, "d/a.csv", "original")
    touch(tmp_path / "outside", "a.csv", "secret")
    with located(text_root, "d/a.csv") as (dir_fd, leaf):
        (text_root / "d" / "a.csv").unlink()
        (text_root / "d").rmdir()
        (text_root / "d").symlink_to(tmp_path / "outside")
        # the descriptor still points at the original directory, which is now gone: no secret
        with pytest.raises(SourceNotFoundError):
            open_leaf(dir_fd, leaf, "d/a.csv")


def test_the_original_directory_is_read_through_its_descriptor(
    text_root: Path, tmp_path: Path
) -> None:
    touch(text_root, "d/a.csv", "original")
    touch(tmp_path / "outside", "a.csv", "secret")
    with located(text_root, "d/a.csv") as (dir_fd, leaf):
        (text_root / "d").rename(tmp_path / "moved")
        (text_root / "d").symlink_to(tmp_path / "outside")
        opened = open_leaf(dir_fd, leaf, "d/a.csv")
        try:
            assert os.read(opened.fd, 100) == b"original"
            assert opened.size == len("original")
        finally:
            os.close(opened.fd)


def test_a_file_swapped_for_a_symlink_after_the_walk_is_refused(
    text_root: Path, tmp_path: Path
) -> None:
    touch(text_root, "a.csv", "original")
    secret = touch(tmp_path, "secret.csv", "secret")
    with located(text_root, "a.csv") as (dir_fd, leaf):
        (text_root / "a.csv").unlink()
        (text_root / "a.csv").symlink_to(secret)
        with pytest.raises(UnsafeSourceError, match=LINK):
            open_leaf(dir_fd, leaf, "a.csv")


def test_located_yields_the_parent_descriptor_and_the_leaf_and_closes_it(text_root: Path) -> None:
    touch(text_root, "d/a.csv")
    before = open_fd_count()
    with located(text_root, "d/a.csv") as (dir_fd, leaf):
        assert leaf == "a.csv"
        assert [entry.name for entry in os.scandir(dir_fd)] == ["a.csv"]
        assert open_fd_count() == before + 1
    assert open_fd_count() == before
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(dir_fd)


# --------------------------------------------------------------------------- OS errors


def fail_open_for(name: str, error: OSError) -> Callable[..., int]:
    real = os.open

    def fake(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if path == name:
            raise error
        return real(path, flags, *args, **kwargs)

    return fake


class OsFailure(NamedTuple):
    error: OSError
    expected: type[Exception]
    message: str


OS_FAILURES = [
    OsFailure(PermissionError(errno.EACCES, "denied"), SourceError, "a.csv: cannot be opened"),
    OsFailure(OSError(errno.EMFILE, "too many"), SourceError, "a.csv: cannot be opened"),
    OsFailure(OSError(errno.EIO, "io"), SourceError, "a.csv: cannot be opened"),
    OsFailure(OSError(errno.ELOOP, "loop"), UnsafeSourceError, f"a.csv: {LINK}"),
    OsFailure(OSError(errno.ENOTDIR, "not a dir"), UnsafeSourceError, f"a.csv: {LINK}"),
    OsFailure(OSError(errno.EMLINK, "bsd symlink"), UnsafeSourceError, f"a.csv: {LINK}"),
    OsFailure(
        FileNotFoundError(errno.ENOENT, "gone"),
        SourceNotFoundError,
        "a.csv: no such file or directory",
    ),
]


@pytest.mark.parametrize(
    "case", OS_FAILURES, ids=[type(c.error).__name__ + str(c.error.errno) for c in OS_FAILURES]
)
def test_open_errors_map_to_domain_errors_without_driver_text(
    text_root: Path, monkeypatch: pytest.MonkeyPatch, case: OsFailure
) -> None:
    touch(text_root, "a.csv")
    monkeypatch.setattr(os, "open", fail_open_for("a.csv", case.error))
    with pytest.raises(case.expected) as info:
        resolve_source_path(text_root, "a.csv")
    assert type(info.value) is case.expected
    assert str(info.value) == case.message


def test_a_failing_open_on_the_way_closes_the_parent_descriptor(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch(text_root, "d/e/a.csv")
    monkeypatch.setattr(os, "open", fail_open_for("e", PermissionError(errno.EACCES, "denied")))
    before = open_fd_count()
    with pytest.raises(SourceError, match=r"^d/e/a\.csv: cannot be opened$"):
        resolve_source_path(text_root, "d/e/a.csv")
    assert open_fd_count() == before


def test_a_failing_fstat_is_a_source_error_and_closes_the_descriptor(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch(text_root, "a.csv")

    def boom(_fd: int) -> os.stat_result:
        raise OSError(errno.EIO, "io")

    before = open_fd_count()
    monkeypatch.setattr(os, "fstat", boom)
    with pytest.raises(SourceError) as info:
        resolve_source_path(text_root, "a.csv")
    assert str(info.value) == "a.csv: cannot be read"
    monkeypatch.undo()
    assert open_fd_count() == before


def test_a_refused_file_does_not_leak_a_descriptor(text_root: Path) -> None:
    os.mkfifo(text_root / "pipe.csv")
    before = open_fd_count()
    for _ in range(3):
        with pytest.raises(UnsafeSourceError):
            resolve_source_path(text_root, "pipe.csv")
    assert open_fd_count() == before


def test_a_successful_resolve_does_not_leak_a_descriptor(text_root: Path) -> None:
    touch(text_root, "d/a.csv")
    before = open_fd_count()
    for _ in range(3):
        resolve_source_path(text_root, "d/a.csv")
    assert open_fd_count() == before
