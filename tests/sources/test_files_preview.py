# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``preview_file`` and ``delete_file``."""

from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import SourceNotFoundError, StorageError, UnsafeSourceError
from sankey_studio.sources.files import delete_file, preview_file
from sankey_studio.sources.files.store import PREVIEW_LINE_MAX, PREVIEW_TOTAL_MAX
from tests.sources.text_support import open_fd_count

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def touch(root: Path, rel: str, data: bytes | str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    return path


def test_the_limits() -> None:
    assert PREVIEW_LINE_MAX == 500
    assert PREVIEW_TOTAL_MAX == 64 * 1024


class Lines(NamedTuple):
    max_lines: int | None
    expected: list[str]


NUMBERED = "".join(f"line {i}\n" for i in range(1, 101))
LINE_COUNTS = [
    Lines(None, [f"line {i}" for i in range(1, 51)]),  # the default is 50
    Lines(1, ["line 1"]),
    Lines(3, ["line 1", "line 2", "line 3"]),
    Lines(0, []),
    Lines(-5, []),
    Lines(100, [f"line {i}" for i in range(1, 101)]),
    Lines(1000, [f"line {i}" for i in range(1, 101)]),
]


@pytest.mark.parametrize("case", LINE_COUNTS, ids=[str(c.max_lines) for c in LINE_COUNTS])
def test_max_lines(text_root: Path, case: Lines) -> None:
    touch(text_root, "a.csv", NUMBERED)
    if case.max_lines is None:
        assert preview_file(text_root, "a.csv") == case.expected
    else:
        assert preview_file(text_root, "a.csv", case.max_lines) == case.expected


def test_newlines_are_normalised_and_the_last_line_needs_no_newline(text_root: Path) -> None:
    touch(text_root, "a.csv", b"a,b\r\nc,d\re,f\n\ng,h")
    assert preview_file(text_root, "a.csv") == ["a,b", "c,d", "e,f", "", "g,h"]


def test_an_empty_file_previews_as_nothing(text_root: Path) -> None:
    touch(text_root, "a.csv", b"")
    assert preview_file(text_root, "a.csv") == []


def test_a_byte_order_mark_is_not_shown(text_root: Path) -> None:
    touch(text_root, "a.csv", b"\xef\xbb\xbfsource,target\nx,y\n")
    assert preview_file(text_root, "a.csv") == ["source,target", "x,y"]


class Cut(NamedTuple):
    length: int
    shown: int


@pytest.mark.parametrize(
    "case",
    [Cut(499, 499), Cut(500, 500), Cut(501, 500), Cut(5000, 500), Cut(200_000, 500)],
    ids=str,
)
def test_a_line_is_cut_at_500_characters(text_root: Path, case: Cut) -> None:
    touch(text_root, "a.csv", "x" * case.length + "\nnext\n")
    assert preview_file(text_root, "a.csv") == ["x" * case.shown, "next"]


def test_the_preview_is_64_kib_at_most(text_root: Path) -> None:
    touch(text_root, "a.csv", ("y" * 500 + "\n") * 400)
    shown = preview_file(text_root, "a.csv", max_lines=10_000)
    assert sum(len(line) for line in shown) == 64 * 1024
    assert len(shown) == 132  # 131 full lines and the 132nd cut at the budget
    assert shown[:131] == ["y" * 500] * 131
    assert shown[131] == "y" * (64 * 1024 - 131 * 500)


def test_the_budget_ends_exactly_on_a_line_boundary(text_root: Path) -> None:
    line = "z" * 255  # 256 lines of 255 characters = 65280; one more of 256 fills 65536
    touch(text_root, "a.csv", (line + "\n") * 256 + "w" * 256 + "\nextra\n")
    shown = preview_file(text_root, "a.csv", max_lines=10_000)
    assert sum(len(item) for item in shown) == 64 * 1024
    assert shown[-1] == "w" * 256
    assert len(shown) == 257
    assert "extra" not in shown


def test_a_single_character_of_budget_is_still_used(text_root: Path) -> None:
    body = ("y" * 500 + "\n") * 131 + "x" * 35 + "\nzz\nlast\n"  # 65500 + 35 = 65535 so far
    touch(text_root, "a.csv", body)
    shown = preview_file(text_root, "a.csv", max_lines=10_000)
    assert sum(len(line) for line in shown) == 64 * 1024
    assert shown[-2:] == ["x" * 35, "z"]


def test_nothing_is_added_when_the_budget_is_spent(text_root: Path) -> None:
    touch(text_root, "a.csv", ("q" * 256 + "\n") * 256 + "after\n")  # exactly 65536
    shown = preview_file(text_root, "a.csv", max_lines=10_000)
    assert len(shown) == 256
    assert "after" not in shown


def test_binary_garbage_is_shown_with_replacement_characters(text_root: Path) -> None:
    touch(text_root, "a.csv", b"ok\n\xff\xfe,b\n")
    assert preview_file(text_root, "a.csv") == ["ok", "\ufffd\ufffd,b"]


def test_the_preview_applies_every_path_check(text_root: Path, tmp_path: Path) -> None:
    secret = touch(tmp_path, "secret.csv")
    (text_root / "link.csv").symlink_to(secret)
    touch(text_root, "a.exe")
    os.mkfifo(text_root / "pipe.csv")
    with pytest.raises(UnsafeSourceError):
        preview_file(text_root, "link.csv")
    with pytest.raises(UnsafeSourceError):
        preview_file(text_root, "a.exe")
    with pytest.raises(UnsafeSourceError):
        preview_file(text_root, "../secret.csv")
    with pytest.raises(UnsafeSourceError):
        preview_file(text_root, "pipe.csv")
    with pytest.raises(SourceNotFoundError):
        preview_file(text_root, "missing.csv")


def test_a_preview_closes_its_file(text_root: Path) -> None:
    touch(text_root, "a.csv", NUMBERED)
    before = open_fd_count()
    preview_file(text_root, "a.csv")
    assert open_fd_count() == before


def test_a_large_file_is_not_read_to_the_end(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch(text_root, "a.csv", "line\n" * 1_000_000)
    reads: list[int] = []
    real = os.read

    def counting(fd: int, size: int) -> bytes:
        data = real(fd, size)
        reads.append(len(data))
        return data

    monkeypatch.setattr(os, "read", counting)
    assert preview_file(text_root, "a.csv", 3) == ["line"] * 3
    assert sum(reads) < 100_000


# --------------------------------------------------------------------------- delete


def test_delete_removes_the_file_and_only_that_file(text_root: Path) -> None:
    touch(text_root, "a.csv")
    touch(text_root, "b.csv")
    touch(text_root, "d/c.csv")
    delete_file(text_root, "a.csv")
    delete_file(text_root, "d/c.csv")
    assert sorted(p.name for p in text_root.rglob("*") if p.is_file()) == ["b.csv"]
    assert (text_root / "d").is_dir()


def test_delete_of_a_missing_file_is_not_found(text_root: Path) -> None:
    with pytest.raises(SourceNotFoundError) as info:
        delete_file(text_root, "gone.csv")
    assert str(info.value) == "gone.csv: no such file or directory"


def test_delete_applies_every_path_check(text_root: Path, tmp_path: Path) -> None:
    secret = touch(tmp_path, "secret.csv")
    (text_root / "link.csv").symlink_to(secret)
    (text_root / "dir.csv").mkdir()
    touch(text_root, "a.exe")
    for rel in ("link.csv", "dir.csv", "a.exe", "../secret.csv", "/etc/passwd", "d//a.csv"):
        with pytest.raises(UnsafeSourceError):
            delete_file(text_root, rel)
    assert secret.exists()
    assert (text_root / "link.csv").is_symlink()
    assert (text_root / "dir.csv").is_dir()
    assert (text_root / "a.exe").exists()


def test_delete_through_a_symlinked_directory_is_refused(text_root: Path, tmp_path: Path) -> None:
    victim = touch(tmp_path / "outside", "a.csv")
    (text_root / "d").symlink_to(tmp_path / "outside")
    with pytest.raises(UnsafeSourceError):
        delete_file(text_root, "d/a.csv")
    assert victim.exists()


def test_delete_closes_its_descriptors(text_root: Path) -> None:
    touch(text_root, "d/a.csv")
    before = open_fd_count()
    delete_file(text_root, "d/a.csv")
    assert open_fd_count() == before


def test_a_file_that_vanishes_before_the_unlink_is_not_found(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch(text_root, "a.csv")
    seen: dict[str, object] = {}

    def vanished(path: str, *, dir_fd: int | None = None) -> None:
        seen.update(path=path, dir_fd_given=dir_fd is not None)
        raise FileNotFoundError(path)

    monkeypatch.setattr(os, "unlink", vanished)
    with pytest.raises(SourceNotFoundError, match=r"^a\.csv: no such file or directory$"):
        delete_file(text_root, "a.csv")
    assert seen == {"path": "a.csv", "dir_fd_given": True}


def test_an_unlink_failure_is_a_storage_error(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch(text_root, "a.csv")

    def denied(_path: str, **_kwargs: object) -> None:
        raise PermissionError(errno.EACCES, "secret detail")

    monkeypatch.setattr(os, "unlink", denied)
    with pytest.raises(StorageError) as info:
        delete_file(text_root, "a.csv")
    assert str(info.value) == "a.csv: could not be deleted"
