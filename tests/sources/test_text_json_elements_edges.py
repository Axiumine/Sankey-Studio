"""Skipped array elements under hostile input: chunk edges, the entry cap and a bounded buffer."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.models import TextSource
from sankey_studio.sources.base import CategoryCleaner, Diagnostics
from sankey_studio.sources.formats.job import ParseJob
from sankey_studio.sources.formats.json_rows import CHUNK_CHARS, MAX_OBJECT_CHARS, json_links
from tests.sources.idtools import safe_id
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext

NOT_OBJECT = "inline:1: each entry must be a JSON object"
A = '{"source":"a","target":"b","value":1}'
TOKENS = [
    "12345",
    "1.5",
    "1e5",
    "-12.5e-3",
    "1E+10",
    "0",
    "null",
    "true",
    "false",
    "NaN",
    "-Infinity",
    '"str"',
    "[1,2]",
]
#: Beyond the entry cap even after the buffer overshoots it by a chunk (inline text is <= 2M).
OVER = MAX_OBJECT_CHARS + 2 * CHUNK_CHARS
CUTS = [(token, cut) for token in TOKENS for cut in range(len(token) + 1)]


@pytest.mark.parametrize(
    ("token", "cut"), CUTS, ids=[safe_id(f"{token}@{cut}") for token, cut in CUTS]
)
def test_an_element_cut_by_a_chunk_edge_is_read_whole(
    source_ctx: SourceContext, token: str, cut: int
) -> None:
    # The first chunk ends after ``cut`` characters of the token (0: the token opens chunk two;
    # len(token): the token ends the chunk and its comma opens the next).
    start = CHUNK_CHARS - cut
    text = "[" + " " * (start - 1) + token + f",{A}]"
    assert text[start : start + len(token)] == token
    out = inline(source_ctx, text, format="json")
    assert out.rows == [("a", "b", 1.0, None)]
    assert out.warnings == [NOT_OBJECT]


def test_a_number_at_the_very_end_of_the_text_is_read_whole(source_ctx: SourceContext) -> None:
    with pytest.raises(SourceError) as info:
        inline(source_ctx, f"[{A}, 12345", format="json")
    assert str(info.value) == "inline:1: the JSON array is not closed"


def test_a_large_element_within_the_cap_is_skipped(source_ctx: SourceContext) -> None:
    text = f'[{A},"{"x" * (MAX_OBJECT_CHARS // 2)}",{A}]'
    out = inline(source_ctx, text, format="json")
    assert len(out.rows) == 2
    assert out.warnings == [NOT_OBJECT]


def test_an_element_over_the_cap_is_a_source_error(source_ctx: SourceContext) -> None:
    text = f'[{A},"{"x" * OVER}",{A}]'
    with pytest.raises(SourceError) as info:
        inline(source_ctx, text, format="json")
    assert str(info.value) == "inline:1: invalid JSON (Unterminated string starting at)"


def test_a_number_over_the_cap_is_a_source_error_not_a_whole_buffer(
    source_ctx: SourceContext,
) -> None:
    text = f"[{A},0.{'1' * OVER},{A}]"
    with pytest.raises(SourceError) as info:
        inline(source_ctx, text, format="json")
    assert str(info.value) == "inline:1: expected ',' or ']' between entries"


class CountingText(io.StringIO):
    """A text stream that remembers every read size."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.reads: list[int] = []

    def read(self, size: int | None = -1, /) -> str:
        self.reads.append(-1 if size is None else size)
        return super().read(size)


FIRST_ELEMENTS = ["", "1,", "null,", '"s",', "[1],", "-2.5e3,", "true,"]


@pytest.mark.parametrize("first", FIRST_ELEMENTS, ids=[safe_id(first) for first in FIRST_ELEMENTS])
def test_the_first_row_costs_one_chunk_however_long_the_array_is(
    source_ctx: SourceContext, first: str
) -> None:
    objects = ",".join([A] * 6000)
    stream = CountingText(f"[{first}{objects}]")
    diag = Diagnostics()
    spec = TextSource(content="x", format="json")
    job = ParseJob(spec, source_ctx, diag, CategoryCleaner(diag), "t", "json", "")
    rows = json_links(job, stream)
    assert next(rows) == ("a", "b", 1.0, None)
    assert stream.reads == [CHUNK_CHARS]  # a mistaken "number may go on" would read to the cap
