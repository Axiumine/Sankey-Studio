# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``save_stream``: the publish step is serialised per directory (case variants cannot race)."""

from __future__ import annotations

import errno
import fcntl
import io
import os
import threading
from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import ConflictError
from sankey_studio.sources.files import SaveRequest, list_files, save_stream

if TYPE_CHECKING:
    from pathlib import Path

LIMIT = 1_000_000


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def save(root: Path, filename: str, *, overwrite: bool = False) -> str:
    request = SaveRequest(root, filename, LIMIT, overwrite)
    return save_stream(request, io.BytesIO(filename.encode())).name


def test_the_publish_takes_an_exclusive_lock_on_the_directory(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[bool, int]] = []
    real = fcntl.flock

    def spy(fd: int, operation: int) -> None:
        is_root = os.path.samestat(os.fstat(fd), text_root.stat())
        calls.append((is_root, operation))
        real(fd, operation)

    monkeypatch.setattr("sankey_studio.sources.files.store.fcntl.flock", spy)
    save(text_root, "a.csv")
    save(text_root, "b.csv", overwrite=True)
    assert calls == [(True, fcntl.LOCK_EX), (True, fcntl.LOCK_EX)]


def test_a_publish_waits_while_another_process_holds_the_directory(text_root: Path) -> None:
    done = threading.Event()
    stored: list[str] = []

    def upload() -> None:
        stored.append(save(text_root, "waits.csv"))
        done.set()

    holder = os.open(text_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        worker = threading.Thread(target=upload)
        worker.start()
        assert not done.wait(0.3)  # blocked at the publish
        assert not (text_root / "waits.csv").exists()
        fcntl.flock(holder, fcntl.LOCK_UN)
        assert done.wait(10)
    finally:
        os.close(holder)
    worker.join()
    assert stored == ["waits.csv"]
    assert (text_root / "waits.csv").read_bytes() == b"waits.csv"


def test_a_filesystem_without_flock_still_stores_the_upload(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_fd: int, _operation: int) -> None:
        raise OSError(errno.ENOTSUP, "flock is not supported here")

    monkeypatch.setattr("sankey_studio.sources.files.store.fcntl.flock", refuse)
    assert save(text_root, "a.csv") == "a.csv"
    with pytest.raises(ConflictError) as info:
        save(text_root, "A.csv")
    assert str(info.value) == "a file named 'a.csv' already exists"
    assert [item.name for item in list_files(text_root)] == ["a.csv"]


def race(root: Path, names: tuple[str, str]) -> list[str]:
    """Upload both names at once; each worker reports its outcome."""
    barrier = threading.Barrier(len(names))
    outcomes: list[str] = []
    guard = threading.Lock()

    def upload(name: str) -> None:
        barrier.wait()
        try:
            save(root, name)
            outcome = f"ok {name}"
        except ConflictError as exc:
            outcome = f"conflict {exc}"
        with guard:
            outcomes.append(outcome)

    workers = [threading.Thread(target=upload, args=(name,)) for name in names]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return outcomes


def test_case_variants_uploaded_at_once_never_both_land(tmp_path: Path) -> None:
    for attempt in range(40):  # without the lock about a third of the attempts stored both
        root = tmp_path / f"run{attempt}"
        root.mkdir()
        outcomes = race(root, ("A.csv", "a.csv"))
        winners = [text for text in outcomes if text.startswith("ok ")]
        losers = [text for text in outcomes if text.startswith("conflict ")]
        assert len(winners) == 1
        assert len(losers) == 1
        (stored,) = root.iterdir()
        assert stored.name == winners[0].removeprefix("ok ")
        assert losers[0] == f"conflict a file named '{stored.name}' already exists"
