"""Git access of the gate (scripts/githook_git.py), against real throw-away repositories."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from scripts import githook_git as gitmod
from scripts.githook_git import GitError, Repo

from tests.githook_support import (
    REPO_ROOT,
    ZERO,
    Case,
    case_id,
    commit_file,
    git,
    git_env,
    init_repo,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = init_repo(tmp_path / "work")
    commit_file(made.root, "a.txt", "one\n", "chore: first")
    return made


# --------------------------------------------------------------------------- run_git, discover


def test_run_git_never_raises_on_a_failing_command(tmp_path: Path) -> None:
    done = gitmod.run_git(["rev-parse", "--verify", "nope"], tmp_path, git_env())
    assert done.returncode != 0
    assert done.stdout == ""


def test_run_git_passes_no_optional_locks_first(repo: Repo) -> None:
    done = gitmod.run_git(["status", "--short"], repo.root, git_env())
    assert done.args[1:3] == ["--no-optional-locks", "status"]


def test_run_git_uses_the_environment_it_is_given(repo: Repo) -> None:
    env = {**git_env(), "GIT_AUTHOR_NAME": "Somebody Else"}
    done = gitmod.run_git(["var", "GIT_AUTHOR_IDENT"], repo.root, env)
    assert done.stdout.startswith("Somebody Else <test@example.com>")


def test_git_binary_is_the_one_on_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    assert gitmod.git_binary() == shutil.which("git")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(GitError, match=r"^git is not on PATH$"):
        gitmod.git_binary()


def test_discover_finds_the_root_and_the_git_dir(repo: Repo) -> None:
    sub = repo.root / "sub"
    sub.mkdir()
    found = Repo.discover(sub, git_env())
    assert found.root == repo.root
    assert found.common_dir == repo.root / ".git"
    assert found.env == git_env()


def test_discover_in_a_linked_worktree_points_to_the_shared_git_dir(
    repo: Repo, tmp_path: Path
) -> None:
    other = tmp_path / "linked"
    git(repo.root, "worktree", "add", "-q", "-b", "side", str(other))
    found = Repo.discover(other, git_env())
    assert found.root == other
    assert found.common_dir == repo.root / ".git"


def test_discover_outside_a_repository_raises(tmp_path: Path) -> None:
    env = {**git_env(), "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)}
    folder = tmp_path / "plain"
    folder.mkdir()
    with pytest.raises(
        GitError, match=r"rev-parse --show-toplevel failed: fatal: not a git repository"
    ):
        Repo.discover(folder, env)


def test_git_strips_the_trailing_newline_and_raises_with_stderr(repo: Repo) -> None:
    assert repo.git("rev-parse", "--abbrev-ref", "HEAD") == "main"
    with pytest.raises(GitError) as caught:
        repo.git("rev-parse", "--verify", "no-such-rev")
    assert str(caught.value).startswith("git ")
    assert "rev-parse --verify no-such-rev failed: " in str(caught.value)


def test_out_reports_a_command_that_is_not_a_list() -> None:
    done = subprocess.CompletedProcess("odd", 3, "", " boom \n")
    with pytest.raises(GitError) as caught:
        gitmod._out(done)
    assert str(caught.value) == "git  failed: boom"


def test_out_keeps_leading_whitespace_of_the_output() -> None:
    done = subprocess.CompletedProcess(["git", "x"], 0, "  a\n\n", "")
    assert gitmod._out(done) == "  a"


# --------------------------------------------------------------------------- trees


def test_the_index_tree_is_the_head_tree_when_nothing_is_staged(repo: Repo) -> None:
    assert repo.index_tree() == repo.head_tree()
    assert len(repo.head_tree()) == 40


def test_staging_a_change_moves_the_index_tree_but_not_the_head_tree(repo: Repo) -> None:
    head = repo.head_tree()
    (repo.root / "b.txt").write_text("two\n", encoding="utf-8")
    git(repo.root, "add", "b.txt")
    assert repo.head_tree() == head
    assert repo.index_tree() != head


def test_the_index_tree_follows_the_index_file_of_the_hook(repo: Repo, tmp_path: Path) -> None:
    alternate = tmp_path / "alternate-index"
    shutil.copy(repo.root / ".git" / "index", alternate)
    env = {**git_env(), "GIT_INDEX_FILE": str(alternate)}
    (repo.root / "c.txt").write_text("three\n", encoding="utf-8")
    git_in_alternate = Repo(repo.root, repo.common_dir, env)
    assert git_in_alternate.run("add", "c.txt").returncode == 0
    assert git_in_alternate.index_tree() != repo.index_tree()
    assert repo.index_tree() == repo.head_tree()


def test_commit_tree_peels_commits_branches_and_tags(repo: Repo) -> None:
    tree = repo.head_tree()
    sha = repo.git("rev-parse", "HEAD")
    git(repo.root, "tag", "-a", "v1", "-m", "release")
    git(repo.root, "tag", "light")
    tag_object = repo.git("rev-parse", "refs/tags/v1")
    assert tag_object != sha
    for rev in (sha, "main", "HEAD", "light", "v1", tag_object):
        assert repo.commit_tree(rev) == tree


def test_commit_tree_follows_the_commit_it_is_asked_about(repo: Repo) -> None:
    first = repo.git("rev-parse", "HEAD")
    commit_file(repo.root, "b.txt", "two\n", "feat: second")
    assert repo.commit_tree(first) != repo.head_tree()
    with pytest.raises(GitError, match="failed"):
        repo.commit_tree("1" * 40)
    with pytest.raises(GitError, match="failed"):
        repo.commit_tree("no-such-branch")


# --------------------------------------------------------------------------- status


def test_a_clean_repository_has_an_empty_status(repo: Repo) -> None:
    assert repo.status() == ()


def test_status_lists_staged_unstaged_and_every_untracked_file(repo: Repo) -> None:
    (repo.root / "a.txt").write_text("changed\n", encoding="utf-8")
    (repo.root / "staged.txt").write_text("s\n", encoding="utf-8")
    git(repo.root, "add", "staged.txt")
    (repo.root / "dir").mkdir()
    (repo.root / "dir" / "one.txt").write_text("1\n", encoding="utf-8")
    (repo.root / "dir" / "two.txt").write_text("2\n", encoding="utf-8")
    assert repo.status() == (
        " M a.txt",
        "A  staged.txt",
        "?? dir/one.txt",
        "?? dir/two.txt",
    )


def test_status_leaves_ignored_files_out(repo: Repo) -> None:
    commit_file(repo.root, ".gitignore", "*.log\nbuild/\n", "chore: ignore")
    (repo.root / "x.log").write_text("noise\n", encoding="utf-8")
    (repo.root / "build").mkdir()
    (repo.root / "build" / "out.bin").write_text("o\n", encoding="utf-8")
    assert repo.status() == ()


def test_status_does_not_take_the_index_lock(repo: Repo) -> None:
    (repo.root / "a.txt").write_text("changed\n", encoding="utf-8")
    assert repo.status() == (" M a.txt",)
    assert not (repo.root / ".git" / "index.lock").exists()


STATUS_LINES = [
    Case([], True, "nothing"),
    Case(["M  a"], True, "staged change"),
    Case(["A  a"], True, "staged add"),
    Case(["D  a"], True, "staged delete"),
    Case(["R  a -> b"], True, "staged rename"),
    Case(["M  a", "A  b"], True, "several staged"),
    Case([" M a"], False, "unstaged change"),
    Case(["MM a"], False, "staged and changed again"),
    Case([" D a"], False, "unstaged delete"),
    Case(["AM a"], False, "added then changed"),
    Case(["?? a"], False, "untracked"),
    Case(["M  a", "?? b"], False, "staged plus untracked"),
    Case(["M "], True, "a bare status code"),
    Case(["x"], False, "too short"),
    Case([""], False, "empty line"),
]


@pytest.mark.parametrize("case", STATUS_LINES, ids=case_id)
def test_the_worktree_matches_the_index_only_without_unstaged_or_untracked_lines(
    case: Case[list[str], bool],
) -> None:
    assert gitmod.worktree_matches_index(case.given) is case.expected


def test_the_worktree_check_accepts_a_tuple(repo: Repo) -> None:
    assert gitmod.worktree_matches_index(repo.status())
    (repo.root / "n.txt").write_text("n\n", encoding="utf-8")
    assert not gitmod.worktree_matches_index(repo.status())


def test_the_snapshot_compares_tree_and_status() -> None:
    one = gitmod.Snapshot("t", ("?? a",))
    assert one == gitmod.Snapshot("t", ("?? a",))
    assert one != gitmod.Snapshot("t", ())
    assert one != gitmod.Snapshot("u", ("?? a",))


# --------------------------------------------------------------------------- config, env vars


def test_config_returns_the_value_or_none(repo: Repo) -> None:
    git(repo.root, "config", "demo.key", "value ")
    assert repo.config("demo.key") == "value"
    assert repo.config("demo.missing") is None


def test_local_env_vars_come_from_git_itself(repo: Repo) -> None:
    names = repo.local_env_vars()
    assert {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX"} <= set(names)
    assert all(name.startswith("GIT_") for name in names)


def test_local_env_vars_are_the_names_git_prints(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, ...]] = []

    def fake_run(_self: Repo, *args: str) -> subprocess.CompletedProcess[str]:
        asked.append(args)
        return subprocess.CompletedProcess(["git"], 0, "GIT_ONE GIT_TWO\nGIT_THREE\n", "")

    monkeypatch.setattr(Repo, "run", fake_run)
    assert repo.local_env_vars() == ("GIT_ONE", "GIT_TWO", "GIT_THREE")
    assert asked == [("rev-parse", "--local-env-vars")]


def test_the_names_of_a_failed_git_call_are_not_trusted(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = subprocess.CompletedProcess(["git"], 129, "GIT_ONE\n", "usage")
    monkeypatch.setattr(Repo, "run", lambda _self, *_args: broken)
    assert repo.local_env_vars() == gitmod.FALLBACK_LOCAL_ENV


def test_local_env_vars_fall_back_to_the_known_list_when_git_cannot_say(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = subprocess.CompletedProcess(["git"], 129, "", "usage")
    monkeypatch.setattr(Repo, "run", lambda _self, *_args: broken)
    assert repo.local_env_vars() == gitmod.FALLBACK_LOCAL_ENV


def test_local_env_vars_fall_back_when_git_prints_nothing(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = subprocess.CompletedProcess(["git"], 0, "\n", "")
    monkeypatch.setattr(Repo, "run", lambda _self, *_args: empty)
    assert repo.local_env_vars() == gitmod.FALLBACK_LOCAL_ENV


def test_the_fallback_list_covers_what_git_reports_today(repo: Repo) -> None:
    assert set(repo.local_env_vars()) <= set(gitmod.FALLBACK_LOCAL_ENV)


# --------------------------------------------------------------------------- files and commits


def test_tracked_mode_tells_executable_normal_and_untracked_files_apart(repo: Repo) -> None:
    script = repo.root / "run.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    git(repo.root, "add", "run.sh")
    (repo.root / "loose.txt").write_text("l\n", encoding="utf-8")
    assert repo.tracked_mode("run.sh") == "100755"
    assert repo.tracked_mode("a.txt") == "100644"
    assert repo.tracked_mode("loose.txt") is None
    assert repo.tracked_mode("missing/file") is None


def test_has_commit_is_true_only_for_commits_that_exist_here(repo: Repo) -> None:
    assert repo.has_commit(repo.git("rev-parse", "HEAD"))
    assert not repo.has_commit("1" * 40)
    assert not repo.has_commit(ZERO)
    assert not repo.has_commit(repo.head_tree())


def test_message_returns_the_full_commit_message(repo: Repo) -> None:
    sha = commit_file(repo.root, "b.txt", "two\n", "feat: second\n\nbody line")
    assert repo.message(sha).rstrip("\n") == "feat: second\n\nbody line"


# --------------------------------------------------------------------------- new_commits


def three_commits(repo: Repo) -> tuple[str, str, str]:
    first = repo.git("rev-parse", "HEAD")
    second = commit_file(repo.root, "b.txt", "2\n", "feat: second")
    third = commit_file(repo.root, "c.txt", "3\n", "feat: third")
    return first, second, third


def track(repo: Repo, remote: str, branch: str, sha: str) -> None:
    git(repo.root, "update-ref", f"refs/remotes/{remote}/{branch}", sha)


def test_new_commits_are_those_no_remote_tracking_ref_has(repo: Repo) -> None:
    first, second, third = three_commits(repo)
    git(repo.root, "config", "remote.origin.url", "https://example.invalid/r.git")
    track(repo, "origin", "main", first)
    assert repo.new_commits(third, "origin", ZERO) == [third, second]


def test_a_known_remote_sha_is_excluded_too(repo: Repo) -> None:
    first, second, third = three_commits(repo)
    git(repo.root, "config", "remote.origin.url", "https://example.invalid/r.git")
    assert repo.new_commits(third, "origin", second) == [third]
    assert repo.new_commits(third, "origin", first) == [third, second]


def test_a_remote_sha_we_do_not_have_is_ignored(repo: Repo) -> None:
    first, second, third = three_commits(repo)
    git(repo.root, "config", "remote.origin.url", "https://example.invalid/r.git")
    track(repo, "origin", "main", first)
    assert repo.new_commits(third, "origin", "9" * 40) == [third, second]


def test_everything_is_new_when_the_remote_has_nothing(repo: Repo) -> None:
    first, second, third = three_commits(repo)
    git(repo.root, "config", "remote.origin.url", "https://example.invalid/r.git")
    assert repo.new_commits(third, "origin", ZERO) == [third, second, first]


def test_nothing_is_new_when_the_remote_already_has_the_tip(repo: Repo) -> None:
    _, _, third = three_commits(repo)
    git(repo.root, "config", "remote.origin.url", "https://example.invalid/r.git")
    track(repo, "origin", "main", third)
    assert repo.new_commits(third, "origin", third) == []


def test_only_the_named_remote_counts_for_a_configured_remote(repo: Repo) -> None:
    _, second, third = three_commits(repo)
    git(repo.root, "config", "remote.origin.url", "https://example.invalid/r.git")
    track(repo, "mirror", "main", third)
    assert repo.new_commits(third, "origin", ZERO)[:2] == [third, second]


def test_a_push_by_url_counts_every_remote_tracking_ref(repo: Repo) -> None:
    _, _, third = three_commits(repo)
    track(repo, "mirror", "main", third)
    url = "https://example.invalid/other.git"
    assert repo.config(f"remote.{url}.url") is None
    assert repo.new_commits(third, url, ZERO) == []


def test_new_commits_of_a_tag_object_are_the_commits_behind_it(repo: Repo) -> None:
    first, second, third = three_commits(repo)
    git(repo.root, "config", "remote.origin.url", "https://example.invalid/r.git")
    track(repo, "origin", "main", first)
    git(repo.root, "tag", "-a", "v1", "-m", "release")
    tag_object = repo.git("rev-parse", "refs/tags/v1")
    assert repo.new_commits(tag_object, "origin", ZERO) == [third, second]


# --------------------------------------------------------------------------- commit-msg hook


@pytest.fixture
def with_hook(repo: Repo) -> Repo:
    hooks = repo.root / ".githooks"
    hooks.mkdir()
    shutil.copy(REPO_ROOT / ".githooks" / "commit-msg", hooks / "commit-msg")
    return repo


MESSAGES = [
    Case("feat(web): add a page\n", 0, "valid"),
    Case("🤖 fix(sources): reject path traversal\n", 0, "valid with the robot"),
    Case("Merge branch 'x' into main\n", 0, "merge"),
    Case("just some words\n", 1, "no type"),
    Case("feat(nope): unknown scope\n", 1, "bad scope"),
    Case("feat: x\n\nCo-Authored-By: someone <a@b.c>\n", 1, "banned trailer"),
]


@pytest.mark.parametrize("case", MESSAGES, ids=case_id)
def test_the_real_commit_msg_hook_judges_a_message(with_hook: Repo, case: Case[str, int]) -> None:
    code, output = gitmod.run_commit_msg_hook(with_hook, case.given)
    assert code == case.expected
    assert (output == "") is (case.expected == 0)


def test_the_refusal_text_is_the_output_of_the_hook(with_hook: Repo) -> None:
    code, output = gitmod.run_commit_msg_hook(with_hook, "just some words\n")
    assert code == 1
    assert "just some words" in output
    assert output == output.strip()


def test_a_missing_hook_refuses_with_a_reason(repo: Repo) -> None:
    code, output = gitmod.run_commit_msg_hook(repo, "feat: x\n")
    assert code == 1
    assert (
        output
        == f"{repo.root / '.githooks' / 'commit-msg'} cannot be run (bash or the hook is missing)"
    )


def test_a_missing_bash_refuses_with_a_reason(
    with_hook: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    code, output = gitmod.run_commit_msg_hook(with_hook, "feat: x\n")
    assert code == 1
    assert "cannot be run" in output


def test_the_hook_counts_characters_not_bytes(with_hook: Repo) -> None:
    accepted = "feat: " + "\u00e9" * 144 + "\n"
    refused = "feat: " + "\u00e9" * 145 + "\n"
    assert gitmod.run_commit_msg_hook(with_hook, accepted)[0] == 0
    assert gitmod.run_commit_msg_hook(with_hook, refused)[0] == 1


def test_the_hook_applies_its_own_length_limit(with_hook: Repo) -> None:
    assert gitmod.run_commit_msg_hook(with_hook, "feat: " + "a" * 144 + "\n")[0] == 0
    assert gitmod.run_commit_msg_hook(with_hook, "feat: " + "a" * 145 + "\n")[0] == 1
