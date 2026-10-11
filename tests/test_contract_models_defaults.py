"""Defaults, literal value sets and shared constants of the models (what the UI sends and reads)."""

from __future__ import annotations

import codecs
import dataclasses
from array import array
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr, TypeAdapter, ValidationError

from sankey_studio import config
from sankey_studio.config import LOOPBACK_HOSTS, WILDCARD_HOSTS, BootstrapConfig
from sankey_studio.models import (
    CATEGORY_MAX,
    ENTRIES_PAGE_MAX,
    ENTRIES_PREVIEW_LIMIT,
    MAX_CATEGORIES,
    NAME_MAX,
    OTHER,
    SCHEMA_VERSION,
    TAG_MAX,
    UNCATEGORIZED,
    AppSettings,
    CategoryRule,
    GraphCreate,
    GraphDefinition,
    GraphSummary,
    ManualSource,
    MongoConnection,
    MongoSource,
    SankeyGraph,
    StyleSpec,
    TextSource,
    Theme,
)
from sankey_studio.models.style import DonutStyle
from sankey_studio.mongo_safety import validate_db_name
from sankey_studio.sources.base import Diagnostics, SourceContext

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.mongo import MongoClients

NOW = "2026-01-02T03:04:05+00:00"
MANUAL: dict[str, Any] = {"type": "manual"}


def test_shared_constants_are_pinned() -> None:
    assert (NAME_MAX, TAG_MAX, CATEGORY_MAX, MAX_CATEGORIES) == (200, 40, 100, 200)
    assert (UNCATEGORIZED, OTHER) == ("Uncategorized", "Other")
    assert (ENTRIES_PREVIEW_LIMIT, ENTRIES_PAGE_MAX) == (2_000, 500)
    assert SCHEMA_VERSION == 1


def test_spec_models_are_strict_and_validate_on_assignment() -> None:
    style = StyleSpec()
    with pytest.raises(ValidationError):
        style.node_pad = 500
    assert style.node_pad == 16
    style.node_pad = 20
    assert style.node_pad == 20
    with pytest.raises(ValidationError):
        StyleSpec.model_validate({"unknown": 1})
    assert StyleSpec(title="  padded  ").title == "padded"


@pytest.mark.parametrize(
    ("model", "field", "values"),
    [
        (CategoryRule, "match", ("source", "target", "either")),
        (StyleSpec, "arrangement", ("snap", "perpendicular", "freeform", "fixed")),
        (DonutStyle, "sort", ("value", "name")),
        (TextSource, "origin", ("inline", "file")),
        (AppSettings, "storage_backend", ("file",)),
    ],
)
def test_literal_sets_accept_every_member_and_nothing_else(
    model: Any, field: str, values: tuple[str, ...]
) -> None:
    base: dict[str, Any] = {
        CategoryRule: {"pattern": "*", "category": "x"},
        TextSource: {"content": "x", "path": "a.csv"},
    }.get(model, {})
    for value in values:
        assert getattr(model.model_validate({**base, field: value}), field) == value
    with pytest.raises(ValidationError):
        model.model_validate({**base, field: "nonsense"})


def test_source_type_tags_select_the_variant() -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(GraphCreate)
    for tag, expected in (("manual", ManualSource), ("text", TextSource), ("mongo", MongoSource)):
        data: dict[str, Any] = {
            "manual": MANUAL,
            "text": {"type": "text", "content": "a,b,1"},
            "mongo": {"type": "mongo", "connection": "c", "collection": "x"},
        }
        graph = adapter.validate_python({"name": "n", "source": data[tag]})
        assert isinstance(graph.source, expected)
        assert graph.source.type == tag
    with pytest.raises(ValidationError):
        adapter.validate_python({"name": "n", "source": {"type": "csv"}})
    with pytest.raises(ValidationError):
        adapter.validate_python({"name": "n", "source": {}})


def test_source_models_default_their_type_tag() -> None:
    assert ManualSource().type == "manual"
    assert TextSource(content="x").type == "text"
    assert MongoSource(connection="c", collection="x").type == "mongo"
    with pytest.raises(ValidationError):
        ManualSource.model_validate({"type": "text"})


def test_theme_and_summary_literals() -> None:
    assert [TypeAdapter(Theme).validate_python(v) for v in ("light", "dark")] == ["light", "dark"]
    with pytest.raises(ValidationError):
        TypeAdapter(Theme).validate_python("system")
    base = {"id": "0" * 32, "name": "n", "description": "", "tags": [], "revision": 1}
    for source_type in ("manual", "text", "mongo"):
        summary = GraphSummary.model_validate(
            {**base, "source_type": source_type, "updated_at": NOW}
        )
        assert summary.source_type == source_type
    with pytest.raises(ValidationError):
        GraphSummary.model_validate({**base, "source_type": "csv", "updated_at": NOW})


def test_graph_defaults() -> None:
    graph = GraphCreate.model_validate({"name": "n", "source": MANUAL})
    assert (graph.description, graph.tags) == ("", [])
    definition = GraphDefinition.model_validate(
        {"name": "n", "source": MANUAL, "id": "0" * 32, "created_at": NOW, "updated_at": NOW}
    )
    assert (definition.revision, definition.schema_version) == (1, SCHEMA_VERSION)


def test_style_defaults() -> None:
    style = StyleSpec()
    assert (style.title, style.orientation, style.arrangement) == (None, "h", "snap")
    assert (style.node_colors, style.category_colors) == ({}, {})
    assert (style.value_suffix, style.show_values_in_labels) == ("", False)
    donut = style.donut
    assert (donut.basis, donut.max_slices, donut.hole) == ("all", 6, 0.58)
    assert (donut.show_percent, donut.show_total, donut.sort) == (True, True, "value")


