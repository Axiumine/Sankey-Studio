"""Tests for the pre-commit code-caps check (scripts/check_code_caps.py)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from scripts import check_code_caps as caps
from scripts import githook_plan

REPO_ROOT = Path(__file__).resolve().parent.parent


def func(name: str, body_lines: int, params: str = "") -> str:
    """A function whose total length is ``body_lines + 1`` lines."""
    body = "\n".join("    x = 1" for _ in range(body_lines))
    return f"def {name}({params}):\n{body}\n"


def kinds(source: str) -> dict[str, int]:
    """``{"kind:name": value}`` of the violations found in ``source``."""
    return {f"{m.kind}:{m.name}": m.value for m in caps.measure_source(source, "m.py")}


# --------------------------------------------------------------------------- function length


def test_function_at_cap_is_fine_and_one_over_violates() -> None:
    assert kinds(func("f", 49)) == {}
    assert kinds(func("f", 50)) == {"function:f": 51}


def test_decorators_count_towards_function_length() -> None:
    source = "@deco\n" + func("f", 49)
    assert kinds(source) == {"function:f": 51}


def test_methods_are_qualified_and_async_defs_are_measured() -> None:
    method = func("m", 50).replace("\n", "\n    ").replace("def m", "    def m", 1)
    source = "class C:\n" + method
    assert "function:C.m" in kinds(source)
    assert kinds("async " + func("g", 50)) == {"function:g": 51}


# --------------------------------------------------------------------------- class and file length


def test_class_length_cap() -> None:
    body = "\n".join("    a = 1" for _ in range(299))
    assert kinds(f"class C:\n{body}\n") == {}
    assert kinds(f"class C:\n{body}\n    b = 2\n") == {"class:C": 301}


def test_file_length_cap() -> None:
    assert kinds("x = 1\n" * 500) == {}
    assert kinds("x = 1\n" * 501) == {"file:-": 501}


# --------------------------------------------------------------------------- parameters


@pytest.mark.parametrize(
    ("signature", "violates"),
    [
        ("a, b, c, d", False),
        ("a, b, c, d, e", True),
        ("a, b, *, c, d", False),
        ("a, b, c, d, /", False),
        ("a, b, c, *args", False),
        ("a, b, c, *args, **kw", True),
    ],
)
def test_function_parameter_cap(signature: str, *, violates: bool) -> None:
    assert ("params:f" in kinds(func("f", 1, signature))) is violates


def test_self_and_cls_of_methods_are_free() -> None:
    cls_src = "class C:\n    def m(self, a, b, c, d):\n        pass\n"
    cm_src = "class C:\n    @classmethod\n    def m(cls, a, b, c, d):\n        pass\n"
    static_src = "class C:\n    @staticmethod\n    def m(a, b, c, d, e):\n        pass\n"
    assert kinds(cls_src) == {}
    assert kinds(cm_src) == {}
    assert kinds(static_src) == {"params:C.m": 5}


def test_nested_function_in_method_does_not_get_free_self() -> None:
    source = "class C:\n    def m(self):\n        def inner(self, a, b, c, d):\n            pass\n"
    assert kinds(source) == {"params:C.m.inner": 5}


# --------------------------------------------------------------------------- nesting


def nested_ifs(depth: int) -> str:
    lines = ["def f(x):", *("    " * (level + 1) + "if x:" for level in range(depth))]
    lines.append("    " * (depth + 1) + "pass")
    return "\n".join(lines) + "\n"


def test_nesting_cap_counts_block_levels() -> None:
    assert kinds(nested_ifs(4)) == {}
    assert kinds(nested_ifs(5)) == {"nesting:f": 5}


def test_elif_chain_does_not_deepen_nesting() -> None:
    elifs = "".join(f"    elif x == {i}:\n        pass\n" for i in range(10))
    assert kinds("def f(x):\n    if x == -1:\n        pass\n" + elifs) == {}


def test_else_if_is_real_nesting() -> None:
    source = (
        "def f(x):\n    if x:\n        pass\n    else:\n        if x:\n            for _ in x:\n"
        "                while x:\n                    with x:\n                        pass\n"
    )
    assert kinds(source) == {"nesting:f": 5}


def test_try_with_match_and_loops_count() -> None:
    source = (
        "def f(x):\n    try:\n        for a in x:\n            with a:\n"
        "                match a:\n                    case 1:\n                        if a:\n"
        "                            pass\n"
        "    except OSError:\n        pass\n"
    )
    assert kinds(source) == {"nesting:f": 5}


def test_nested_defs_are_measured_separately() -> None:
    source = (
        "def outer(x):\n    if x:\n        def inner(y):\n            if y:\n                pass\n"
    )
    assert kinds(source) == {}


def test_duplicate_qualnames_get_a_suffix() -> None:
    source = func("f", 50) + func("f", 50)
    assert sorted(kinds(source)) == ["function:f", "function:f#2"]


# --------------------------------------------------------------------------- baseline ratchet


def measure(kind: str, name: str, value: int) -> caps.Measure:
    return caps.Measure("a.py", 1, kind, name, value)


def test_compare_classifies_new_grown_improved_fixed() -> None:
    current = [measure("function", "new", 60), measure("function", "grew", 70)]
    current += [measure("function", "better", 55)]
    baseline = {
        "a.py::function::grew": 60,
        "a.py::function::better": 80,
        "a.py::function::gone": 90,
    }
    verdict = caps.compare(current, baseline)
    assert [m.name for m in verdict.new] == ["new"]
    assert [(m.name, old) for m, old in verdict.grown] == [("grew", 60)]
    assert verdict.improved == (("a.py::function::better", 80, 55),)
    assert verdict.fixed == ("a.py::function::gone",)
    assert verdict.failed


def test_equal_or_smaller_violation_passes() -> None:
    verdict = caps.compare([measure("function", "f", 60)], {"a.py::function::f": 60})
    assert not verdict.failed


def test_ratchet_only_lowers_and_never_adds() -> None:
    current = [measure("function", "f", 55), measure("function", "added", 99)]
    baseline = {"a.py::function::f": 70, "a.py::function::fixed": 80}
    assert caps.ratcheted(current, baseline) == {"a.py::function::f": 55}


def test_baseline_round_trip_and_validation(tmp_path: Path) -> None:
    path = tmp_path / caps.BASELINE_NAME
    assert caps.load_baseline(path) == {}
    caps.write_baseline(path, {"b": 2, "a": 1})
    assert caps.load_baseline(path) == {"a": 1, "b": 2}
    assert json.loads(path.read_text(encoding="utf-8"))["caps"] == caps.CAPS
    path.write_text('{"violations": {"a": "x"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid"):
        caps.load_baseline(path)


# --------------------------------------------------------------------------- CLI end to end


def make_repo(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def run(root: Path, *args: str) -> int:
    return caps.main(["--root", str(root), *args])


def test_cli_passes_on_clean_repo_and_fails_on_new_violation(tmp_path: Path) -> None:
    make_repo(tmp_path, {"ok.py": func("small", 3)})
    assert run(tmp_path) == 0
    make_repo(tmp_path, {"big.py": func("huge", 60)})
    assert run(tmp_path) == 1


def test_cli_init_then_tolerates_but_blocks_growth(tmp_path: Path) -> None:
    make_repo(tmp_path, {"big.py": func("huge", 60)})
    assert run(tmp_path, "--init") == 0
    assert run(tmp_path) == 0
    assert run(tmp_path, "--init") == 2
    assert run(tmp_path, "--init", "--force") == 0
    make_repo(tmp_path, {"big.py": func("huge", 65)})
    assert run(tmp_path) == 1


def test_cli_update_baseline_ratchets_down_and_refuses_new(tmp_path: Path) -> None:
    make_repo(tmp_path, {"big.py": func("huge", 60)})
    run(tmp_path, "--init")
    make_repo(tmp_path, {"big.py": func("huge", 55)})
    assert run(tmp_path, "--update-baseline") == 0
    baseline = caps.load_baseline(tmp_path / caps.BASELINE_NAME)
    assert baseline == {"big.py::function::huge": 56}
    make_repo(tmp_path, {"other.py": func("worse", 70)})
    assert run(tmp_path, "--update-baseline") == 1


def test_cli_reports_syntax_errors_and_corrupt_baseline(tmp_path: Path) -> None:
    make_repo(tmp_path, {"bad.py": "def (:\n"})
    assert run(tmp_path) == 2
    make_repo(tmp_path, {"bad.py": "x = 1\n", caps.BASELINE_NAME: "[]"})
    assert run(tmp_path) == 2


def test_excluded_directories_are_skipped(tmp_path: Path) -> None:
    make_repo(tmp_path, {".venv/lib/x.py": func("huge", 80), "mutants/y.py": func("huge", 80)})
    make_repo(tmp_path, {"ok.py": "x = 1\n"})
    assert run(tmp_path) == 0


def test_git_listing_honours_gitignore_and_includes_untracked(tmp_path: Path) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)  # noqa: S607 - git from PATH, fixed argv
    make_repo(tmp_path, {".gitignore": "ignored.py\n", "ignored.py": func("huge", 80)})
    make_repo(tmp_path, {"untracked.py": func("huge", 80)})
    names = [p.name for p in caps.python_files(tmp_path)]
    assert names == ["untracked.py"]
    assert run(tmp_path) == 1


# --------------------------------------------------------------------------- repo wiring


def test_pre_commit_hook_runs_the_check_through_the_gate() -> None:
    """The hook is a shim for the gate, whose ``fast`` check runs ``make caps`` (this script)."""
    hook = REPO_ROOT / ".githooks" / "pre-commit"
    assert hook.is_file()
    assert os.access(hook, os.X_OK)
    assert "-m scripts.githook_gate pre-commit" in hook.read_text(encoding="utf-8")
    assert ("make", "caps") in [step.argv for step in githook_plan.CHECKS["fast"].steps]


def test_caps_are_the_documented_ones() -> None:
    assert caps.CAPS == {"file": 500, "function": 50, "class": 300, "params": 4, "nesting": 4}
