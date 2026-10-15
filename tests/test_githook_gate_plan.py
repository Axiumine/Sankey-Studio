"""The pure planner of the git-hook gate (scripts/githook_plan.py): checks, tiers, ref -> checks."""

from __future__ import annotations

from datetime import date

import pytest
from scripts import githook_plan as plan

from tests.githook_support import ZERO, Case, case_id

SHA_A = "a" * 40
SHA_B = "b" * 40
PUSH_TIER = ("fast", "cov", "memray", "e2e")
MAIN_TIER = (*PUSH_TIER, "security")
RELEASE_TIER = (*MAIN_TIER, "e2e-mongo", "qodana", "mutation")


# --------------------------------------------------------------------------- the check table


def test_the_eight_checks_run_in_this_order() -> None:
    assert plan.CHECK_ORDER == (
        "fast",
        "cov",
        "memray",
        "e2e",
        "security",
        "e2e-mongo",
        "qodana",
        "mutation",
    )
    assert tuple(plan.CHECKS) == plan.CHECK_ORDER
    assert all(check.name == name for name, check in plan.CHECKS.items())


def targets(*names: str) -> list[tuple[str, ...]]:
    return [("make", name) for name in names]


EXACT_STEPS = [
    Case("fast", targets("lint", "typecheck", "caps")),
    Case("cov", targets("cov")),
    Case("memray", targets("memray")),
    Case("e2e", targets("e2e")),
    Case("security", targets("semgrep-test", "semgrep", "trivy")),
    Case("e2e-mongo", targets("e2e-mongo")),
    Case("qodana", targets("cov", "qodana")),
    Case("mutation", targets("mutate", "mutate-gate")),
]


@pytest.mark.parametrize("case", EXACT_STEPS, ids=case_id)
def test_every_check_runs_exactly_these_make_targets_in_order(
    case: Case[str, list[tuple[str, ...]]],
) -> None:
    check = plan.CHECKS[case.given]
    assert [step.argv for step in check.steps] == case.expected


JUNIT_STEPS = [
    Case("fast", [False, False, False]),
    Case("cov", [True]),
    Case("memray", [True]),
    Case("e2e", [True]),
    Case("security", [False, False, False]),
    Case("e2e-mongo", [True]),
    Case("qodana", [True, False]),
    Case("mutation", [False, False]),
]


@pytest.mark.parametrize("case", JUNIT_STEPS, ids=case_id)
def test_pytest_steps_are_verified_through_junit_and_the_others_are_not(
    case: Case[str, list[bool]],
) -> None:
    check = plan.CHECKS[case.given]
    assert [step.junit for step in check.steps] == case.expected


def test_only_the_mongo_unit_tests_may_skip_and_only_inside_cov() -> None:
    allowed = {
        (check.name, index): step.allow_skips
        for check in plan.CHECKS.values()
        for index, step in enumerate(check.steps)
        if step.allow_skips
    }
    assert allowed == {
        ("cov", 0): (plan.MONGO_ENV,),
        ("qodana", 0): (plan.MONGO_ENV,),
    }
    assert plan.MONGO_ENV == "SANKEY_TEST_MONGO_URI"


def test_caps_is_the_only_step_without_a_locked_uv() -> None:
    unlocked = [
        (check.name, step.argv)
        for check in plan.CHECKS.values()
        for step in check.steps
        if not step.uv_locked
    ]
    assert unlocked == [("fast", ("make", "caps"))]


def test_check_flags_are_set_only_where_they_belong() -> None:
    flags = {
        name: (check.dated, check.mongo, check.offline_guard) for name, check in plan.CHECKS.items()
    }
    assert {n: f for n, f in flags.items() if any(f)} == {
        "security": (True, False, True),
        "e2e-mongo": (False, True, False),
    }


def test_the_project_mongo_is_the_compose_one_on_port_27117() -> None:
    assert plan.MONGO_URI == "mongodb://127.0.0.1:27117"
    assert (plan.MAIN_REF, plan.TAG_PREFIX) == ("refs/heads/main", "refs/tags/")


def test_make_builds_a_step_with_defaults() -> None:
    step = plan.make("lint")
    assert step == plan.Step(("make", "lint"))
    assert (step.junit, step.allow_skips, step.uv_locked) == (False, (), True)
    custom = plan.make("cov", junit=True, allow_skips=("x",))
    assert (custom.junit, custom.allow_skips) == (True, ("x",))


# --------------------------------------------------------------------------- tiers


TIERS = [
    Case(plan.Tier.COMMIT, ("fast",)),
    Case(plan.Tier.PUSH, PUSH_TIER),
    Case(plan.Tier.MAIN, MAIN_TIER),
    Case(plan.Tier.RELEASE, RELEASE_TIER),
]


@pytest.mark.parametrize("case", TIERS, ids=case_id)
def test_tiers_are_cumulative_groups_of_checks(case: Case[plan.Tier, tuple[str, ...]]) -> None:
    assert plan.TIER_CHECKS[case.given] == case.expected


