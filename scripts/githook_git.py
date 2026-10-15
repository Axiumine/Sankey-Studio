"""Git access of the hook gate: the repository, trees, porcelain status, new commits."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Self

from scripts import githook_messages as msg
from scripts.githook_plan import is_zero_sha

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: ``git rev-parse --local-env-vars`` as of git 2.47, used when that command fails.
FALLBACK_LOCAL_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)


class GitError(RuntimeError):
    """A git command failed (the message carries the command and its stderr)."""


def git_binary() -> str:
    found = shutil.which("git")
    if found is None:
        raise GitError("git is not on PATH")
    return found


def run_git(
    args: Sequence[str], cwd: Path, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    """One git call, no shell, never raising on a non-zero exit."""
    return subprocess.run(  # noqa: S603 - fixed git binary, argv list, no shell
        [git_binary(), "--no-optional-locks", *args],
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )


class Snapshot(NamedTuple):
    """What a run must not change: the tree it tested and the porcelain status."""

    tree: str
    status: tuple[str, ...]


def worktree_matches_index(status: Sequence[str]) -> bool:
    """True when no line shows an unstaged change or an untracked file."""
    return all(len(line) >= 2 and line[1] == " " and line[0] != "?" for line in status)


@dataclass(frozen=True, slots=True)
class Repo:
    """A repository seen from a hook: ``env`` is the hook's own environment (GIT_INDEX_FILE...)."""

    root: Path
    common_dir: Path
    env: Mapping[str, str]

    @classmethod
    def discover(cls, cwd: Path, env: Mapping[str, str]) -> Self:
        top = _out(run_git(["rev-parse", "--show-toplevel"], cwd, env))
        common = _out(
            run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd, env)
        )
        return cls(Path(top), Path(common), env)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run_git(args, self.root, self.env)

    def git(self, *args: str) -> str:
        """Stdout of a git call without the trailing newline; a failure raises ``GitError``."""
        return _out(self.run(*args))

    def index_tree(self) -> str:
        """Tree of the index the hook sees (``git write-tree`` honours GIT_INDEX_FILE)."""
        return self.git("write-tree")

    def commit_tree(self, rev: str) -> str:
        """Tree of a commit, also from a tag object (``rev^{tree}`` peels)."""
        return self.git("rev-parse", "--verify", f"{rev}^{{tree}}")

    def head_tree(self) -> str:
        return self.commit_tree("HEAD")

    def status(self) -> tuple[str, ...]:
        lines = self.git("status", "--porcelain", "--untracked-files=all").splitlines()
        return tuple(lines)

    def config(self, key: str) -> str | None:
        done = self.run("config", "--get", key)
        return done.stdout.strip() if done.returncode == 0 else None

    def local_env_vars(self) -> tuple[str, ...]:
        done = self.run("rev-parse", "--local-env-vars")
        names = done.stdout.split()
        return tuple(names) if done.returncode == 0 and names else FALLBACK_LOCAL_ENV

    def tracked_mode(self, path: str) -> str | None:
        """Index mode of a tracked path (``100755``), or None when it is not tracked."""
        listing = self.git("ls-files", "-s", "--", path)
        return listing.split()[0] if listing else None

    def has_commit(self, sha: str) -> bool:
        return self.run("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0

    def new_commits(self, local_sha: str, remote: str, remote_sha: str) -> list[str]:
        """Commits reachable from ``local_sha`` that no remote-tracking ref of ``remote`` has.

        When ``remote`` is not a configured remote name (a push by URL), every remote-tracking
        ref counts, so the whole history is not mistaken for new commits.
        """
        known = self.config(f"remote.{remote}.url") is not None
        args = ["rev-list", local_sha, "--not", f"--remotes={remote}" if known else "--remotes"]
        if not is_zero_sha(remote_sha) and self.has_commit(remote_sha):
            args.append(remote_sha)
        return self.git(*args).split()

    def message(self, sha: str) -> str:
        return self.run("show", "-s", "--format=%B", sha).stdout


def _out(done: subprocess.CompletedProcess[str]) -> str:
    if done.returncode != 0:
        command = " ".join(str(a) for a in done.args[1:]) if isinstance(done.args, list) else ""
        raise GitError(f"git {command} failed: {done.stderr.strip()}")
    return done.stdout.rstrip("\n")


def run_commit_msg_hook(repo: Repo, message: str) -> tuple[int, str]:
    """Apply ``.githooks/commit-msg`` to a message; returns its exit code and its output."""
    hook = repo.root / ".githooks" / "commit-msg"
    bash = shutil.which("bash")
    if bash is None or not hook.is_file():
        return 1, msg.MESSAGE_HOOK_UNUSABLE.format(hook=hook)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "COMMIT_EDITMSG"
        path.write_text(message, encoding="utf-8")
        done = subprocess.run(  # noqa: S603 - fixed argv, the message travels in a file
            [bash, str(hook), str(path)],
            cwd=repo.root,
            env={**repo.env, "LC_ALL": "C.UTF-8"},
            capture_output=True,
            text=True,
            check=False,
        )
    return done.returncode, (done.stdout + done.stderr).strip()
