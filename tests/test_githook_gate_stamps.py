"""Stamps (proof that a check passed on a tree) and the gate lock (scripts/githook_stamps.py)."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

import pytest
from scripts import githook_stamps as stamps

from tests.githook_support import Case, case_id

TREE = "0123456789abcdef0123456789abcdef01234567"


def sample(check: str = "cov", key: str = TREE) -> stamps.Stamp:
    steps = (
        stamps.StepTiming(("make", "cov"), 0, 12.3456),
        stamps.StepTiming(("make", "qodana"), 0, 0.0004),
    )
    return stamps.Stamp(check, key, TREE, "2026-10-15T12:00:00Z", 12.3463, steps)


# --------------------------------------------------------------------------- the JSON form


def test_a_stamp_is_pretty_json_with_a_trailing_newline_and_rounded_durations() -> None:
    text = sample().to_json()
    assert text.endswith("}\n")
    assert text.startswith('{\n  "version": 1,\n  "check": "cov",\n')
    assert json.loads(text) == {
        "version": 1,
        "check": "cov",
        "key": TREE,
        "tree": TREE,
        "finished_utc": "2026-10-15T12:00:00Z",
        "duration_s": 12.346,
        "steps": [
            {"argv": ["make", "cov"], "exit": 0, "duration_s": 12.346},
            {"argv": ["make", "qodana"], "exit": 0, "duration_s": 0.0},
        ],
    }


def test_a_stamp_survives_a_round_trip_through_json() -> None:
    original = stamps.Stamp("fast", TREE, TREE, "2026-10-15T12:00:00Z", 1.5, ())
    assert stamps.Stamp.from_json(original.to_json()) == original
    full = sample()
    again = stamps.Stamp.from_json(full.to_json())
    assert again.steps == (
        stamps.StepTiming(("make", "cov"), 0, 12.346),
        stamps.StepTiming(("make", "qodana"), 0, 0.0),
    )
    assert (again.check, again.key, again.tree) == ("cov", TREE, TREE)


GOOD = json.loads(sample().to_json())


def mutated(**changes: object) -> str:
    return json.dumps({**GOOD, **changes})


def without(key: str) -> str:
    return json.dumps({k: v for k, v in GOOD.items() if k != key})


JUNK: list[Case[str, None]] = [
    Case("", None, "empty"),
    Case("{", None, "truncated"),
    Case("[]", None, "list"),
    Case("null", None, "null"),
    Case('"text"', None, "string"),
    Case(mutated(version=2), None, "version-2"),
    Case(mutated(version="1"), None, "version-str"),
    Case(without("version"), None, "no-version"),
    Case(without("check"), None, "no-check"),
    Case(without("key"), None, "no-key"),
    Case(without("tree"), None, "no-tree"),
    Case(without("finished_utc"), None, "no-finish"),
    Case(without("duration_s"), None, "no-duration"),
    Case(without("steps"), None, "no-steps"),
    Case(mutated(steps=[{"argv": ["make"], "exit": 0}]), None, "step-no-dur"),
    Case(mutated(steps=["x"]), None, "step-str"),
    Case(mutated(steps=[{"argv": 5, "exit": 0, "duration_s": 1}]), None, "argv-int"),
    Case(mutated(duration_s="fast"), None, "duration-str"),
    Case(mutated(steps=None), None, "steps-null"),
]


@pytest.mark.parametrize("text", ["[]", "null", mutated(version=2), without("version")])
def test_a_foreign_document_says_it_is_not_a_version_1_stamp(text: str) -> None:
    with pytest.raises(ValueError, match=r"^not a version 1 stamp$"):
        stamps.Stamp.from_json(text)


@pytest.mark.parametrize("case", JUNK, ids=case_id)
def test_from_json_refuses_anything_that_is_not_a_version_1_stamp(case: Case[str, None]) -> None:
    with pytest.raises((ValueError, KeyError, TypeError)):
        stamps.Stamp.from_json(case.given)


# --------------------------------------------------------------------------- the store


def test_the_store_lays_stamps_out_as_base_check_key(tmp_path: Path) -> None:
    store = stamps.StampStore(tmp_path / "hook-stamps")
    assert store.path("cov", TREE) == tmp_path / "hook-stamps" / "cov" / TREE


def test_a_stamp_is_written_and_read_back(tmp_path: Path) -> None:
    store = stamps.StampStore(tmp_path / "hook-stamps")
    assert store.read("cov", TREE) is None
    written = store.write(sample())
    assert written == store.path("cov", TREE)
    assert written.read_text(encoding="utf-8") == sample().to_json()
    assert store.read("cov", TREE) == stamps.Stamp.from_json(sample().to_json())


def test_writing_again_replaces_the_stamp_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    store = stamps.StampStore(tmp_path)
    store.write(sample())
    newer = stamps.Stamp("cov", TREE, TREE, "2026-10-16T08:00:00Z", 2.0, ())
    store.write(newer)
    assert store.read("cov", TREE) == newer
    assert sorted(p.name for p in (tmp_path / "cov").iterdir()) == [TREE]


def test_a_stamp_file_is_private_to_the_owner(tmp_path: Path) -> None:
    path = stamps.StampStore(tmp_path).write(sample())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_prepare_creates_the_check_directory_and_leaves_nothing_in_it(tmp_path: Path) -> None:
    store = stamps.StampStore(tmp_path / "hook-stamps")
    store.prepare("cov")
    assert (tmp_path / "hook-stamps" / "cov").is_dir()
    assert list((tmp_path / "hook-stamps" / "cov").iterdir()) == []


def test_prepare_keeps_the_stamps_that_are_already_there(tmp_path: Path) -> None:
    store = stamps.StampStore(tmp_path)
    store.write(sample())
    store.prepare("cov")
    assert store.read("cov", TREE) == stamps.Stamp.from_json(sample().to_json())
    assert sorted(p.name for p in (tmp_path / "cov").iterdir()) == [TREE]


def test_prepare_fails_with_an_os_error_when_the_directory_is_a_file(tmp_path: Path) -> None:
    (tmp_path / "cov").write_text("in the way\n", encoding="utf-8")
    with pytest.raises(OSError, match="cov"):
        stamps.StampStore(tmp_path).prepare("cov")


def test_prepare_fails_when_no_file_can_be_created_in_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(**_: object) -> tuple[int, str]:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tempfile, "mkstemp", denied)
    with pytest.raises(PermissionError):
        stamps.StampStore(tmp_path).prepare("cov")


def test_stamps_of_different_checks_and_keys_do_not_collide(tmp_path: Path) -> None:
    store = stamps.StampStore(tmp_path)
    store.write(sample("cov"))
    store.write(sample("memray"))
    store.write(sample("security", f"{TREE}.20261015"))
    assert store.read("cov", TREE) is not None
    assert store.read("memray", TREE) is not None
    assert store.read("e2e", TREE) is None
    assert store.read("security", TREE) is None
    assert store.read("security", f"{TREE}.20261015") is not None
    assert store.read("security", f"{TREE}.20261016") is None


def put(store: stamps.StampStore, check: str, key: str, text: str | bytes) -> None:
    path = store.path(check, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


UNUSABLE: list[Case[str | bytes, None]] = [
    Case("", None, "empty"),
    Case("not json", None, "junk"),
    Case(b"\xff\xfe\x00bad", None, "not utf-8"),
    Case(sample().to_json().replace('"version": 1', '"version": 9'), None, "other version"),
    Case(sample("memray").to_json(), None, "belongs to another check"),
    Case(sample("cov", "f" * 40).to_json(), None, "belongs to another key"),
]


@pytest.mark.parametrize("case", UNUSABLE, ids=case_id)
def test_a_damaged_or_foreign_stamp_counts_as_missing(
    tmp_path: Path, case: Case[str | bytes, None]
) -> None:
    store = stamps.StampStore(tmp_path)
    put(store, "cov", TREE, case.given)
    assert store.read("cov", TREE) is None


def test_a_directory_in_place_of_a_stamp_counts_as_missing(tmp_path: Path) -> None:
    store = stamps.StampStore(tmp_path)
    store.path("cov", TREE).mkdir(parents=True)
    assert store.read("cov", TREE) is None


def leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_a_failed_write_keeps_the_old_stamp_and_removes_its_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stamps.StampStore(tmp_path)
    store.write(sample())
    before = store.path("cov", TREE).read_text(encoding="utf-8")

    def refuse(_fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", refuse)
    replacement = stamps.Stamp("cov", TREE, TREE, "2030-01-01T00:00:00Z", 9.0, ())
    with pytest.raises(OSError, match="disk full"):
        store.write(replacement)
    assert store.path("cov", TREE).read_text(encoding="utf-8") == before
    assert leftovers(tmp_path / "cov") == [TREE]


def test_a_failed_first_write_leaves_no_stamp_and_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stamps.StampStore(tmp_path)

    def refuse(_self: Path, _target: object) -> Path:
        raise OSError("rename refused")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError, match="rename refused"):
        store.write(sample())
    assert store.read("cov", TREE) is None
    assert leftovers(tmp_path / "cov") == []


def test_the_stamp_is_flushed_before_the_sync_and_appears_only_at_the_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        seen["size"] = os.fstat(fd).st_size
        seen["names"] = leftovers(tmp_path / "cov")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    stamps.StampStore(tmp_path).write(sample())
    assert seen["size"] == len(sample().to_json().encode())
    (name,) = seen["names"]
    assert name.startswith(".tmp-")
    assert leftovers(tmp_path / "cov") == [TREE]


def test_a_failure_after_the_rename_reports_the_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = Path.replace

    def replace_then_fail(self: Path, target: Path) -> Path:
        real_replace(self, target)
        raise OSError("late failure")

    monkeypatch.setattr(Path, "replace", replace_then_fail)
    with pytest.raises(OSError, match="late failure"):
        stamps.StampStore(tmp_path).write(sample())


def test_an_interrupt_during_the_write_also_removes_the_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(_fd: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "fsync", interrupt)
    with pytest.raises(KeyboardInterrupt):
        stamps.StampStore(tmp_path).write(sample())
    assert leftovers(tmp_path / "cov") == []


# --------------------------------------------------------------------------- the lock


def test_the_lock_writes_its_holder_and_clears_it_on_exit(tmp_path: Path) -> None:
    path = tmp_path / "git" / "deeper" / "hook-gate.lock"
    lock = stamps.GateLock(path, "pid 7, pre-push, started 2026-10-15T12:00:00Z")
    with lock:
        assert path.read_text(encoding="utf-8") == "pid 7, pre-push, started 2026-10-15T12:00:00Z\n"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == ""


def test_entering_the_lock_gives_the_lock_itself(tmp_path: Path) -> None:
    lock = stamps.GateLock(tmp_path / "hook-gate.lock", "me")
    with lock as held:
        assert held is lock
        assert (held.path, held.holder) == (tmp_path / "hook-gate.lock", "me")


def test_a_second_run_is_refused_and_told_who_holds_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "hook-gate.lock"
    with stamps.GateLock(path, "pid 7, run, started now"):
        with pytest.raises(stamps.GateBusyError) as caught, stamps.GateLock(path, "pid 8, x"):
            pytest.fail("the second lock must not be granted")
        assert str(caught.value) == "pid 7, run, started now"
        assert path.read_text(encoding="utf-8") == "pid 7, run, started now\n"


def test_the_holder_text_survives_a_refused_attempt(tmp_path: Path) -> None:
    path = tmp_path / "hook-gate.lock"
    with stamps.GateLock(path, "first"):
        for _ in range(2):
            with pytest.raises(stamps.GateBusyError, match="first"), stamps.GateLock(path, "x"):
                pytest.fail("not granted")
    with stamps.GateLock(path, "third"):
        assert path.read_text(encoding="utf-8") == "third\n"


def test_a_lock_held_by_something_else_reports_an_unknown_holder(tmp_path: Path) -> None:
    path = tmp_path / "hook-gate.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with pytest.raises(stamps.GateBusyError) as caught, stamps.GateLock(path, "me"):
            pytest.fail("not granted")
        assert str(caught.value) == "unknown holder"
    finally:
        os.close(fd)


def open_fds() -> int:
    return len(list(Path("/dev/fd").iterdir()))


def test_a_refused_attempt_does_not_leak_a_file_descriptor(tmp_path: Path) -> None:
    path = tmp_path / "hook-gate.lock"
    with stamps.GateLock(path, "holder"):
        before = open_fds()
        for _ in range(5):
            with pytest.raises(stamps.GateBusyError), stamps.GateLock(path, "x"):
                pytest.fail("not granted")
        assert open_fds() == before


def test_a_shorter_holder_text_replaces_a_longer_old_one_completely(tmp_path: Path) -> None:
    path = tmp_path / "hook-gate.lock"
    path.write_text("x" * 200, encoding="utf-8")
    with stamps.GateLock(path, "short"):
        assert path.read_text(encoding="utf-8") == "short\n"


def test_leaving_a_lock_twice_is_harmless(tmp_path: Path) -> None:
    lock = stamps.GateLock(tmp_path / "hook-gate.lock", "twice")
    lock.__enter__()
    lock.__exit__(None, None, None)
    lock.__exit__(None, None, None)


def test_the_lock_is_free_again_after_an_error_inside_it(tmp_path: Path) -> None:
    path = tmp_path / "hook-gate.lock"
    with pytest.raises(RuntimeError, match="boom"), stamps.GateLock(path, "one"):
        raise RuntimeError("boom")
    with stamps.GateLock(path, "two"):
        assert path.read_text(encoding="utf-8") == "two\n"


def test_leaving_a_lock_that_was_never_taken_is_harmless(tmp_path: Path) -> None:
    lock = stamps.GateLock(tmp_path / "hook-gate.lock", "never")
    lock.__exit__(None, None, None)
    assert not (tmp_path / "hook-gate.lock").exists()


def test_a_lock_can_be_taken_again_after_it_was_released(tmp_path: Path) -> None:
    lock = stamps.GateLock(tmp_path / "hook-gate.lock", "again")
    for _ in range(2):
        with lock:
            assert (tmp_path / "hook-gate.lock").read_text(encoding="utf-8") == "again\n"


def test_the_busy_error_is_a_runtime_error_that_carries_the_holder() -> None:
    error = stamps.GateBusyError("pid 1, run")
    assert isinstance(error, RuntimeError)
    assert str(error) == "pid 1, run"
    assert stamps.STAMP_VERSION == 1
