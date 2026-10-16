# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Manual (web-editor) source: links already live inside the graph definition."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sankey_studio.models import ManualSource, RawLink
    from sankey_studio.sources.base import Diagnostics


class ManualDataSource:
    def __init__(self, spec: ManualSource) -> None:
        self._spec = spec

    # DataSource.iter_links is implemented structurally, so the signature is fixed.
    # noinspection PyUnusedParameter
    def iter_links(self, diag: Diagnostics) -> Iterator[RawLink]:  # noqa: ARG002 - matches DataSource.iter_links
        for link in self._spec.links:
            yield link.source, link.target, link.value, link.category or None
