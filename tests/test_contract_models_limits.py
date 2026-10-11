"""Boundary tables for every numeric / length limit of the spec and settings models.

Each row names a model, the minimal valid input, one field, the values at and just inside the
limit (must be accepted) and the first values outside it (must be refused). A moved limit, a
``>`` turned into ``>=`` or a dropped constraint fails exactly one row.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from sankey_studio.models import (
    AppSettings,
    CategoryRule,
    DonutStyle,
    EntryCategory,
    GraphCreate,
    GraphDefinition,
    GraphUpdate,
    Link,
    ManualSource,
    MongoConnection,
    MongoSource,
    StyleSpec,
    TextSource,
    TransformSpec,
)

NOW = "2026-01-02T03:04:05+00:00"
INF = math.inf
NAN = math.nan


@dataclass(frozen=True, slots=True)
class Row:
    model: type[BaseModel]
    base: dict[str, Any]
    field: str
    ok: tuple[Any, ...]
    bad: tuple[Any, ...]

    @property
    def id(self) -> str:
        return f"{self.model.__name__}.{self.field}"


def s(n: int) -> str:
    return "x" * n


LINK = {"source": "a", "target": "b", "value": 1}
MONGO = {"connection": "c", "collection": "events"}
TEXT = {"content": "a,b,1"}
FILE = {"origin": "file", "path": "a.csv"}
GRAPH = {"source": {"type": "manual"}, "name": "n"}
CONN = {"name": "c", "uri": SecretStr("mongodb://h/")}
DEFINITION = {**GRAPH, "id": "0" * 32, "created_at": NOW, "updated_at": NOW}
BAD_NAMES = ("", "   ", s(201), "a\0b")
GOOD_NAMES = ("a", s(200), "two words")
COLUMN_OK = (0, 10_000, "a", s(200))
COLUMN_BAD = (-1, 10_001, "", s(201))
FIELD_OK = ("a", "a.b", "_a", "a-b.c1", "A9")
FIELD_BAD = ("", "1a", "a..b", "a.", ".a", "$a", "a b", "a$b")
CONN_NAME_OK = ("a", s(64), "a.b_c-d")
CONN_NAME_BAD = ("", s(65), "a b", "a/b", "a:b")

ROWS = [
    Row(Link, LINK, "value", (1e-300, 1, 1e300), (0, -1, -1e-300, INF, -INF, NAN)),
    Row(Link, LINK, "source", GOOD_NAMES, BAD_NAMES),
    Row(Link, LINK, "target", GOOD_NAMES, BAD_NAMES),
    Row(Link, LINK, "category", (None, "", "x", s(100)), (s(101), "Other", "a\x00b")),
    Row(TransformSpec, {}, "min_link_value", (0, 0.0, 1e300), (-0.1, -1, INF, NAN)),
    Row(TransformSpec, {}, "top_links", (None, 1, 10**9), (0, -1)),
    Row(TransformSpec, {}, "on_cycle", ("error", "break"), ("", "ignore")),
    Row(EntryCategory, {"source": "a", "target": "b"}, "category", (None, "x"), ("Other",)),
    Row(CategoryRule, {"category": "x"}, "pattern", ("*", s(200), "a?[bc]"), ("", s(201), "a\0")),
    Row(CategoryRule, {"pattern": "*"}, "category", ("x", s(100)), ("", s(101), "Uncategorized")),
    Row(
        CategoryRule, {"pattern": "*", "category": "x"}, "match", ("source", "target"), ("", "any")
    ),
    Row(DonutStyle, {}, "max_slices", (2, 6, 8), (1, 9, 0, -1)),
    Row(DonutStyle, {}, "hole", (0.3, 0.58, 0.85), (0.29, 0.86, 0, 1)),
    Row(DonutStyle, {}, "basis", ("all", "initial", "terminal"), ("", "middle")),
    Row(StyleSpec, {}, "title", (None, "", s(200)), (s(201),)),
    Row(StyleSpec, {}, "node_pad", (0, 16, 100), (-1, 101)),
    Row(StyleSpec, {}, "node_thickness", (1, 18, 100), (0, 101)),
    Row(StyleSpec, {}, "link_opacity", (0.05, 0.4, 1.0), (0.04, 1.01, 0, 2)),
    Row(StyleSpec, {}, "font_size", (8, 13, 32), (7, 33)),
    Row(StyleSpec, {}, "height", (240, 560, 2400), (239, 2401)),
    Row(StyleSpec, {}, "value_suffix", ("", s(20)), (s(21),)),
    Row(
        StyleSpec, {}, "value_format", ("", ",.2~f", s(24), "$,.0f", "+.1%"), (s(25), "a;b", "a\nb")
    ),
    Row(StyleSpec, {}, "orientation", ("h", "v"), ("", "x")),
    Row(StyleSpec, {}, "color_mode", ("node", "layer", "mono", "category"), ("", "x")),
    Row(StyleSpec, {}, "arrangement", ("snap", "freeform", "fixed"), ("", "x")),
    Row(MongoSource, MONGO, "limit", (1, 10_000, 1_000_000), (0, -1, 1_000_001)),
    Row(MongoSource, MONGO, "max_time_ms", (None, 100, 300_000), (99, 0, 300_001)),
    Row(MongoSource, MONGO, "database", (None, "flows", s(64)), (s(65), "admin", "a b", "")),
    Row(MongoSource, MONGO, "collection", ("a", s(120), "x.y"), ("", s(121), "a$b", "system.a")),
    Row(MongoSource, MONGO, "connection", CONN_NAME_OK, CONN_NAME_BAD),
    Row(MongoSource, MONGO, "source_field", FIELD_OK, FIELD_BAD),
    Row(MongoSource, MONGO, "target_field", FIELD_OK, FIELD_BAD),
    Row(MongoSource, MONGO, "value_field", (None, *FIELD_OK), FIELD_BAD),
    Row(MongoSource, MONGO, "category_field", (None, *FIELD_OK), FIELD_BAD),
    Row(MongoSource, MONGO, "mode", ("find",), ("", "delete")),
    Row(
        TextSource, TEXT, "delimiter", (None, ",", "\t", " ", ";", "|"), ("", ",,", '"', "\n", "\0")
    ),
    Row(TextSource, TEXT, "content", ("", s(2_000_000)), (s(2_000_001),)),
    Row(
        TextSource,
        TEXT,
        "encoding",
        ("utf-8", "cp1252", "latin-1"),
        ("nope", "zlib", "idna", s(33)),
    ),
    Row(TextSource, TEXT, "source_column", (None, *COLUMN_OK), COLUMN_BAD),
    Row(TextSource, TEXT, "target_column", (None, *COLUMN_OK), COLUMN_BAD),
    Row(TextSource, TEXT, "value_column", (None, *COLUMN_OK), COLUMN_BAD),
    Row(TextSource, TEXT, "category_column", (None, *COLUMN_OK), COLUMN_BAD),
    Row(TextSource, TEXT, "format", ("auto", "csv", "tsv", "sankeymatic", "json"), ("", "xml")),
    Row(
        TextSource,
        {"origin": "file"},
        "path",
        ("a.csv", "d/a.csv", s(255), "a b/c.txt"),
        ("", "/a", "~/a", "a\\b", "a\0b", ".", "..", "a/../b", "a//b", "./a", "a/", s(256)),
    ),
    Row(AppSettings, {}, "max_links", (100, 200_000, 5_000_000), (99, 5_000_001)),
    Row(AppSettings, {}, "max_drawn_links", (50, 3_000, 20_000), (49, 20_001)),
    Row(AppSettings, {}, "max_upload_mb", (1, 25, 100), (0, 101)),
    Row(AppSettings, {}, "mongo_timeout_ms", (500, 15_000, 300_000), (499, 300_001)),
    Row(AppSettings, {}, "storage_database", ("flows", s(64)), ("", s(65), "admin", "a.b")),
    Row(AppSettings, {}, "theme", ("system", "light", "dark"), ("", "blue")),
    Row(AppSettings, {}, "storage_backend", ("file",), ("", "sqlite")),
    Row(MongoConnection, CONN, "name", CONN_NAME_OK, CONN_NAME_BAD),
    Row(MongoConnection, CONN, "default_database", (None, "flows", s(64)), (s(65), "local", "a/b")),
    Row(GraphCreate, GRAPH, "name", ("a", s(200)), ("", "   ", s(201))),
    Row(GraphCreate, GRAPH, "description", ("", s(2000)), (s(2001),)),
    Row(GraphUpdate, {**GRAPH, "revision": 1}, "revision", (1, 2, 10**9), (0, -1)),
    Row(
        GraphDefinition,
        DEFINITION,
        "id",
        ("0" * 32, "a" * 32, "0123456789abcdef" * 2),
        (
            "",
            "0" * 31,
            "0" * 33,
            "G" * 32,
            "A" * 32,
            "../" + "0" * 29,
        ),
    ),
    Row(GraphDefinition, DEFINITION, "schema_version", (1, 2, 10**6), (0, -1)),
    Row(GraphDefinition, DEFINITION, "revision", (1, 2, 10**6), (0, -1)),
    Row(
        GraphDefinition,
        DEFINITION,
        "created_at",
        (NOW, "2026-01-02T03:04:05Z"),
        (
            "2026-01-02T03:04:05",
            "yesterday",
            "",
        ),
    ),
]


@pytest.mark.parametrize("row", ROWS, ids=[row.id for row in ROWS])
def test_value_limits(row: Row) -> None:
    for value in row.ok:
        row.model.model_validate({**row.base, row.field: value})
    for value in row.bad:
        with pytest.raises(ValidationError):
            row.model.model_validate({**row.base, row.field: value})


def test_accepted_values_are_stored_as_given() -> None:
    assert StyleSpec(node_pad=100).node_pad == 100
    assert StyleSpec(link_opacity=0.05).link_opacity == 0.05
    assert DonutStyle(max_slices=8, hole=0.85).hole == 0.85
    assert AppSettings(max_links=100).max_links == 100
    assert MongoSource.model_validate({**MONGO, "limit": 1_000_000}).limit == 1_000_000
    assert Link.model_validate({**LINK, "value": 1e-300}).value == 1e-300


# --------------------------------------------------------------------------- list sizes


@dataclass(frozen=True, slots=True)
class Size:
    name: str
    limit: int
    build: Any  # (count) -> model

    def make(self, count: int) -> object:
        return self.build(count)


def links(count: int) -> ManualSource:
    return ManualSource(links=[Link.model_validate(LINK)] * count)


def hide(count: int) -> TransformSpec:
    return TransformSpec(hide_nodes=[f"n{i}" for i in range(count)])


def merge(count: int) -> TransformSpec:
    return TransformSpec(merge_nodes={f"a{i}": f"b{i}" for i in range(count)})


def entries(count: int) -> TransformSpec:
    items = [{"source": f"a{i}", "target": "b", "category": None} for i in range(count)]
    return TransformSpec.model_validate({"entry_categories": items})


def rules(count: int) -> TransformSpec:
    items = [{"pattern": f"p{i}", "category": "c"} for i in range(count)]
    return TransformSpec.model_validate({"category_rules": items})


def pipeline(count: int) -> MongoSource:
    return MongoSource.model_validate({**MONGO, "pipeline": [{"$match": {}}] * count})


def node_colors(count: int) -> StyleSpec:
    return StyleSpec(node_colors={f"n{i}": "#aabbcc" for i in range(count)})


def category_colors(count: int) -> StyleSpec:
    return StyleSpec(category_colors={f"c{i}": "#aabbcc" for i in range(count)})


def connections(count: int) -> AppSettings:
    items = [MongoConnection(name=f"c{i}", uri=SecretStr("mongodb://h/")) for i in range(count)]
    return AppSettings(mongo_connections=items)


def tags(count: int) -> GraphCreate:
    return GraphCreate.model_validate({**GRAPH, "tags": [f"t{i}" for i in range(count)]})


SIZES = [
    Size("ManualSource.links", 5_000, links),
    Size("TransformSpec.hide_nodes", 1_000, hide),
    Size("TransformSpec.merge_nodes", 5_000, merge),
    Size("TransformSpec.entry_categories", 20_000, entries),
    Size("TransformSpec.category_rules", 200, rules),
    Size("MongoSource.pipeline", 50, pipeline),
    Size("StyleSpec.node_colors", 1_000, node_colors),
    Size("StyleSpec.category_colors", 1_000, category_colors),
    Size("AppSettings.mongo_connections", 20, connections),
    Size("GraphCreate.tags", 20, tags),
]


@pytest.mark.parametrize("size", SIZES, ids=[size.name for size in SIZES])
def test_list_size_limits(size: Size) -> None:
    size.make(size.limit)
    with pytest.raises(ValidationError):
        size.make(size.limit + 1)


# --------------------------------------------------------------------------- tags


def test_tags_are_stripped_deduplicated_and_blank_ones_dropped() -> None:
    graph = GraphCreate.model_validate({**GRAPH, "tags": [" a ", "b", "a", "", "  ", "b "]})
    assert graph.tags == ["a", "b"]


def test_tag_length_limit_message() -> None:
    GraphCreate.model_validate({**GRAPH, "tags": [s(40)]})
    with pytest.raises(ValidationError) as info:
        GraphCreate.model_validate({**GRAPH, "tags": ["ok", s(41)]})
    assert info.value.errors(include_input=False)[0]["msg"] == (
        "Value error, tags are limited to 40 characters"
    )


def test_tag_count_limit_counts_before_deduplication() -> None:
    GraphCreate.model_validate({**GRAPH, "tags": ["a"] * 20})
    with pytest.raises(ValidationError):
        GraphCreate.model_validate({**GRAPH, "tags": ["a"] * 21})


# --------------------------------------------------------------------------- cross-field messages


def test_aggregate_mode_needs_a_pipeline() -> None:
    with pytest.raises(ValidationError) as info:
        MongoSource.model_validate({**MONGO, "mode": "aggregate"})
    assert info.value.errors(include_input=False)[0]["msg"] == (
        "Value error, pipeline must not be empty in 'aggregate' mode"
    )
    MongoSource.model_validate({**MONGO, "mode": "aggregate", "pipeline": [{"$match": {}}]})
    MongoSource.model_validate({**MONGO, "mode": "find", "pipeline": []})


def test_text_origin_requirements() -> None:
    inline = "Value error, content is required when origin is 'inline'"
    file = "Value error, path is required when origin is 'file'"
    relative = "Value error, path must be a relative POSIX path inside the sources directory"
    cases: tuple[tuple[dict[str, Any], str], ...] = (
        ({}, inline),
        ({"origin": "file"}, file),
        ({"origin": "file", "path": ""}, relative),
    )
    for data, message in cases:
        with pytest.raises(ValidationError) as info:
            TextSource.model_validate(data)
        assert info.value.errors(include_input=False)[0]["msg"] == message
    TextSource.model_validate({"content": ""})
    TextSource.model_validate({"origin": "inline", "content": "x", "path": "ignored.csv"})


def test_defaults_of_the_spec_models() -> None:
    source = MongoSource.model_validate(MONGO)
    assert (source.limit, source.max_time_ms, source.mode) == (10_000, None, "find")
    assert (source.source_field, source.target_field, source.value_field) == (
        "source",
        "target",
        "value",
    )
    assert source.category_field is None
    text = TextSource.model_validate(TEXT)
    assert (text.format, text.encoding, text.has_header, text.detect_category) == (
        "auto",
        "utf-8",
        True,
        True,
    )
    transform = TransformSpec()
    assert (transform.min_link_value, transform.top_links, transform.on_cycle) == (
        0.0,
        None,
        "error",
    )
    assert (transform.strict, transform.rules_override) == (False, False)
    style = StyleSpec()
    assert (style.node_pad, style.node_thickness, style.link_opacity) == (16, 18, 0.4)
    assert (style.font_size, style.height, style.color_mode) == (13, 560, "node")
    assert DonutStyle().hole == 0.58
    settings = AppSettings()
    assert (settings.max_links, settings.max_drawn_links) == (200_000, 3_000)
    assert (settings.max_upload_mb, settings.mongo_timeout_ms) == (25, 15_000)
    assert (settings.storage_database, settings.theme) == ("sankey_studio", "system")
