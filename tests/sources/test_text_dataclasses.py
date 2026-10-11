"""The small value types of the text layer are frozen (or slotted) as designed."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sankey_studio.sources.files import SaveRequest, SourceFileInfo
from sankey_studio.sources.formats.csv_rows import Columns
from sankey_studio.sources.formats.lines import Line

FROZEN: list[Any] = [
    Line(1, "a\n", overlong=False),
    Columns(0, 1, 2, None),
    SourceFileInfo("a.csv", 1, datetime(2025, 1, 1, tzinfo=UTC)),
    SaveRequest(Path("sources"), "a.csv", 10),
]


@pytest.mark.parametrize("value", FROZEN, ids=[type(v).__name__ for v in FROZEN])
def test_value_types_are_frozen_and_slotted(value: Any) -> None:
    assert dataclasses.is_dataclass(value)
    first = dataclasses.fields(value)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, first, None)
    assert not hasattr(value, "__dict__")


def test_the_parse_job_is_slotted(source_ctx: Any) -> None:
    from sankey_studio.models import TextSource
    from sankey_studio.sources.base import CategoryCleaner, Diagnostics
    from sankey_studio.sources.formats.job import ParseJob

    diag = Diagnostics()
    job = ParseJob(TextSource(content="x"), source_ctx, diag, CategoryCleaner(diag), "t", "csv", "")
    assert not hasattr(job, "__dict__")
    with pytest.raises(AttributeError):
        job.unknown = 1  # type: ignore[attr-defined]
