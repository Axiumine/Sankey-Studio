"""The self-check: every way an edit is accepted or turned into ``cannot_verify``."""

from __future__ import annotations

import codecs
import importlib
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import MAX_INLINE_CHARS
from sankey_studio.sources.rewrite import REWRITE_MAX_BYTES
from sankey_studio.sources.rewrite.model import Item
from tests.sources.rewrite.support import add, categorise, reorder

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter

HEAD = "source,target,value"


def refused(rewrite: Rewriter, text: str, edit: Any, **fields: Any) -> str:
    with pytest.raises(SourceEditRefused) as info:
        rewrite(text, edit, **fields)
    return info.value.reason


def drop_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deliberately BROKEN tokenizer for the parser (the rewriter keeps the real one)."""
    from sankey_studio.sources.formats import sankeymatic

    real = sankeymatic.split_entry
    monkeypatch.setattr(sankeymatic, "split_entry", lambda text: real(text)._replace(category=None))


@pytest.mark.parametrize("fmt", ["sankeymatic", "auto"])
def test_a_broken_tokenizer_is_cannot_verify(
    rewrite: Rewriter, monkeypatch: pytest.MonkeyPatch, fmt: str
) -> None:
    drop_categories(monkeypatch)
    # the retry (format pinned) fails the same way, and so does the plain refusal
    assert refused(rewrite, "a [1] b\n", categorise("a", "b", "N"), format=fmt) == "cannot_verify"


def test_a_broken_tokenizer_does_not_matter_for_an_edit_it_does_not_touch(
    rewrite: Rewriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    drop_categories(monkeypatch)
    done = rewrite("b [1] c\na [2] b\n", reorder("a", "b", "c"), format="sankeymatic")
    assert done.text == "a [2] b\nb [1] c\n"


def test_an_edit_that_adds_a_warning_is_cannot_verify(
    rewrite: Rewriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("sankey_studio.sources.rewrite.verify")
    real = module.parse_links
    calls: list[int] = []

    def noisy(job: Any, text: str) -> Any:
        links = real(job, text)
        calls.append(1)
        if len(calls) % 2 == 0:  # the parse of the NEW text (the retry parses again)
            job.diag.warn("something new")
        return links

    monkeypatch.setattr(module, "parse_links", noisy)
    assert (
        refused(rewrite, f"{HEAD}\na,b,1\n", categorise("a", "b", "N"), format="csv")
        == "cannot_verify"
    )


def test_a_new_text_the_parser_rejects_is_cannot_verify(
    rewrite: Rewriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sankey_studio.sources.rewrite import sankeymatic as module

    monkeypatch.setattr(module.SankeymaticDoc, "render", lambda _self, _items: "a [oops\n")
    monkeypatch.setattr(
        module.SankeymaticDoc,
        "recategorised",
        lambda _self, item, _c: Item("x\n", item.pair),
    )
    assert (
        refused(rewrite, "a [1] b\n", categorise("a", "b", "N"), format="sankeymatic")
        == "cannot_verify"
    )


def test_the_sniffer_flipping_after_an_edit_is_retried_with_the_old_delimiter(
    rewrite: Rewriter,
) -> None:
    text = "a;b;1\nc;d;2\n"
    # the new first line has more commas than semicolons: the sniffer would now pick ","
    done = rewrite(text, categorise("a", "b", "N,M,O,P,Q"), has_header=False)
    assert done.text == "a;b;1;N,M,O,P,Q\nc;d;2\n"
    assert (done.spec.delimiter, done.spec.format) == (";", "csv")


def test_a_document_that_does_not_load_cannot_be_edited(rewrite: Rewriter) -> None:
    big = '{"source":"a","target":"b","value":1,"pad":"' + "x" * 1_300_000 + '"}'
    assert refused(rewrite, f"[{big}]", categorise("a", "b", "N"), format="json") == "unreadable"


def register_lossy_codec() -> str:
    """A text codec that turns u-umlaut into plain u (so the written file differs)."""

    def encode(text: str, errors: str = "strict") -> tuple[bytes, int]:
        return text.replace("ü", "u").encode("latin-1", errors), len(text)

    def decode(data: Any, errors: str = "strict") -> tuple[str, int]:
        return bytes(data).decode("latin-1", errors), len(data)

    def search(name: str) -> codecs.CodecInfo | None:
        if name.replace("-", "_") != "wp02_lossy":
            return None
        return codecs.CodecInfo(encode, decode, name="wp02-lossy")

    codecs.register(search)
    return "wp02-lossy"


FILE: dict[str, Any] = {"origin": "file", "path": "f.csv", "content": None, "has_header": False}


def test_a_file_that_cannot_be_written_back_the_same_is_cannot_verify(rewrite: Rewriter) -> None:
    fields = {**FILE, "encoding": register_lossy_codec()}
    assert refused(rewrite, "a,b,1\n", add("x", "ü", 2), **fields) == "cannot_verify"


def test_a_character_the_encoding_cannot_hold_is_unrepresentable(rewrite: Rewriter) -> None:
    fields = {**FILE, "encoding": "cp1252"}
    assert refused(rewrite, "a,b,1\n", add("x", "\U0001f600", 2), **fields) == "unrepresentable"


@pytest.mark.parametrize(
    "encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32", "cp1252", "latin-1"]
)
def test_a_file_round_trips_in_its_own_encoding(rewrite: Rewriter, encoding: str) -> None:
    done = rewrite("a,b,1\n", add("x", "é", 2), **{**FILE, "encoding": encoding})
    assert done.text == "a,b,1\nx,é,2\n"


def test_the_utf16_bom_is_added_by_encode_and_stripped_by_decode(rewrite: Rewriter) -> None:
    done = rewrite("a,b,1\n", add("x", "y", 2), **{**FILE, "encoding": "utf-16"})
    assert done.text == "a,b,1\nx,y,2\n"  # no BOM in the text: encode adds it, decode strips it


def test_an_inline_text_is_not_checked_against_an_encoding(rewrite: Rewriter) -> None:
    done = rewrite("a,b,1\n", add("x", "\U0001f600", 2), has_header=False, encoding="cp1252")
    assert done.text == "a,b,1\nx,\U0001f600,2\n"


# ------------------------------------------------------------------ size

LIMIT = 80
BODY = f"{HEAD}\na,b,1\n"


def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    package = "sankey_studio.sources.rewrite"
    monkeypatch.setattr(f"{package}.MAX_INLINE_CHARS", LIMIT)
    monkeypatch.setattr(f"{package}.REWRITE_MAX_BYTES", LIMIT)


def test_the_limits_are_the_documented_ones() -> None:
    assert (MAX_INLINE_CHARS, REWRITE_MAX_BYTES) == (2_000_000, 8 * 1024 * 1024)


class Size(NamedTuple):
    fields: dict[str, Any]
    delta: int
    reason: str | None


SIZES = [Size(f, d, r) for f in ({}, FILE) for d, r in ((0, None), (1, "file_too_large"))]


@pytest.mark.parametrize("case", SIZES, ids=[str(i) for i in range(len(SIZES))])
def test_a_text_above_the_limit_is_too_large(
    rewrite: Rewriter, monkeypatch: pytest.MonkeyPatch, case: Size
) -> None:
    small_limits(monkeypatch)
    text = BODY + "\n" * (LIMIT - len(BODY) + case.delta)
    if case.reason:
        assert refused(rewrite, text, reorder("a", "b"), **case.fields) == case.reason
    else:
        assert rewrite(text, reorder("a", "b"), **case.fields).changed == 0


def test_the_real_limits_refuse_without_parsing(rewrite: Rewriter) -> None:
    assert refused(rewrite, "\n" * (MAX_INLINE_CHARS + 1), reorder("a")) == "file_too_large"
    assert (
        refused(rewrite, "\n" * (REWRITE_MAX_BYTES + 1), reorder("a"), **FILE) == "file_too_large"
    )


GROWS = [Size(f, d, r) for f in ({}, FILE) for d, r in ((0, None), (1, "file_too_large"))]


@pytest.mark.parametrize("case", GROWS, ids=[str(i) for i in range(len(GROWS))])
def test_an_edit_that_pushes_the_text_over_the_limit_is_too_large(
    rewrite: Rewriter, monkeypatch: pytest.MonkeyPatch, case: Size
) -> None:
    small_limits(monkeypatch)
    row = "x,y,1\n"
    text = BODY + "\n" * (LIMIT - len(BODY) - len(row) + case.delta)  # the new row fits / not
    if case.reason:
        assert refused(rewrite, text, add("x", "y", 1), **case.fields) == case.reason
    else:
        assert len(rewrite(text, add("x", "y", 1), **case.fields).text) == LIMIT
