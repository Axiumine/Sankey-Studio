"""``list_files``: filters, depth, symlinks, ordering and what the entries say."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sankey_studio.sources.files import ALLOWED_EXTENSIONS, SourceFileInfo, list_files
from sankey_studio.sources.files.paths import split_relative
from sankey_studio.sources.files.store import MAX_DEPTH


@pytest.fixture
def text_root(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    root.mkdir()
    return root


def touch(root: Path, rel: str, data: str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path


def names(root: Path) -> list[str]:
    return [info.name for info in list_files(root)]


def test_an_empty_or_missing_directory_lists_nothing(text_root: Path, tmp_path: Path) -> None:
    assert list_files(text_root) == []
    assert list_files(tmp_path / "absent") == []


def test_each_allowed_extension_in_both_cases_is_listed(text_root: Path) -> None:
    for ext in ALLOWED_EXTENSIONS:
        touch(text_root, f"low{ext}")
        touch(text_root, f"UP{ext.upper()}")
    expected = sorted(
        [f"low{ext}" for ext in ALLOWED_EXTENSIONS]
        + [f"UP{ext.upper()}" for ext in ALLOWED_EXTENSIONS],
        key=lambda name: (name.casefold(), name),
    )
    assert names(text_root) == expected


def test_other_files_are_not_listed(text_root: Path) -> None:
    for rel in ("a.exe", "noext", "a.csv.bak", ".x.part", "script.py", "a.csvx", ".csv"):
        touch(text_root, rel)
    touch(text_root, "keep.csv")
    assert names(text_root) == ["keep.csv"]


def test_the_listing_is_sorted_casefolded_then_exact(text_root: Path) -> None:
    for rel in ("b.csv", "A.csv", "a.csv", "B.csv", "c/z.csv", "c/a.csv", "0.csv"):
        touch(text_root, rel)
    assert names(text_root) == ["0.csv", "A.csv", "a.csv", "B.csv", "b.csv", "c/a.csv", "c/z.csv"]


def test_casefolded_order_puts_the_underscore_between_upper_and_lower_case_letters(
    text_root: Path,
) -> None:
    for rel in ("_b.csv", "a.csv", "B.csv", "Z.csv"):
        touch(text_root, rel)
    assert names(text_root) == ["_b.csv", "a.csv", "B.csv", "Z.csv"]


def test_names_are_posix_relative_paths(text_root: Path) -> None:
    touch(text_root, "top.csv")
    touch(text_root, "d/e/deep.tsv")
    assert names(text_root) == ["d/e/deep.tsv", "top.csv"]


def test_depth_three_is_listed_and_depth_four_is_not(text_root: Path) -> None:
    assert MAX_DEPTH == 3
    touch(text_root, "d0.csv")
    touch(text_root, "a/d1.csv")
    touch(text_root, "a/b/d2.csv")
    touch(text_root, "a/b/c/d3.csv")
    touch(text_root, "a/b/c/d/d4.csv")
    touch(text_root, "a/b/c/d/e/d5.csv")
    assert names(text_root) == ["a/b/c/d3.csv", "a/b/d2.csv", "a/d1.csv", "d0.csv"]


def test_symlinks_are_skipped(text_root: Path, tmp_path: Path) -> None:
    real = touch(tmp_path, "outside.csv")
    outside_dir = tmp_path / "outside_dir"
    touch(outside_dir, "inner.csv")
    touch(text_root, "real.csv")
    (text_root / "link.csv").symlink_to(real)
    (text_root / "dirlink").symlink_to(outside_dir)
    (text_root / "dangling.csv").symlink_to(tmp_path / "nowhere.csv")
    assert names(text_root) == ["real.csv"]


def test_a_fifo_and_a_directory_with_a_file_name_are_skipped(text_root: Path) -> None:
    os.mkfifo(text_root / "pipe.csv")
    (text_root / "dir.csv").mkdir()
    touch(text_root, "real.csv")
    assert names(text_root) == ["real.csv"]


def test_a_file_name_that_is_not_text_is_skipped(text_root: Path) -> None:
    bad = os.fsencode(text_root) + b"/caf\xe9.csv"
    Path(os.fsdecode(bad)).write_bytes(b"x")
    touch(text_root, "good.csv")
    assert names(text_root) == ["good.csv"]


@pytest.mark.parametrize("rel", ["a\\b.csv", "dir\\x/f.csv", "sub/a\\b.csv", "\\.csv"])
def test_a_name_with_a_backslash_is_skipped_because_preview_and_delete_refuse_it(
    text_root: Path, rel: str
) -> None:
    touch(text_root, rel)
    touch(text_root, "good.csv")
    assert names(text_root) == ["good.csv"]


def test_every_listed_name_is_accepted_by_split_relative(text_root: Path) -> None:
    for rel in ("a b.csv", "sub/caf\u00e9.csv", "new\nline.csv", 'q"uote.csv', "a\\b.csv"):
        touch(text_root, rel)
    listed = names(text_root)
    assert "a\\b.csv" not in listed
    assert len(listed) == 4
    assert all(split_relative(name) for name in listed)


def test_a_file_that_vanishes_during_the_walk_is_skipped(
    text_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touch(text_root, "gone.csv")
    touch(text_root, "kept.csv")
    real = Path.lstat

    def lstat(self: Path) -> os.stat_result:
        if self.name == "gone.csv":
            raise FileNotFoundError(self.name)
        return real(self)

    monkeypatch.setattr(Path, "lstat", lstat)
    assert names(text_root) == ["kept.csv"]


def test_the_entries_carry_size_and_utc_modification_time(text_root: Path) -> None:
    path = touch(text_root, "a.csv", "hello")
    os.utime(path, (1_700_000_000, 1_700_000_123))
    (info,) = list_files(text_root)
    assert info == SourceFileInfo(
        name="a.csv", size=5, modified=datetime.fromtimestamp(1_700_000_123, tz=UTC)
    )
    assert info.modified.utcoffset() is not None
    assert info.modified.tzinfo is UTC


def test_the_sources_directory_may_be_a_symlink(text_root: Path, tmp_path: Path) -> None:
    touch(text_root, "a.csv")
    alias = tmp_path / "alias"
    alias.symlink_to(text_root)
    assert names(alias) == ["a.csv"]


def test_source_file_info_is_a_frozen_value() -> None:
    info = SourceFileInfo("a.csv", 1, datetime(2025, 1, 1, tzinfo=UTC))
    with pytest.raises(AttributeError):
        info.size = 2  # type: ignore[misc]
    assert info == SourceFileInfo("a.csv", 1, datetime(2025, 1, 1, tzinfo=UTC))
