"""``scripts/profile_memory.py``: the synthetic data, the pipeline and the two report modes."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

from scripts import profile_memory

from sankey_studio.models import MAX_CATEGORIES

if TYPE_CHECKING:
    import pytest


def test_synthetic_links_are_deterministic_and_layered() -> None:
    first = profile_memory.synthetic_links(500)
    assert first == profile_memory.synthetic_links(500)
    assert first != profile_memory.synthetic_links(500, seed=8)
    assert len(first) == 500
    assert all(source.split("-")[0] < target.split("-")[0] for source, target, _v, _c in first)
    assert all(1 <= value <= 1000 for _s, _t, value, _c in first)
    assert {category for *_rest, category in first} <= set(profile_memory.CATEGORIES)
    assert len(profile_memory.CATEGORIES) <= MAX_CATEGORIES


def test_the_pipeline_summary_counts_graph_and_figures() -> None:
    summary = profile_memory.run_pipeline(profile_memory.synthetic_links(5000))
    assert summary.raw_links == 5000
    assert summary.categories == 12
    assert 0 < summary.nodes <= profile_memory.LAYERS * profile_memory.WIDTH
    assert summary.full_figure_links == summary.links
    assert summary.drawn_figure_links == min(summary.links, profile_memory.DRAWN)
    assert summary.donut_slices == 8  # six kept, Uncategorized and Other


def test_under_memray_is_detected_from_the_imported_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "memray", raising=False)
    assert not profile_memory.under_memray()
    monkeypatch.setitem(sys.modules, "memray", types.ModuleType("memray"))
    assert profile_memory.under_memray()


def test_peak_rss_is_a_positive_number_of_mib() -> None:
    assert 10 < profile_memory.peak_mib() < 100_000


def test_main_prints_the_peak_when_run_plainly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(profile_memory, "LINKS", 3000)
    monkeypatch.delitem(sys.modules, "memray", raising=False)
    profile_memory.main()
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("3000 raw links -> ")
    assert out[1].startswith("peak RSS: ")
    assert out[1].endswith(" MiB")
    assert len(out) == 2


def test_main_only_hints_at_memray_stats_under_memray(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(profile_memory, "LINKS", 3000)
    monkeypatch.setitem(sys.modules, "memray", types.ModuleType("memray"))
    profile_memory.main()
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "running under memray: read the numbers with `memray stats .memray/bench.bin`"
    assert "peak RSS" not in "".join(out)
    assert len(out) == 2
