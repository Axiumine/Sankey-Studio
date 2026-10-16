# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""JSON decode errors name the line where the failing block starts (an exact lower bound)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.json_rows import CHUNK_CHARS
from tests.sources.text_support import of_file, put

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext


def test_the_line_counts_the_newlines_of_the_unfinished_object(
    source_ctx: SourceContext,
) -> None:
    # One pretty-printed object spans the chunk edge: the buffer holds several of its lines
    # when the next block fails to decode, so the reported line is the one at the chunk edge.
    keys = b"".join(b'  "k%d": 1,\n' % index for index in range(8000))
    data = b'[\n{\n  "source": "a",\n' + keys + b'  "bad": "\xff"\n}]'
    assert data.index(b"\xff") > CHUNK_CHARS + 8192  # outside the block that holds the edge
    put(source_ctx, "edge.json", data)
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "edge.json", format="json")
    edge_line = 1 + data[:CHUNK_CHARS].count(b"\n")
    assert edge_line > 3  # the object began on line 2: its own newlines are in the count
    assert str(info.value) == (
        f"edge.json:{edge_line}: cannot decode the data as utf-8 (at or after this line)"
    )
