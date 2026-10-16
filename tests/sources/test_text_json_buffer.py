# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""JSON buffer accounting: the object budget counts what is left AFTER the cursor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.json_rows import CHUNK_CHARS, MAX_OBJECT_CHARS
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext

HEAD = '[{"source":"a","target":"b","value":1,"pad":"'
BETWEEN = '"},'
SECOND = '{"source":"c","target":"d","value":2}]'


def test_a_small_object_behind_a_big_one_is_not_charged_for_the_big_one(
    source_ctx: SourceContext,
) -> None:
    # The first object ends 10 characters before a chunk boundary far into the text, so the
    # second one is cut in two by that boundary. The undecoded part is 10 characters long,
    # however far the cursor has moved.
    boundary = CHUNK_CHARS * (MAX_OBJECT_CHARS // (2 * CHUNK_CHARS) + 1)
    pad = boundary - 10 - len(HEAD) - len(BETWEEN)
    text = HEAD + "x" * pad + BETWEEN + SECOND
    assert text[boundary - 10] == "{"
    assert 2 * boundary > MAX_OBJECT_CHARS > boundary
    out = inline(source_ctx, text, format="json")
    assert out.rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]
    assert out.warnings == []


GARBAGE = [
    'r{"source":"a","target":"b","value":1}',
    '[r{"source":"a","target":"b","value":1}]',
    '{"source":"a","target":"b","value":1}\nr{"source":"a","target":"b","value":1}',
]


@pytest.mark.parametrize("text", GARBAGE, ids=["ndjson-start", "array", "ndjson-second"])
def test_only_json_whitespace_may_sit_between_entries(source_ctx: SourceContext, text: str) -> None:
    with pytest.raises(SourceError) as info:
        inline(source_ctx, text, format="json")
    assert str(info.value).endswith(": each entry must be a JSON object")
