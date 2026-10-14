"""``edit_file`` / ``read_text``: replace the content of an existing managed file atomically."""

from __future__ import annotations

import dataclasses
import logging
import os
import stat
import threading
from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import (
    ConflictError,
    SourceEditRefused,
    SourceNotFoundError,
    StorageError,
    UnsafeSourceError,
)
from sankey_studio.sources.files import paths, store
from sankey_studio.sources.files.store import FileEdit, edit_file, read_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

LIMIT = 1_000_000


@pytest.fixture
def root(tmp_path: Path) -> Path:
    directory = tmp_path / "sources"
    directory.mkdir()
    return directory


def req(
    root: Path, name: str = "a.csv", encoding: str = "utf-8", max_bytes: int = LIMIT
) -> FileEdit:
    return FileEdit(root, name, encoding, max_bytes)


def recording(seen: list[str], extra: str = "") -> Callable[[str], str]:
    """A rewrite that notes the text it was given and appends ``extra``."""

    def rewrite(text: str) -> str:
        seen.append(text)
        return text + extra

    return rewrite


def names(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


def test_the_request_is_a_frozen_value(root: Path) -> None:
    request = req(root)
    assert (request.sources_dir, request.name, request.encoding, request.max_bytes) == (
        root,
        "a.csv",
        "utf-8",
        LIMIT,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.name = "b.csv"  # type: ignore[misc]


def test_the_content_is_replaced_and_the_bytes_written_are_returned(root: Path) -> None:
    (root / "a.csv").write_bytes(b"a,b,1\n")
    written = edit_file(req(root), lambda text: text + "c,d,2\n")
    assert written == len(b"a,b,1\nc,d,2\n")
    assert (root / "a.csv").read_bytes() == b"a,b,1\nc,d,2\n"
    assert names(root) == ["a.csv"]  # no part file


def test_the_rewrite_sees_the_raw_line_endings(root: Path) -> None:
    (root / "a.csv").write_bytes(b"a,b,1\r\nc,d,2\rx\n")
    seen: list[str] = []
    edit_file(req(root), recording(seen))
    assert seen == ["a,b,1\r\nc,d,2\rx\n"]
    assert (root / "a.csv").read_bytes() == b"a,b,1\r\nc,d,2\rx\n"


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o644, 0o444])
def test_the_permission_bits_are_kept(root: Path, mode: int) -> None:
    leaf = root / "a.csv"
    leaf.write_bytes(b"x")
    leaf.chmod(mode)
    edit_file(req(root), lambda text: text + "y")
    assert stat.S_IMODE(leaf.stat().st_mode) == mode
    assert leaf.read_bytes() == b"xy"


def test_a_file_in_a_subdirectory_is_edited(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "sub" / "a.csv").write_bytes(b"x")
    edit_file(req(root, "sub/a.csv"), lambda text: text + "y")
    assert (root / "sub" / "a.csv").read_bytes() == b"xy"
    assert names(root / "sub") == ["a.csv"]


ENCODINGS = {
    "utf-8": (b"caf\xc3\xa9", "é"),
    "utf-8-sig": (b"\xef\xbb\xbfcaf\xc3\xa9", "é"),
    "utf-16": ("cafe".encode("utf-16"), "!"),
    "cp1252": (b"caf\xe9", "é"),
}


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_each_encoding_round_trips(root: Path, encoding: str) -> None:
    raw, extra = ENCODINGS[encoding]
    (root / "a.csv").write_bytes(raw)
    seen: list[str] = []
    edit_file(req(root, encoding=encoding), recording(seen, extra))
    stored = (root / "a.csv").read_bytes()
    assert stored.decode(encoding) == seen[0] + extra
    assert chr(0xFEFF) not in seen[0]  # the BOM is consumed by the decoder


def test_a_utf_16_file_gets_exactly_one_bom_again(root: Path) -> None:
    (root / "a.csv").write_bytes("abc".encode("utf-16"))
    for _ in range(2):
        edit_file(req(root, encoding="utf-16"), lambda text: text + "d")
    stored = (root / "a.csv").read_bytes()
    assert stored.decode("utf-16") == "abcdd"
    assert stored.count(b"\xff\xfe") + stored.count(b"\xfe\xff") == 1


def test_a_utf_8_sig_file_keeps_its_bom_and_does_not_double_it(root: Path) -> None:
    (root / "a.csv").write_bytes(b"\xef\xbb\xbfx")
    edit_file(req(root, encoding="utf-8-sig"), lambda text: text + "y")
    assert (root / "a.csv").read_bytes() == b"\xef\xbb\xbfxy"


