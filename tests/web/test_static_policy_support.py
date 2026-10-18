# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers of ``test_static_policy.py``: the base test ids and the file scanners.

No tests here. ``API_TESTIDS`` is the base list of ``data-testid`` names (documented in
docs/ui/testids.md; the contract of wave 3 and of the e2e wave); ``testids-extra.txt`` in
``static/`` lists the names the shared code adds beyond it. ``used_testids`` finds the literal
names a template or script uses.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from sankey_studio.web.app import STATIC_DIR
from sankey_studio.web.routers.pages import TEMPLATES_DIR

if TYPE_CHECKING:
    from pathlib import Path

_API_NAMES: Final = """
    app-root categorise-all-matching category-cell category-clear category-datalist
    category-error category-row category-table chart-tab-donut chart-tab-sankey compare-card
    compare-card-toggle compare-grid compare-limit-message compare-missing compare-open
    compare-select conflict-banner conflict-reload conflict-save-copy connection-add
    connection-default-db connection-delete connection-latency connection-name connection-test
    connection-uri delete-confirm donut-chart donut-hint editor-description editor-name
    editor-tags entries-pager-next entries-pager-prev entries-row entries-search entries-sort
    entries-table entries-total entries-uncategorized-only export-csv export-donut-png
    export-donut-svg export-fallback-note export-height export-html export-json
    export-sankey-png export-sankey-svg export-scale export-transparent export-width graph-card
    graph-delete graph-duplicate graph-edit graph-open legend legend-item library-empty
    library-export library-import library-pager-next library-pager-prev library-search
    library-sort library-tag-filter loading manual-add-row manual-row manual-table
    mongo-collection mongo-connection mongo-database mongo-filter mongo-pipeline mongo-sample
    mongo-suggest nav-library nav-new nav-settings read-only-banner remote-banner sankey-chart
    save-as-copy save-button settings-connection settings-error settings-max-drawn-links
    settings-max-links settings-max-upload-mb settings-migrate settings-mongo-timeout
    settings-save settings-sources-dir settings-storage-backend settings-storage-connection
    settings-test-storage source-column-category source-column-source source-column-target
    source-column-value source-content source-file-select source-format
    source-no-category-switch source-tab-manual source-tab-mongo source-tab-paste
    source-tab-text source-tab-upload source-upload-input stats style-color-mode style-height
    style-orientation style-title theme-switch toast transform-hide-nodes transform-merge-nodes
    transform-min-value transform-on-cycle transform-top-links warning-item warnings
"""
API_TESTIDS: Final = frozenset(_API_NAMES.split())
EXTRA_FILE: Final = STATIC_DIR / "testids-extra.txt"
TESTID_NAME: Final = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
TEXT_SUFFIXES: Final = frozenset({".html", ".js", ".css", ".svg", ".txt"})

_LITERAL: Final = r"""["']([a-z][a-z0-9-]*)["']"""
_PATTERNS: Final = (
    re.compile(r'data-testid="([^"{}]+)"'),
    re.compile(rf"""["']data-testid["']\s*:\s*{_LITERAL}"""),
    re.compile(rf"""\b\w*[tT]estid\s*:\s*{_LITERAL}"""),
    re.compile(rf"""\bdataset\.testid\s*=\s*{_LITERAL}"""),
    re.compile(rf"""setAttribute\(\s*["']data-testid["']\s*,\s*{_LITERAL}"""),
)
_BLOCK: Final = re.compile(r"\btestids\s*:\s*\{([^}]*)\}")
_VALUE: Final = re.compile(r"""\w+\s*:\s*["']([a-z][a-z0-9-]*)["']""")


def extra_testids() -> set[str]:
    """The names in ``static/testids-extra.txt`` (comments and blank lines skipped)."""
    lines = (line.strip() for line in EXTRA_FILE.read_text(encoding="utf-8").splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def used_testids(text: str) -> set[str]:
    """Every literal ``data-testid`` name in ``text`` (HTML attribute or script option)."""
    found: set[str] = set()
    for pattern in _PATTERNS:
        found.update(pattern.findall(text))
    for block in _BLOCK.findall(text):
        found.update(_VALUE.findall(block))
    return found


def own_files(root: Path, *suffixes: str) -> list[Path]:
    """The files below ``root`` with one of ``suffixes`` (all text suffixes if none), no vendor."""
    wanted = frozenset(suffixes) or TEXT_SUFFIXES
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in wanted
        and "vendor" not in path.relative_to(root).parts[:-1]
    )


def rel(path: Path) -> str:
    """``path`` relative to its root (templates or static) as a POSIX string."""
    root = TEMPLATES_DIR if TEMPLATES_DIR in path.parents else STATIC_DIR
    return path.relative_to(root).as_posix()