def test_every_tier_is_listed_and_release_is_everything() -> None:
    assert set(plan.TIER_CHECKS) == set(plan.Tier)
    assert plan.TIER_CHECKS[plan.Tier.RELEASE] == plan.CHECK_ORDER
    assert [t.value for t in plan.Tier] == ["commit", "push", "main", "release"]


# --------------------------------------------------------------------------- resolve_names


RESOLVE = [
    Case((), ()),
    Case(("fast",), ("fast",)),
    Case(("commit",), ("fast",)),
    Case(("push",), PUSH_TIER),
    Case(("main",), MAIN_TIER),
    Case(("release",), RELEASE_TIER),
    Case(("e2e", "fast"), ("fast", "e2e")),
    Case(("mutation", "qodana"), ("qodana", "mutation")),
    Case(("push", "cov", "cov"), PUSH_TIER),
    Case(("security", "push"), (*PUSH_TIER, "security")),
    Case(("e2e-mongo", "commit"), ("fast", "e2e-mongo")),
]


@pytest.mark.parametrize("case", RESOLVE, ids=case_id)
def test_resolve_names_gives_unique_checks_in_run_order(
    case: Case[tuple[str, ...], tuple[str, ...]],
) -> None:
    assert plan.resolve_names(case.given) == case.expected


def test_resolve_names_accepts_any_iterable() -> None:
    assert plan.resolve_names(iter(["cov", "fast"])) == ("fast", "cov")


@pytest.mark.parametrize("name", ["nope", "", "Fast", "e2e_mongo", "pre-push"])
def test_resolve_names_rejects_an_unknown_name_and_lists_the_valid_ones(name: str) -> None:
    with pytest.raises(plan.UnknownNameError) as caught:
        plan.resolve_names(["fast", name])
    assert str(caught.value) == (
        f"unknown check or tier {name!r}; use one of: fast, cov, memray, e2e, security, "
        "e2e-mongo, qodana, mutation, commit, push, main, release"
    )
    assert isinstance(caught.value, ValueError)


# --------------------------------------------------------------------------- stamp keys


TREE = "0123456789abcdef0123456789abcdef01234567"
KEYS = [
    Case(("fast", date(2026, 10, 15)), TREE),
    Case(("cov", date(2026, 10, 15)), TREE),
    Case(("e2e-mongo", date(2026, 1, 2)), TREE),
    Case(("mutation", date(2026, 12, 31)), TREE),
    Case(("security", date(2026, 10, 15)), f"{TREE}.20261015"),
    Case(("security", date(2026, 1, 2)), f"{TREE}.20260102"),
    Case(("security", date(2027, 1, 1)), f"{TREE}.20270101"),
]


@pytest.mark.parametrize("case", KEYS, ids=case_id)
def test_stamp_key_is_the_tree_and_for_a_dated_check_also_the_utc_day(
    case: Case[tuple[str, date], str],
) -> None:
    name, day = case.given
    assert plan.stamp_key(plan.CHECKS[name], TREE, day) == case.expected


# --------------------------------------------------------------------------- shas and lines


ZERO_SHAS = [
    Case("", False),
    Case("0", True),
    Case(ZERO, True),
    Case("0" * 64, True),
    Case("0" * 39 + "1", False),
    Case("1" + "0" * 39, False),
    Case(SHA_A, False),
    Case(" ", False),
]


@pytest.mark.parametrize("case", ZERO_SHAS, ids=case_id)
def test_is_zero_sha_needs_a_non_empty_string_of_zeros(case: Case[str, bool]) -> None:
    assert plan.is_zero_sha(case.given) is case.expected


def test_a_pushed_ref_is_a_delete_when_the_local_sha_is_zero() -> None:
    assert plan.PushedRef("(delete)", ZERO, "refs/heads/x", SHA_A).is_delete
    assert not plan.PushedRef("refs/heads/x", SHA_A, "refs/heads/x", ZERO).is_delete


def line(local: str = "refs/heads/f", sha: str = SHA_A, remote: str = "refs/heads/f") -> str:
    return f"{local} {sha} {remote} {ZERO}"


def test_parse_push_lines_reads_four_fields_per_line() -> None:
    refs = plan.parse_push_lines(f"{line()}\nrefs/tags/v1 {SHA_B} refs/tags/v1 {SHA_A}\n")
    assert refs == [
        plan.PushedRef("refs/heads/f", SHA_A, "refs/heads/f", ZERO),
        plan.PushedRef("refs/tags/v1", SHA_B, "refs/tags/v1", SHA_A),
    ]


@pytest.mark.parametrize("text", ["", "\n", "\n\n", "   \n\t\n", "  "])
def test_parse_push_lines_skips_blank_lines(text: str) -> None:
    assert plan.parse_push_lines(text) == []


def test_parse_push_lines_skips_blank_lines_between_refs() -> None:
    assert len(plan.parse_push_lines(f"\n{line()}\n\n{line()}\n   \n")) == 2


