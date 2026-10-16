# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``MongoDataSource``: truncation warning, the ``$limit`` rule and the row cap."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

import pytest

from sankey_studio.errors import GraphTooLargeError
from sankey_studio.graph.build import build_graph
from sankey_studio.models import TransformSpec
from sankey_studio.sources import open_source
from sankey_studio.sources.base import Diagnostics
from tests.sources.test_mongo_fakes import FakeMongo, fake_ctx

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sankey_studio.models import AppSettings, RawLink
    from sankey_studio.sources.base import SourceContext
    from tests.sources.conftest import FakeRunner, MongoResult, MongoRunner, SpecFactory

TRUNCATED = "Result truncated at limit 5"


def seed_many(seed: Callable[[list[dict[str, Any]]], None], count: int) -> None:
    seed([{"source": "a", "target": f"t{i}", "value": 1} for i in range(count)])


def build_docs(pattern: str, *, counting: bool) -> list[dict[str, Any]]:
    """One document per letter: ``g`` is usable, ``u`` has no target (so it is skipped).

    ``counting`` leaves out the value field, as an event log does (``value_field`` is null).
    """
    docs: list[dict[str, Any]] = []
    for index, kind in enumerate(pattern):
        doc: dict[str, Any] = {"source": "a"} if counting else {"source": "a", "value": 1}
        if kind == "g":
            doc["target"] = f"t{index}"
        docs.append(doc)
    return docs


class Boundary(NamedTuple):
    """What a collection laid out as ``pattern`` yields with ``limit`` 5."""

    pattern: str
    rows: int
    skipped: int
    warned: bool


BOUNDARIES = {
    "empty": Boundary("", 0, 0, warned=False),
    "limit - 1 documents": Boundary("gggg", 4, 0, warned=False),
    "exactly limit documents": Boundary("ggggg", 5, 0, warned=False),
    "limit + 1 documents": Boundary("gggggg", 5, 0, warned=True),
    "limit + 2 documents": Boundary("ggggggg", 5, 0, warned=True),
    "far past the limit": Boundary("g" * 50, 5, 0, warned=True),
    "unusable ones interleaved, limit - 1": Boundary("gugu", 2, 2, warned=False),
    "unusable ones interleaved, exactly limit": Boundary("ugugu", 2, 3, warned=False),
    "unusable ones interleaved, limit + 1": Boundary("uguggg", 3, 2, warned=True),
    "the extra document is unusable": Boundary("gugugu", 3, 2, warned=True),
    "only unusable ones, exactly limit": Boundary("uuuuu", 0, 5, warned=False),
    "only unusable ones, limit + 1": Boundary("uuuuuu", 0, 5, warned=True),
    "an unusable limit-th document, nothing after it": Boundary("ggggu", 4, 1, warned=False),
    "an unusable limit-th document, one after it": Boundary("ggggug", 4, 1, warned=True),
}

#: How the 5-document limit reaches the source: both modes, and the counting mode of each.
KINDS: dict[str, dict[str, Any]] = {
    "find": {},
    "aggregate": {"mode": "aggregate", "pipeline": [{"$match": {}}]},
    "find, counting": {"value_field": None},
    "aggregate, counting": {"mode": "aggregate", "pipeline": [{"$match": {}}], "value_field": None},
}


class BoundaryRunner(Protocol):
    def __call__(self, case: Boundary, kind: str) -> MongoResult: ...


@pytest.fixture
def boundary_run(
    mongo_run: MongoRunner,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[[list[dict[str, Any]]], None],
) -> BoundaryRunner:
    def run(case: Boundary, kind: str) -> MongoResult:
        options = KINDS[kind]
        mongo_seed(build_docs(case.pattern, counting="value_field" in options))
        return mongo_run(mongo_spec(limit=5, **options))

    return run


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", BOUNDARIES.values(), ids=BOUNDARIES)
def test_the_warning_needs_a_document_past_the_limit(
    case: Boundary, kind: str, boundary_run: BoundaryRunner
) -> None:
    """Documents count, not usable rows; the extra one proves the cut and is never read."""
    result = boundary_run(case, kind)
    assert len(result.rows) == case.rows
    assert result.diag.skipped == case.skipped
    truncations = [warning for warning in result.diag.warnings if "truncated" in warning]
    assert truncations == ([TRUNCATED] if case.warned else [])
    assert (result.diag.warnings[-1:] == [TRUNCATED]) is case.warned