def test_rule_and_settings_defaults() -> None:
    assert CategoryRule(pattern="*", category="x").match == "either"
    settings = AppSettings()
    assert (settings.storage_backend, settings.storage_connection) == ("file", None)
    assert (settings.mongo_connections, settings.default_style) == ([], StyleSpec())
    connection = MongoConnection(name="c", uri=SecretStr("mongodb://h/"))
    assert connection.default_database is None


def test_text_source_defaults() -> None:
    text = TextSource(content="x")
    assert (text.origin, text.path, text.delimiter) == ("inline", None, None)
    assert (text.source_column, text.target_column, text.value_column) == (None, None, None)
    assert text.category_column is None


# --------------------------------------------------------------------------- name sets


@pytest.mark.parametrize("name", ["X", "Xa", "aXb", "XX"])
def test_the_letter_x_is_an_ordinary_database_name_character(name: str) -> None:
    assert validate_db_name(name) == name


@pytest.mark.parametrize("delimiter", ["X", "x", "|", ";", "\t", " "])
def test_ordinary_delimiters_are_accepted(delimiter: str) -> None:
    assert TextSource(content="x", delimiter=delimiter).delimiter == delimiter


@pytest.mark.parametrize(
    "encoding",
    [
        "undefined",
        "idna",
        "punycode",
        "unicode-escape",
        "unicode_escape",
        "raw-unicode-escape",
        "raw_unicode_escape",
        "charmap",
        "zlib",
        "base64",
        "hex",
        "rot13",
    ],
)
def test_encodings_that_are_not_data_file_encodings_are_refused(encoding: str) -> None:
    with pytest.raises(ValidationError):
        TextSource(content="x", encoding=encoding)


@pytest.mark.parametrize(
    ("given", "canonical"),
    [("UTF8", "utf-8"), ("utf_8_sig", "utf-8-sig"), ("latin1", "iso8859-1"), ("cp1252", "cp1252")],
)
def test_encodings_are_stored_in_canonical_form(given: str, canonical: str) -> None:
    assert TextSource(content="x", encoding=given).encoding == canonical


@pytest.fixture
def long_codecs() -> Iterator[tuple[str, str]]:
    """Two registered text codecs whose names are exactly 32 and 33 characters long."""
    short, long = "c" * 32, "c" * 33

    def search(name: str) -> codecs.CodecInfo | None:
        if name not in {short, long}:
            return None
        utf8 = codecs.lookup("utf-8")
        return codecs.CodecInfo(utf8.encode, utf8.decode, name=name)

    codecs.register(search)
    try:
        yield short, long
    finally:
        codecs.unregister(search)


def test_encoding_name_length_limit(long_codecs: tuple[str, str]) -> None:
    short, long = long_codecs
    assert TextSource(content="x", encoding=short).encoding == short
    with pytest.raises(ValidationError):
        TextSource(content="x", encoding=long)


# --------------------------------------------------------------------------- dataclasses


def empty_graph() -> SankeyGraph:
    return SankeyGraph(
        node_names=(),
        node_layers=(),
        node_color_slot=(),
        node_in=(),
        node_out=(),
        link_source=array("i"),
        link_target=array("i"),
        link_value=array("d"),
        link_category=array("i"),
    )


def test_graph_is_frozen_and_slotted() -> None:
    graph = empty_graph()
    assert not hasattr(graph, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.categories = ("x",)  # type: ignore[misc]
    assert graph.categories == ()
    assert graph.category_color_slot == ()
    assert graph.warnings == ()


def test_diagnostics_are_slotted_and_context_is_frozen_and_lenient_by_default(
    app_settings: AppSettings, mongo_clients: MongoClients, tmp_path: Path
) -> None:
    ctx = SourceContext(settings=app_settings, sources_dir=tmp_path, mongo=mongo_clients)
    assert not hasattr(Diagnostics(), "__dict__")
    assert not hasattr(ctx, "__dict__")
    assert ctx.strict is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.strict = True  # type: ignore[misc]
    assert ctx.strict is False


# --------------------------------------------------------------------------- bootstrap config


def test_bootstrap_constants_and_defaults(tmp_path: Path) -> None:
    assert {"127.0.0.1", "localhost", "::1", "[::1]"} == LOOPBACK_HOSTS
    assert {"0.0.0.0", "::", ""} == WILDCARD_HOSTS  # noqa: S104 - pins the refused binds
    defaults = BootstrapConfig(data_dir=tmp_path)
    assert (defaults.host, defaults.port, defaults.log_level) == ("127.0.0.1", 8765, "info")
    assert defaults.allowed_hosts == ["localhost", "127.0.0.1", "[::1]"]
    assert (defaults.remote_mode, defaults.remote_writes, defaults.sources_dir) == (
        False,
        False,
        None,
    )
    assert config.default_data_dir().name == "sankey-studio"


@pytest.mark.parametrize("host", ["::", ""])
def test_wildcard_binds_never_become_allowed_hosts(host: str, tmp_path: Path) -> None:
    built = BootstrapConfig(data_dir=tmp_path, host=host, remote_mode=True)
    assert built.allowed_hosts == ["localhost", "127.0.0.1", "[::1]"]


def test_unknown_sankey_variables_and_keywords_are_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SANKEY_NOT_A_SETTING", "1")
    assert BootstrapConfig(data_dir=tmp_path).port == 8765
    assert BootstrapConfig(data_dir=tmp_path, not_a_setting=1).port == 8765  # type: ignore[call-arg]