@pytest.mark.parametrize(
    "bad",
    [
        "refs/heads/f " + SHA_A,
        f"refs/heads/f {SHA_A} refs/heads/f",
        f"refs/heads/f {SHA_A} refs/heads/f {ZERO} extra",
        f"refs/heads/f  {SHA_A} refs/heads/f {ZERO}",
        f"{line()} ",
        "just words",
    ],
    ids=["two", "three", "five", "double-space", "trailing-space", "words"],
)
def test_parse_push_lines_refuses_a_line_that_is_not_four_fields(bad: str) -> None:
    with pytest.raises(ValueError, match="malformed pre-push line: ") as caught:
        plan.parse_push_lines(f"{line()}\n{bad}\n")
    assert repr(bad) in str(caught.value)


# --------------------------------------------------------------------------- ref -> tier


REMOTE_REFS = [
    Case("refs/heads/main", plan.Tier.RELEASE),
    Case("refs/heads/feature", plan.Tier.PUSH),
    Case("refs/heads/main2", plan.Tier.PUSH),
    Case("refs/heads/mainline", plan.Tier.PUSH),
    Case("refs/heads/release/main", plan.Tier.PUSH),
    Case("refs/heads/Main", plan.Tier.PUSH),
    Case("refs/tags/v1.0.0", plan.Tier.RELEASE),
    Case("refs/tags/anything/nested", plan.Tier.RELEASE),
    Case("refs/tags/", plan.Tier.RELEASE),
    Case("refs/tag/v1", plan.Tier.PUSH),
    Case("refs/remotes/origin/main", plan.Tier.PUSH),
    Case("refs/notes/commits", plan.Tier.PUSH),
    Case("main", plan.Tier.PUSH),
]


@pytest.mark.parametrize("case", REMOTE_REFS, ids=case_id)
def test_only_main_and_tags_on_the_remote_side_need_the_release_tier(
    case: Case[str, plan.Tier],
) -> None:
    assert plan.tier_for_remote_ref(case.given) is case.expected


# --------------------------------------------------------------------------- plan_push


def refs_of(*lines: str) -> list[plan.PushedRef]:
    return plan.parse_push_lines("\n".join(lines))


def release(ref: str) -> tuple[str, plan.Tier, tuple[str, ...]]:
    return ref, plan.Tier.RELEASE, RELEASE_TIER


def pushed(ref: str) -> tuple[str, plan.Tier, tuple[str, ...]]:
    return ref, plan.Tier.PUSH, PUSH_TIER


type Expected = list[tuple[str, plan.Tier, tuple[str, ...]]]

PUSH_PLANS: list[Case[list[str], Expected]] = [
    Case(
        [line("refs/heads/feature", SHA_A, "refs/heads/feature")],
        [pushed("refs/heads/feature")],
        "branch",
    ),
    Case([line("refs/heads/main", SHA_A, "refs/heads/main")], [release("refs/heads/main")], "main"),
    Case(
        [line("refs/heads/feature", SHA_A, "refs/heads/main")],
        [release("refs/heads/main")],
        "feature:main",
    ),
    Case(
        [line("refs/heads/main", SHA_A, "refs/heads/feature")],
        [pushed("refs/heads/feature")],
        "main:feature",
    ),
    Case([line("refs/tags/v1", SHA_A, "refs/tags/v1")], [release("refs/tags/v1")], "tag"),
    Case([f"(delete) {ZERO} refs/heads/old {SHA_B}"], [], "delete"),
    Case([], [], "empty"),
]


@pytest.mark.parametrize("case", PUSH_PLANS, ids=case_id)
def test_plan_push_maps_each_remote_ref_to_its_tier_and_drops_deletes(
    case: Case[list[str], Expected],
) -> None:
    plans = plan.plan_push(refs_of(*case.given))
    assert [(p.ref.remote_ref, p.tier, p.checks) for p in plans] == case.expected


def test_plan_push_handles_a_mixed_push_in_order() -> None:
    refs = refs_of(
        line("refs/heads/a", SHA_A, "refs/heads/a"),
        f"(delete) {ZERO} refs/heads/gone {SHA_B}",
        line("refs/heads/a", SHA_A, "refs/heads/main"),
        line("refs/tags/v2", SHA_B, "refs/tags/v2"),
    )
    plans = plan.plan_push(refs)
    assert [(p.ref.remote_ref, p.tier.value) for p in plans] == [
        ("refs/heads/a", "push"),
        ("refs/heads/main", "release"),
        ("refs/tags/v2", "release"),
    ]


def test_plan_push_keeps_the_pushed_ref_object_and_accepts_any_iterable() -> None:
    ref = plan.PushedRef("refs/heads/a", SHA_A, "refs/heads/a", ZERO)
    (only,) = plan.plan_push(iter([ref]))
    assert only.ref is ref
    assert only == plan.RefPlan(ref, plan.Tier.PUSH, PUSH_TIER)


def test_a_ref_deleted_remotely_is_judged_by_the_local_sha_not_the_ref_name() -> None:
    deleting_main = plan.PushedRef("(delete)", ZERO, "refs/heads/main", SHA_A)
    assert plan.plan_push([deleting_main]) == []