@pytest.mark.parametrize("kind", ["find", "aggregate"])
def test_counting_mode_counts_each_document_once(kind: str, boundary_run: BoundaryRunner) -> None:
    result = boundary_run(BOUNDARIES["limit + 1 documents"], f"{kind}, counting")
    assert [row[2] for row in result.rows] == [1.0] * 5


class UserLimit(NamedTuple):
    user_limit: int
    documents: int
    rows: int
    warned: bool


#: The spec limit is 5. A last-stage ``$limit`` up to 6 (the number asked for) is the user's own.
USER_LIMITS = {
    "a smaller user limit": UserLimit(3, 10, 3, warned=False),
    "an equal user limit is the user's cut, not ours": UserLimit(5, 10, 5, warned=False),
    "one above ours reads the extra document": UserLimit(6, 10, 5, warned=True),
    "one above ours but only 5 documents": UserLimit(6, 5, 5, warned=False),
    "a larger user limit is cut to ours": UserLimit(8, 10, 5, warned=True),
    "a larger user limit but only 5 documents": UserLimit(8, 5, 5, warned=False),
}


@pytest.mark.parametrize("case", USER_LIMITS.values(), ids=USER_LIMITS)
def test_a_user_limit_at_the_end_of_the_pipeline(
    case: UserLimit,
    mongo_run: MongoRunner,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[[list[dict[str, Any]]], None],
) -> None:
    seed_many(mongo_seed, case.documents)
    pipeline = [{"$sort": {"target": 1}}, {"$limit": case.user_limit}]
    result = mongo_run(mongo_spec(mode="aggregate", pipeline=pipeline, limit=5))
    assert [row[1] for row in result.rows] == [f"t{i}" for i in range(case.rows)]
    assert result.diag.warnings == ([TRUNCATED] if case.warned else [])


