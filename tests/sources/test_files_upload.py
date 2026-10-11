"""``save_stream``: the happy path, collisions (casefolded), overwrite, size cap and races."""

from __future__ import annotations

import io
import os
import stat
import threading
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import ConflictError, PayloadTooLargeError, SourceError, UnsafeSourceError
from sankey_studio.sources.files import SaveRequest, SourceFileInfo, list_files, save_stream
from sankey_studio.sources.files.store import CHUNK_BYTES, PART_MODE, PART_SUFFIX
from tests.sources.idtools import safe_id

if TYPE_CHECKING:
    from pathlib import Path

LIMIT = 1_000_000


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    return tmp_path / "sources"


def request(
    root: Path, filename: str, *, overwrite: bool = False, max_bytes: int = LIMIT
) -> SaveRequest:
    return SaveRequest(root, filename, max_bytes, overwrite)


def save(root: Path, filename: str, data: bytes, **options: Any) -> SourceFileInfo:
    return save_stream(request(root, filename, **options), io.BytesIO(data))


def test_save_request_defaults(tmp_path: Path) -> None:
    req = SaveRequest(tmp_path, "a.csv", 10)
    assert req.overwrite is False
    assert (req.sources_dir, req.filename, req.max_bytes) == (tmp_path, "a.csv", 10)


def test_the_constants() -> None:
    assert CHUNK_BYTES == 1024 * 1024
    assert PART_MODE == 0o600
    assert PART_SUFFIX == ".part"


def test_a_save_stores_the_bytes_and_reports_them(text_root: Path) -> None:
    info = save(text_root, "flows.csv", b"source,target,value\na,b,1\n")
    assert info.name == "flows.csv"
    assert info.size == len(b"source,target,value\na,b,1\n")
    assert info.modified.tzinfo is not None
    assert (text_root / "flows.csv").read_bytes() == b"source,target,value\na,b,1\n"
    assert list_files(text_root) == [info]


def test_the_stored_file_is_private_and_regular(text_root: Path) -> None:
    save(text_root, "a.csv", b"x")
    mode = (text_root / "a.csv").stat().st_mode
    assert stat.S_ISREG(mode)
    assert stat.S_IMODE(mode) == 0o600


def test_a_missing_sources_directory_is_created_private(text_root: Path) -> None:
    nested = text_root / "deeper" / "still"
    save(nested, "a.csv", b"x")
    assert stat.S_IMODE(nested.stat().st_mode) == 0o700
    assert (nested / "a.csv").exists()


def test_no_temporary_file_is_left_behind(text_root: Path) -> None:
    save(text_root, "a.csv", b"x" * 10)
    save(text_root, "a.csv", b"y" * 10, overwrite=True)
    assert sorted(p.name for p in text_root.iterdir()) == ["a.csv"]


def test_the_name_is_cleaned_before_it_is_used(text_root: Path) -> None:
    info = save(text_root, "..sneaky.CSV", b"x")
    assert info.name == "sneaky.CSV"
    assert (text_root / "sneaky.CSV").exists()


def test_large_uploads_are_copied_in_chunks(text_root: Path) -> None:
    data = os.urandom(CHUNK_BYTES * 2 + 12345)
    info = save(text_root, "big.csv", data, max_bytes=len(data))
    assert info.size == len(data)
    assert (text_root / "big.csv").read_bytes() == data


