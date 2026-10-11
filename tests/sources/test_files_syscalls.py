"""The exact arguments the managed-files store hands to the standard library.

These flags (no symlink following, lenient UTF-8 for previews) are indistinguishable from
their defaults on an ordinary directory, so the calls are recorded and compared whole.
"""

from __future__ import annotations

import io
import os
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.sources.files import (
    SaveRequest,
    list_files,
    preview_file,
    resolve_source_path,
    save_stream,
)
from tests.sources.text_support import record

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def save(root: Path) -> None:
    save_stream(SaveRequest(root, "a.csv", 100), io.BytesIO(b"x"))


def test_listing_never_follows_symlinked_directories(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (text_root / "a.csv").write_text("x", encoding="utf-8")
    calls = record(monkeypatch, os, "walk")
    assert [info.name for info in list_files(text_root)] == ["a.csv"]
    assert calls == [{"followlinks": False}]


def test_a_preview_is_decoded_as_utf_8_with_replacement(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (text_root / "a.csv").write_bytes(b"ok\xff\n")
    calls = record(monkeypatch, io, "TextIOWrapper")
    assert preview_file(text_root, "a.csv") == ["ok�"]
    assert calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_publishing_links_the_part_file_itself_never_what_it_points_to(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record(monkeypatch, os, "link")
    save(text_root)
    (kwargs,) = calls
    assert kwargs.keys() == {"src_dir_fd", "dst_dir_fd", "follow_symlinks"}
    assert kwargs["src_dir_fd"] == kwargs["dst_dir_fd"]
    assert kwargs["follow_symlinks"] is False


def test_the_stored_file_is_measured_without_following_symlinks(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record(monkeypatch, os, "stat")
    save(text_root)
    (kwargs,) = [call for call in calls if "dir_fd" in call]
    assert kwargs.keys() == {"dir_fd", "follow_symlinks"}
    assert kwargs["follow_symlinks"] is False


ROOT_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
PART_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def opens(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    """Record the arguments of every ``os.open``."""
    real = os.open
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def spy(*args: Any, **kwargs: Any) -> int:
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    return calls


def test_a_path_is_walked_with_the_flags_that_refuse_symlinks(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (text_root / "sub").mkdir()
    (text_root / "sub" / "f.csv").write_text("x", encoding="utf-8")
    calls = opens(monkeypatch)
    resolve_source_path(text_root, "sub/f.csv")
    assert [args for args, _ in calls] == [
        (text_root, ROOT_FLAGS),
        ("sub", DIR_FLAGS),
        ("f.csv", FILE_FLAGS),
    ]
    assert [kwargs.keys() for _, kwargs in calls] == [{"dir_fd"}] * 3
    assert calls[0][1]["dir_fd"] is None
    assert calls[1][1]["dir_fd"] != calls[2][1]["dir_fd"]


def test_an_upload_is_written_through_an_exclusive_private_descriptor(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = opens(monkeypatch)
    save(text_root)
    (root_call, part_call) = calls
    assert root_call == ((text_root, ROOT_FLAGS), {})
    part_args, part_kwargs = part_call
    assert part_args[1:] == (PART_FLAGS, 0o600)
    assert part_args[0].startswith(".")
    assert part_args[0].endswith(".part")
    assert part_kwargs.keys() == {"dir_fd"}
