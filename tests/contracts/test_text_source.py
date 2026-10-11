"""Contract tests: ``TextSource`` fields (delimiter, content, encoding, columns, origin)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sankey_studio.models import (
    AppSettings,
    GraphCreate,
    GraphDefinition,
    GraphSummary,
    GraphUpdate,
    Link,
    TextSource,
)


@pytest.mark.parametrize("delimiter", ["\t", " ", ",", ";", "|"])
def test_text_delimiter_survives_verbatim(delimiter: str) -> None:
    src = TextSource(content="a" + delimiter + "b", delimiter=delimiter)
    assert src.delimiter == delimiter


@pytest.mark.parametrize("delimiter", ['"', "\n", "\r", "\0", "", ",,"])
def test_text_delimiter_rejects_unusable_values(delimiter: str) -> None:
    with pytest.raises(ValidationError):
        TextSource(content="a", delimiter=delimiter)


def test_text_content_is_not_whitespace_stripped() -> None:
    content = "\tb\t1\n  \n"
    assert TextSource(content=content).content == content
    assert TextSource(content="\ta\n").content == "\ta\n"
    # other strings still are
    assert Link(source="  a ", target="b", value=1).source == "a"


def test_tab_separated_graph_survives_a_json_round_trip() -> None:
    """Persisted graphs (JSON) must keep a leading tab and a tab delimiter byte for byte."""
    draft = GraphCreate.model_validate(
        {"name": "n", "source": {"type": "text", "content": "\tb\t1\n", "delimiter": "\t"}}
    )
    again = GraphCreate.model_validate_json(draft.model_dump_json())
    assert again == draft
    assert isinstance(again.source, TextSource)
    assert again.source.content == "\tb\t1\n"
    assert again.source.delimiter == "\t"


def test_json_schemas_can_be_generated() -> None:
    """FastAPI builds schemas from these models; custom Annotated types must not break that."""
    for model in (GraphCreate, GraphDefinition, GraphSummary, AppSettings, GraphUpdate):
        assert model.model_json_schema()["type"] == "object"


def test_text_content_cap() -> None:
    with pytest.raises(ValidationError):
        TextSource(content="x" * 2_000_001)


@pytest.mark.parametrize(
    ("given", "canonical"),
    [
        ("utf-8", "utf-8"),
        ("UTF8", "utf-8"),
        ("utf-8-sig", "utf-8-sig"),
        ("utf-16", "utf-16"),
        ("cp1252", "cp1252"),
        ("latin-1", "iso8859-1"),
        ("ascii", "ascii"),
        ("shift_jis", "shift_jis"),
    ],
)
def test_text_encoding_allows_text_codecs_in_canonical_form(given: str, canonical: str) -> None:
    assert TextSource(content="x", encoding=given).encoding == canonical


@pytest.mark.parametrize(
    "encoding",
    [
        "zlib",
        "bz2",
        "base64",
        "hex",
        "rot13",
        "undefined",
        "idna",
        "punycode",
        "unicode_escape",
        "no-such-codec",
        "x" * 33,
        "utf-8\0",
        "",
    ],
)
def test_text_encoding_rejects_non_text_codecs(encoding: str) -> None:
    with pytest.raises(ValidationError):
        TextSource(content="x", encoding=encoding)


def test_text_category_switches_and_column_refs() -> None:
    assert TextSource(content="x").detect_category is True
    assert TextSource(content="x", detect_category=False).detect_category is False
    src = TextSource(content="x", category_column="Tag", source_column=0, value_column="amt")
    assert (src.category_column, src.source_column, src.value_column) == ("Tag", 0, "amt")
    for bad in (-1, "", 10_001):
        with pytest.raises(ValidationError):
            TextSource(content="x", category_column=bad)


def test_text_source_origin_rules() -> None:
    with pytest.raises(ValidationError):
        TextSource(origin="inline")
    with pytest.raises(ValidationError):
        TextSource(origin="file")
    assert TextSource(origin="file", path="a/b.csv").path == "a/b.csv"
    for path in ("/etc/passwd", "~/x", "a\\b", "a//b", "./a", "a/../b", "a\0b"):
        with pytest.raises(ValidationError):
            TextSource(origin="file", path=path)