@pytest.mark.parametrize("served", [5, 6, 50])
def test_reading_stops_at_the_document_past_the_limit(
    served: int, mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    """A server that ignores ``limit`` is still cut after the extra document, and the cursor
    is closed."""
    good = {"source": "a", "target": "b", "value": 1}
    fake = FakeMongo([good] * served)
    result = mongo_fake_run(fake, mongo_spec(limit=5))
    assert len(result.rows) == 5
    assert fake.cursors[0].served == min(served, 6)
    assert fake.cursors[0].closed is True
    assert result.diag.warnings == ([TRUNCATED] if served > 5 else [])


def test_the_truncation_warning_follows_the_skip_warnings(
    mongo_run: MongoRunner,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[[list[dict[str, Any]]], None],
) -> None:
    pair: list[dict[str, Any]] = [
        {"target": "b", "value": 1},
        {"source": "a", "target": "b", "value": "3"},
    ]
    mongo_seed([dict(entry) for entry in [*pair, *pair, pair[0]]])  # the 5th is the extra one
    result = mongo_run(mongo_spec(limit=4))
    assert result.diag.warnings == [
        "document 1: source field 'source' is missing",
        "document 3: source field 'source' is missing",
        "Read 2 text value(s) as numbers",
        "Result truncated at limit 4",
    ]


# --------------------------------------------------------------------------- max_links + 1


def read_rows(ctx: SourceContext, spec: Any) -> tuple[list[RawLink], Diagnostics]:
    diag = Diagnostics()
    return list(open_source(spec, ctx).iter_links(diag)), diag


class CapCase(NamedTuple):
    limit: int
    rows: int
    warning: str | None


CAPS = {
    "limit below the cap": CapCase(60, 60, "Result truncated at limit 60"),
    "limit exactly max_links": CapCase(100, 100, "Result truncated at limit 100"),
    "limit max_links + 1: the row cap stops reading before the extra document": CapCase(
        101, 101, None
    ),
    "limit max_links + 2 is read as max_links + 1": CapCase(102, 101, None),
    "limit far above the cap": CapCase(5_000, 101, None),
}


@pytest.mark.parametrize("case", CAPS.values(), ids=CAPS)
def test_never_more_than_max_links_plus_one_rows_are_yielded(
    case: CapCase,
    mongo_capped_ctx: SourceContext,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[[list[dict[str, Any]]], None],
) -> None:
    seed_many(mongo_seed, 400)
    rows, diag = read_rows(mongo_capped_ctx, mongo_spec(limit=case.limit))
    assert len(rows) == case.rows
    assert diag.warnings == ([case.warning] if case.warning else [])


def test_the_text_value_report_still_follows_the_stop_at_the_row_cap(
    mongo_capped_ctx: SourceContext,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[[list[dict[str, Any]]], None],
) -> None:
    mongo_seed([{"source": "a", "target": f"t{i}", "value": "2"} for i in range(400)])
    rows, diag = read_rows(mongo_capped_ctx, mongo_spec(limit=5_000))
    assert len(rows) == 101
    assert diag.warnings == ["Read 101 text value(s) as numbers"]


# --------------------------------------------------------------------------- skipped documents


def dirty_docs(count: int, bad_every: int) -> list[dict[str, Any]]:
    """``count`` documents; the first and then every ``bad_every``-th has a value of zero."""
    return [
        {"source": "a", "target": f"t{i}", "value": 0 if i % bad_every == 0 else 1}
        for i in range(count)
    ]


def test_skipped_documents_do_not_eat_the_cap_so_a_too_large_result_is_refused(
    mongo_capped_ctx: SourceContext,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[[list[dict[str, Any]]], None],
) -> None:
    """400 documents, every 10th unusable, max_links 100: 389 usable rows are too many. The
    document limit used to be max_links + 1, so 101 documents (90 rows) were silently kept."""
    mongo_seed(dirty_docs(400, 10))
    spec = mongo_spec(limit=5_000)
    rows, diag = read_rows(mongo_capped_ctx, spec)
    assert len(rows) == 101
    assert [row[1] for row in rows[:3]] + [rows[-1][1]] == ["t1", "t2", "t3", "t112"]
    assert diag.skipped == 12  # documents 0, 10, ..., 110 precede the 101st usable row
    build_diag = Diagnostics()
    stream = open_source(spec, mongo_capped_ctx).iter_links(build_diag)
    with pytest.raises(GraphTooLargeError, match="more than 100 links"):
        build_graph(stream, TransformSpec(), max_raw_links=100, diag=build_diag)


class RowCapCase(NamedTuple):
    usable: int
    rows: int
    served: int


#: One unusable document (no source) precedes every usable one: ``served`` is twice the rows read.
ROW_CAPS = {
    "one below max_links": RowCapCase(99, 99, 198),
    "exactly max_links": RowCapCase(100, 100, 200),
    "max_links + 1 is the last row read": RowCapCase(101, 101, 202),
    "max_links + 2 is never read": RowCapCase(102, 101, 202),
    "far above": RowCapCase(150, 101, 202),
}


@pytest.mark.parametrize("case", ROW_CAPS.values(), ids=ROW_CAPS)
def test_reading_stops_at_the_row_past_max_links_not_at_a_document_count(
    case: RowCapCase, mongo_capped_settings: AppSettings, mongo_spec: SpecFactory, tmp_path: Path
) -> None:
    docs: list[dict[str, Any]] = []
    for i in range(case.usable):
        docs += [{"target": "b", "value": 1}, {"source": "a", "target": f"t{i}", "value": 1}]
    fake = FakeMongo(docs)
    ctx = fake_ctx(fake, mongo_capped_settings, tmp_path)
    rows, diag = read_rows(ctx, mongo_spec(limit=5_000))
    assert len(rows) == case.rows
    assert fake.cursors[0].served == case.served
    assert fake.cursors[0].closed is True
    assert diag.skipped == case.served // 2


def test_the_truncation_warning_still_follows_skipped_documents_below_the_cap(
    mongo_capped_ctx: SourceContext,
    mongo_spec: SpecFactory,
    mongo_seed: Callable[[list[dict[str, Any]]], None],
) -> None:
    """The document limit is reached before the row cap: half of the 60 documents are unusable."""
    mongo_seed(dirty_docs(400, 2))
    rows, diag = read_rows(mongo_capped_ctx, mongo_spec(limit=60))
    assert len(rows) == 30
    assert diag.skipped == 30
    assert diag.warnings[-1] == "Result truncated at limit 60"