def test_a_character_the_encoding_lacks_refuses_the_edit(root: Path) -> None:
    (root / "a.csv").write_bytes(b"caf\xe9")
    with pytest.raises(SourceEditRefused) as info:
        edit_file(req(root, encoding="cp1252"), lambda text: text + "\U0001f600")
    assert info.value.reason == "unrepresentable"
    assert (root / "a.csv").read_bytes() == b"caf\xe9"
    assert names(root) == ["a.csv"]  # no part file was ever opened


def test_a_refusal_of_the_rewrite_leaves_the_file_alone(root: Path) -> None:
    (root / "a.csv").write_bytes(b"x")

    def refuse(_text: str) -> str:
        raise SourceEditRefused("no_match")

    with pytest.raises(SourceEditRefused) as info:
        edit_file(req(root), refuse)
    assert info.value.reason == "no_match"
    assert names(root) == ["a.csv"]
    assert (root / "a.csv").read_bytes() == b"x"


@pytest.mark.parametrize(("size", "fits"), [(99, True), (100, True), (101, False)])
def test_the_size_cap_has_a_sharp_edge(root: Path, size: int, fits: bool) -> None:
    (root / "a.csv").write_bytes(b"x" * size)
    request = req(root, max_bytes=100)
    if fits:
        assert len(read_text(request)) == size
        return
    for call in (read_text, lambda r: edit_file(r, lambda text: text)):
        with pytest.raises(SourceEditRefused) as info:
            call(request)
        assert info.value.reason == "file_too_large"
    assert (root / "a.csv").read_bytes() == b"x" * size


def test_a_file_that_grew_after_the_size_check_is_still_capped(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "a.csv").write_bytes(b"x" * 200)
    real = paths.open_leaf
    monkeypatch.setattr(store, "open_leaf", lambda *a: real(*a)._replace(size=0))
    with pytest.raises(SourceEditRefused) as info:
        read_text(req(root, max_bytes=100))
    assert info.value.reason == "file_too_large"


@pytest.mark.parametrize(
    ("raw", "encoding"), [(b"\xff\xfe\x00", "utf-8"), (b"abc", "no-such-codec")]
)
def test_content_that_does_not_decode_is_unreadable(root: Path, raw: bytes, encoding: str) -> None:
    (root / "a.csv").write_bytes(raw)
    with pytest.raises(SourceEditRefused) as info:
        edit_file(req(root, encoding=encoding), lambda text: text)
    assert info.value.reason == "unreadable"
    assert (root / "a.csv").read_bytes() == raw


def test_a_read_error_is_unreadable(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "a.csv").write_bytes(b"x")

    def broken(_fd: int, _size: int) -> bytes:
        raise OSError("boom")

    monkeypatch.setattr(os, "read", broken)
    with pytest.raises(SourceEditRefused) as info:
        read_text(req(root))
    assert info.value.reason == "unreadable"


