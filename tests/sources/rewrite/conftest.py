"""The ``rewrite`` fixture: run ``rewrite_text`` on a text with spec fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import pytest

from sankey_studio.models import TextSource
from sankey_studio.sources.rewrite import RewriteJob, rewrite_text

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext
    from sankey_studio.sources.rewrite import Rewritten


class Rewriter(Protocol):
    def __call__(
        self, text: str, edit: Any, *, alias: dict[str, str] | None = None, **fields: Any
    ) -> Rewritten: ...


@pytest.fixture
def rewrite(source_ctx: SourceContext) -> Rewriter:
    """``rewrite(text, edit, alias=None, **spec_fields)``; the spec is inline text by default."""

    def run(
        text: str, edit: Any, *, alias: dict[str, str] | None = None, **fields: Any
    ) -> Rewritten:
        spec = TextSource.model_validate({"content": "x", **fields})
        return rewrite_text(RewriteJob(spec, text, edit, alias or {}, source_ctx))

    return run
