"""Data sources: text files (csv/tsv/sankeymatic/json), MongoDB, and manual entries.

Owned by the architect. The concrete sources are imported inside the branches on purpose: a
half-written ``text.py`` or ``mongo_source.py`` must not break ``import sankey_studio.sources``
(and with it ``sources.files``) for the other agents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.models import ManualSource, TextSource
from sankey_studio.sources.manual import ManualDataSource

if TYPE_CHECKING:
    from sankey_studio.models import SourceSpec
    from sankey_studio.sources.base import DataSource, SourceContext

__all__ = ["open_source"]


def open_source(spec: SourceSpec, ctx: SourceContext) -> DataSource:
    """Return the ``DataSource`` for ``spec``."""
    if isinstance(spec, ManualSource):
        return ManualDataSource(spec)
    if isinstance(spec, TextSource):
        from sankey_studio.sources.text import TextDataSource  # noqa: PLC0415 - see module doc

        return TextDataSource(spec, ctx)
    from sankey_studio.sources.mongo_source import MongoDataSource  # noqa: PLC0415 - lazy, see module doc

    return MongoDataSource(spec, ctx)