def test_the_data_is_on_disk_before_the_fsync(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes: list[int] = []
    real = os.fsync

    def spy(fd: int) -> None:
        sizes.append(os.fstat(fd).st_size)
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    save(text_root, "a.csv", b"abc")
    assert sizes == [3]


def test_the_stream_is_read_in_one_mebibyte_chunks(text_root: Path) -> None:
    sizes: list[int] = []

    class Spy(io.BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            sizes.append(-1 if size is None else size)
            return super().read(size)

    save_stream(request(text_root, "a.csv"), Spy(b"abc"))
    assert sizes == [CHUNK_BYTES, CHUNK_BYTES]


class Cap(NamedTuple):
    size: int
    fits: bool


@pytest.mark.parametrize(
    "case", [Cap(99, True), Cap(100, True), Cap(101, False)], ids=["99", "100", "101"]
)
def test_max_bytes_boundary(text_root: Path, case: Cap) -> None:
    data = b"x" * case.size
    if case.fits:
        assert save(text_root, "a.csv", data, max_bytes=100).size == case.size
        return
    with pytest.raises(PayloadTooLargeError) as info:
        save(text_root, "a.csv", data, max_bytes=100)
    assert str(info.value) == "the upload is larger than the limit of 100 bytes"
    assert list(text_root.iterdir()) == []  # neither the file nor a temporary one


def test_the_cap_applies_across_chunks(text_root: Path) -> None:
    data = b"x" * (CHUNK_BYTES + 1)
    with pytest.raises(PayloadTooLargeError):
        save(text_root, "a.csv", data, max_bytes=CHUNK_BYTES)
    assert list(text_root.iterdir()) == []
    assert save(text_root, "a.csv", data, max_bytes=CHUNK_BYTES + 1).size == CHUNK_BYTES + 1


def test_a_too_large_upload_keeps_the_existing_file(text_root: Path) -> None:
    save(text_root, "a.csv", b"old")
    with pytest.raises(PayloadTooLargeError):
        save(text_root, "a.csv", b"x" * 200, overwrite=True, max_bytes=100)
    assert (text_root / "a.csv").read_bytes() == b"old"
    assert sorted(p.name for p in text_root.iterdir()) == ["a.csv"]


class Clash(NamedTuple):
    first: str
    second: str
    existing: str


CLASHES = [
    Clash("a.csv", "a.csv", "a.csv"),
    Clash("a.csv", "A.csv", "a.csv"),
    Clash("A.csv", "a.csv", "A.csv"),
    Clash("Report.CSV", "report.csv", "Report.CSV"),
    Clash("\u00c4.csv", "\u00e4.csv", "\u00c4.csv"),
    Clash("stra\u00dfe.csv", "STRASSE.csv", "stra\u00dfe.csv"),  # casefold, not lower()
]


@pytest.mark.parametrize("case", CLASHES, ids=[safe_id(f"{c.first}-{c.second}") for c in CLASHES])
def test_a_name_that_exists_casefolded_is_a_conflict(text_root: Path, case: Clash) -> None:
    save(text_root, case.first, b"first")
    with pytest.raises(ConflictError) as info:
        save(text_root, case.second, b"second")
    assert str(info.value) == f"a file named '{case.existing}' already exists"
    assert info.value.status_code == 409
    assert (text_root / case.first).read_bytes() == b"first"
    assert [p.name for p in text_root.iterdir()] == [case.first]


def test_overwrite_replaces_the_content(text_root: Path) -> None:
    save(text_root, "a.csv", b"old")
    info = save(text_root, "a.csv", b"new!", overwrite=True)
    assert info == SourceFileInfo("a.csv", 4, info.modified)
    assert (text_root / "a.csv").read_bytes() == b"new!"


def test_overwrite_of_a_differently_cased_name_keeps_the_stored_spelling(text_root: Path) -> None:
    save(text_root, "Report.csv", b"old")
    info = save(text_root, "report.CSV", b"new", overwrite=True)
    assert info.name == "Report.csv"
    assert [p.name for p in text_root.iterdir()] == ["Report.csv"]
    assert (text_root / "Report.csv").read_bytes() == b"new"


def test_overwrite_without_an_existing_file_just_saves(text_root: Path) -> None:
    info = save(text_root, "fresh.csv", b"x", overwrite=True)
    assert info.name == "fresh.csv"


def test_an_exact_match_wins_over_a_casefolded_one(text_root: Path) -> None:
    text_root.mkdir()
    (text_root / "A.csv").write_bytes(b"upper")
    (text_root / "a.csv").write_bytes(b"lower")
    info = save(text_root, "a.csv", b"new", overwrite=True)
    assert info.name == "a.csv"
    assert (text_root / "a.csv").read_bytes() == b"new"
    assert (text_root / "A.csv").read_bytes() == b"upper"
    with pytest.raises(ConflictError, match=r"'a\.csv' already exists"):
        save(text_root, "a.csv", b"again")


def test_a_directory_in_the_way_is_a_conflict(text_root: Path) -> None:
    (text_root / "a.csv").mkdir(parents=True)
    with pytest.raises(ConflictError, match=r"'a\.csv' already exists"):
        save(text_root, "a.csv", b"x")


def test_bad_names_fail_before_the_disk_is_touched(tmp_path: Path) -> None:
    root = tmp_path / "never-created"
    with pytest.raises(UnsafeSourceError):
        save(root, "../x.csv", b"x")
    with pytest.raises(UnsafeSourceError):
        save(root, "x.exe", b"x")
    with pytest.raises(SourceError):
        save(root, "x\u202e.csv", b"x")
    assert not root.exists()


def test_losing_the_race_at_the_link_is_a_conflict(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save(text_root, "a.csv", b"first")
    monkeypatch.setattr("sankey_studio.sources.files.store._existing_name", lambda _fd, _name: None)
    with pytest.raises(ConflictError) as info:
        save(text_root, "a.csv", b"second")
    assert str(info.value) == "a file named 'a.csv' already exists"
    assert (text_root / "a.csv").read_bytes() == b"first"
    assert [p.name for p in text_root.iterdir()] == ["a.csv"]


def test_concurrent_uploads_of_one_name_have_exactly_one_winner(text_root: Path) -> None:
    text_root.mkdir()
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[str] = []
    lock = threading.Lock()

    def upload(index: int) -> None:
        barrier.wait()
        try:
            save(text_root, "same.csv", f"writer {index}".encode())
            outcome = "ok"
        except ConflictError:
            outcome = "conflict"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["conflict"] * (workers - 1) + ["ok"]
    (stored,) = text_root.iterdir()
    assert stored.name == "same.csv"
    assert stored.read_bytes().startswith(b"writer ")


def test_the_temporary_name_is_random_hidden_and_exclusive(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[int] = []

    def token(nbytes: int) -> str:
        asked.append(nbytes)
        return "feedfacefeedface"

    monkeypatch.setattr("sankey_studio.sources.files.store.secrets.token_hex", token)
    text_root.mkdir()
    (text_root / ".feedfacefeedface.part").write_bytes(b"squatter")
    with pytest.raises(Exception, match="could not be stored") as info:
        save(text_root, "a.csv", b"x")
    assert type(info.value).__name__ == "StorageError"
    assert asked == [8]
    assert (text_root / ".feedfacefeedface.part").read_bytes() == b"squatter"
    assert not (text_root / "a.csv").exists()
