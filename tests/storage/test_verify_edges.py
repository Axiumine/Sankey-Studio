"""Edges a mutation sweep of the storage layer found unpinned: texts and interrupt cleanup."""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.config import BootstrapConfig
from sankey_studio.errors import ReadOnlyModeError
from sankey_studio.models import AppSettings
from sankey_studio.services import MSG_READ_ONLY, Services
from sankey_studio.storage import FileGraphRepository
from sankey_studio.storage.atomic import (
    check_writable,
    fsync_dir,
    read_file_nofollow,
    write_atomic,
)
from tests.storage.mongo_fakes import Hub
from tests.storage.support import ID_A, ID_B, ID_C, definition

if TYPE_CHECKING:
    from collections.abc import Callable

    from pymongo.collection import Collection

    from sankey_studio.mongo import MongoClients
    from sankey_studio.storage import MongoGraphRepository

READ_ONLY = "Settings cannot be changed in read-only remote mode (--allow-remote-writes)"


class _Names:
    """A ``token_hex`` stand-in that always answers the same name."""

    def __call__(self, _nbytes: int) -> str:
        return "dead"


def _interrupt() -> Callable[..., None]:
    def stop(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    return stop


def test_the_read_only_message_is_exact(tmp_path: Path) -> None:
    assert MSG_READ_ONLY == READ_ONLY
    config = BootstrapConfig(data_dir=tmp_path / "data", remote_mode=True)
    services = Services.create(config, mongo_factory=Hub())
    with pytest.raises(ReadOnlyModeError) as info:
        services.update_settings(AppSettings())
    assert info.value.message == READ_ONLY
    services.close()


def test_the_exhausted_name_error_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".f.json.dead.tmp").write_text("taken")
    monkeypatch.setattr("sankey_studio.storage.atomic.secrets.token_hex", _Names())
    with pytest.raises(FileExistsError) as info:
        write_atomic(tmp_path / "f.json", b"data")
    assert info.value.strerror == "no free temporary file name"


def test_an_interrupt_mid_write_still_removes_the_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.json"
    write_atomic(target, b"old")
    monkeypatch.setattr("sankey_studio.storage.atomic.os.fsync", _interrupt())
    with pytest.raises(KeyboardInterrupt):
        write_atomic(target, b"new")
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


def test_files_that_are_not_graphs_are_ignored_without_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    graphs = tmp_path / "graphs"
    repo = FileGraphRepository(graphs)
    repo.put(definition(ID_A, "real"))
    (graphs / f"{ID_B}.json").symlink_to(tmp_path / "nowhere")
    (graphs / f"{ID_C}.json").mkdir()
    os.mkfifo(graphs / f"{'d' * 32}.json")
    with caplog.at_level(logging.WARNING):
        assert [row.id for row in repo.list_graphs()] == [ID_A]
        assert repo.count() == 1
    assert caplog.records == []


FD_DIR = Path("/proc/self/fd")


def _open_fds() -> int:
    return len(list(FD_DIR.iterdir()))


def _refuse_replace(*_args: object, **_kwargs: object) -> None:
    raise PermissionError(errno.EACCES, "denied")


def _one_round(directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_atomic(directory / "f.json", b"data")
    read_file_nofollow(directory / "f.json", 100)
    check_writable(directory)
    fsync_dir(directory)
    with pytest.raises(OSError, match="too large"):
        read_file_nofollow(directory / "f.json", 2)
    with pytest.raises(OSError, match="not a regular file"):
        read_file_nofollow(_fifo(directory), 100)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", _refuse_replace)
        with pytest.raises(PermissionError):
            write_atomic(directory / "f.json", b"new")


def _fifo(directory: Path) -> Path:
    fifo = directory / "pipe"
    if not fifo.exists():
        os.mkfifo(fifo)
    return fifo


@pytest.mark.skipif(not FD_DIR.exists(), reason="needs /proc to count open file descriptors")
def test_no_file_descriptor_leaks_on_any_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _one_round(tmp_path, monkeypatch)  # warm up lazy imports
    before = _open_fds()
    for _ in range(10):
        _one_round(tmp_path, monkeypatch)
    assert _open_fds() == before


def test_the_data_is_flushed_before_the_file_is_fsynced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes: list[int] = []
    real_fsync = os.fsync

    def recording(fd: int) -> None:
        sizes.append(os.fstat(fd).st_size)
        real_fsync(fd)

    monkeypatch.setattr("sankey_studio.storage.atomic.os.fsync", recording)
    write_atomic(tmp_path / "f.json", b"0123456789")
    assert sizes[0] == 10  # the file fsync comes first, the directory fsync second
    assert len(sizes) == 2


@pytest.mark.parametrize("overwrite", [False, True], ids=["insert", "replace"])
def test_a_put_as_the_first_write_creates_the_indexes(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any], overwrite: bool
) -> None:
    mongo_repo.put(definition(ID_A, "first"), overwrite=overwrite)
    assert set(mongo_collection.index_information()) == {"_id_", "updated_at_1", "tags_1"}


def test_the_repository_ping_asks_the_server_about_the_storage_connection(
    mongo_repo: MongoGraphRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def record(_self: MongoClients, connection: str) -> float:
        asked.append(connection)
        return 0.0

    monkeypatch.setattr("sankey_studio.mongo.MongoClients.ping", record)
    mongo_repo.ping()
    assert asked == ["test"]