def test_read_text_decodes_without_touching_anything(root: Path) -> None:
    leaf = root / "a.csv"
    leaf.write_bytes(b"caf\xe9\r\n")
    before = leaf.stat()
    assert read_text(req(root, encoding="cp1252")) == "caf\xe9\r\n"
    after = leaf.stat()
    assert (before.st_ino, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_ino,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    assert names(root) == ["a.csv"]


# --------------------------------------------------------------------------- path rules


def test_a_symlinked_leaf_is_refused(root: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.csv").write_bytes(b"s")
    (root / "a.csv").symlink_to(tmp_path / "secret.csv")
    for call in (read_text, lambda r: edit_file(r, lambda text: text + "!")):
        with pytest.raises(UnsafeSourceError):
            call(req(root))
    assert (tmp_path / "secret.csv").read_bytes() == b"s"


def test_a_symlinked_parent_directory_is_refused(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.csv").write_bytes(b"s")
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafeSourceError):
        edit_file(req(root, "link/a.csv"), lambda text: text + "!")
    assert (outside / "a.csv").read_bytes() == b"s"


@pytest.mark.parametrize("name", ["a.exe", "a", "../a.csv", "sub/../a.csv", "/a.csv", "a\\b.csv"])
def test_names_outside_the_rules_are_refused(root: Path, name: str) -> None:
    with pytest.raises(UnsafeSourceError):
        edit_file(req(root, name), lambda text: text)


def test_a_missing_file_is_not_created(root: Path) -> None:
    with pytest.raises(SourceNotFoundError):
        edit_file(req(root), lambda text: text + "x")
    assert names(root) == []


def test_a_directory_and_a_fifo_are_not_files(root: Path) -> None:
    (root / "dir.csv").mkdir()
    os.mkfifo(root / "pipe.csv")
    for name in ("dir.csv", "pipe.csv"):
        with pytest.raises(UnsafeSourceError):
            edit_file(req(root, name), lambda text: text)
    assert names(root) == ["dir.csv", "pipe.csv"]


# --------------------------------------------------------------------------- failures


def test_a_file_changed_meanwhile_is_a_conflict_and_stays_as_the_other_writer_left_it(
    root: Path,
) -> None:
    leaf = root / "a.csv"
    leaf.write_bytes(b"one\n")

    def meanwhile(text: str) -> str:
        leaf.write_bytes(b"someone else wrote this\n")
        return text + "mine\n"

    with pytest.raises(ConflictError) as info:
        edit_file(req(root), meanwhile)
    assert str(info.value) == "The file changed while it was being edited"
    assert leaf.read_bytes() == b"someone else wrote this\n"
    assert names(root) == ["a.csv"]


def test_a_file_replaced_by_another_of_the_same_size_is_a_conflict(root: Path) -> None:
    leaf = root / "a.csv"
    leaf.write_bytes(b"one\n")

    def swap(text: str) -> str:
        other = root / "other.tmp"
        other.write_bytes(b"two\n")
        other.replace(leaf)
        return text + "mine\n"

    with pytest.raises(ConflictError):
        edit_file(req(root), swap)
    assert leaf.read_bytes() == b"two\n"
    assert names(root) == ["a.csv"]


def test_a_file_removed_meanwhile_is_a_conflict_and_not_recreated(root: Path) -> None:
    leaf = root / "a.csv"
    leaf.write_bytes(b"one\n")

    def remove(text: str) -> str:
        leaf.unlink()
        return text

    with pytest.raises(ConflictError):
        edit_file(req(root), remove)
    assert names(root) == []


@pytest.mark.parametrize("failing", ["replace", "fsync", "fchmod"])
def test_an_os_failure_is_a_storage_error_without_paths_and_leaves_no_part_file(
    root: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    (root / "a.csv").write_bytes(b"x")

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError(f"disk full at {root}")

    monkeypatch.setattr(os, failing, broken)
    with pytest.raises(StorageError) as info:
        edit_file(req(root), lambda text: text + "y")
    assert str(info.value) == "the file could not be written"
    assert str(root) not in str(info.value)
    monkeypatch.undo()
    assert names(root) == ["a.csv"]
    assert (root / "a.csv").read_bytes() == b"x"


def test_the_part_file_is_private_exclusive_and_not_followed(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "a.csv").write_bytes(b"x")
    calls: list[tuple[str, int, int]] = []
    real = os.open

    def spy(path: str, flags: int, mode: int = 0o777, **kwargs: int) -> int:
        calls.append((str(path), flags, mode))
        return real(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    edit_file(req(root), lambda text: text + "y")
    parts = [c for c in calls if c[0].endswith(".part")]
    assert len(parts) == 1
    path, flags, mode = parts[0]
    assert path.startswith(".")
    assert flags == store._PART_FLAGS
    assert flags & os.O_EXCL
    assert flags & os.O_NOFOLLOW
    assert flags & os.O_CREAT
    assert mode == 0o600


def test_the_data_is_synced_before_the_swap_and_the_directory_after(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "a.csv").write_bytes(b"x")
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        events.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        real_fsync(fd)

    def replace(src: str, dst: str, **kwargs: int) -> None:
        events.append("replace")
        real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    edit_file(req(root), lambda text: text + "y")
    assert events == ["fsync-file", "replace", "fsync-dir"]


def test_one_info_line_names_the_file_with_repr_and_the_size_only(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    name = "x\ny.csv"
    (root / name).write_bytes(b"secret")
    with caplog.at_level(logging.INFO, logger=store.logger.name):
        edit_file(req(root, name), lambda text: text + "!")
    assert [r.getMessage() for r in caplog.records] == ["source write: file='x\\ny.csv' bytes=7"]
    assert "secret" not in caplog.text


# --------------------------------------------------------------------------- concurrency


def test_two_writers_never_tear_the_file(root: Path) -> None:
    (root / "a.csv").write_bytes(b"base\n")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def work(tag: str) -> None:
        barrier.wait()
        try:
            edit_file(req(root), lambda text: text + tag * 5000 + "\n")
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(exc)

    workers = [threading.Thread(target=work, args=(tag,)) for tag in "ab"]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert errors == []
    lines = (root / "a.csv").read_text(encoding="utf-8").split("\n")
    assert lines[0] == "base"
    assert sorted(lines[1:3]) == ["a" * 5000, "b" * 5000]
    assert lines[3:] == [""]
    assert names(root) == ["a.csv"]
