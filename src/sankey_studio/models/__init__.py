"""Shared domain models: the contract every other module builds on.

Three families live here:

* **Spec models** (pydantic, persisted + sent over the API): ``SourceSpec`` variants,
  ``TransformSpec``, ``StyleSpec``, ``GraphDraft`` / ``GraphCreate`` / ``GraphDefinition``.
* **Settings models** (pydantic, persisted in ``settings.json``): ``AppSettings``.
* **Built graph** (plain dataclass, never persisted): ``SankeyGraph`` - columnar and
  lean on purpose, because graphs can hold hundreds of thousands of links.

Pipeline:  ``SourceSpec`` -> ``DataSource.iter_links`` -> ``build_graph`` ->
``SankeyGraph`` -> ``build_figure`` (Sankey) / ``build_donut_figure`` (donut) -> Plotly dict.

Every entry (link) may carry a **category**, and categorising is OPTIONAL everywhere: every
category field is nullable and a graph without categories is a plain Sankey. The user assigns a
category in the web UI (per entry via ``TransformSpec.entry_categories``, or by manual-link input),
or it comes from the data (a column / document field) or from glob ``TransformSpec.category_rules``.
Categories drive the donut chart and optionally the Sankey link colors; both charts share one
category -> color map.

Category identity: names are normalised (NFC, trimmed, inner whitespace collapsed) and compared
case-insensitively (``util.category_key``); the display spelling is the first one seen. The names
``Uncategorized`` and ``Other`` (any case) are RESERVED for the renderer: user-authored specs
reject them, data sources turn them into ``None`` with an aggregated warning.

Models used as request bodies forbid unknown fields. ``GraphDefinition`` (the persisted shape)
ignores unknown top-level fields and carries ``schema_version`` so old graphs stay readable.
Spec models are values: never mutate them (``validate_assignment`` runs the after-validators on
every single assignment, so a two-step edit can fail halfway); rebuild with
``Model.model_validate({**m.model_dump(), "field": value})``.
"""

from __future__ import annotations

from sankey_studio.models.base import (
    _VALUE_FORMAT_RE,
    CATEGORY_MAX,
    CONNECTION_NAME_RE,
    ENTRIES_PAGE_MAX,
    ENTRIES_PREVIEW_LIMIT,
    FIELD_PATH_RE,
    GRAPH_ID_PATTERN,
    HEX_COLOR_RE,
    INDEX_TYPECODE,
    MAX_CATEGORIES,
    MAX_COLOR_OVERRIDES,
    MAX_ENTRY_CATEGORIES,
    MAX_HIDE_NODES,
    MAX_INLINE_CHARS,
    MAX_MANUAL_LINKS,
    MAX_MERGE_NODES,
    NAME_MAX,
    OTHER,
    SCHEMA_VERSION,
    TAG_MAX,
    UNCATEGORIZED,
    VALUE_TYPECODE,
    _Model,
)
from sankey_studio.models.fields import (
    GraphId,
    NameStr,
    OptUserCategory,
    UserCategory,
    _name_check,
    _optional_user_category,
    _safe_name,
    _user_category,
)
from sankey_studio.models.graph import RawLink, SankeyGraph, Theme
from sankey_studio.models.graphs import (
    GraphCreate,
    GraphDefinition,
    GraphDraft,
    GraphSummary,
    GraphUpdate,
)
from sankey_studio.models.settings import AppSettings, MongoConnection
from sankey_studio.models.sources import (
    _BAD_DELIMITERS,
    _ENCODING_DENY,
    ColumnRef,
    Link,
    ManualSource,
    MongoSource,
    SourceSpec,
    TextFormat,
    TextSource,
    _Content,
    _Delimiter,
)
from sankey_studio.models.style import DonutStyle, StyleSpec, _color_dict
from sankey_studio.models.transform import CategoryRule, EntryCategory, TransformSpec

__all__ = [
    "CATEGORY_MAX",
    "CONNECTION_NAME_RE",
    "ENTRIES_PAGE_MAX",
    "ENTRIES_PREVIEW_LIMIT",
    "FIELD_PATH_RE",
    "GRAPH_ID_PATTERN",
    "HEX_COLOR_RE",
    "INDEX_TYPECODE",
    "MAX_CATEGORIES",
    "MAX_COLOR_OVERRIDES",
    "MAX_ENTRY_CATEGORIES",
    "MAX_HIDE_NODES",
    "MAX_INLINE_CHARS",
    "MAX_MANUAL_LINKS",
    "MAX_MERGE_NODES",
    "NAME_MAX",
    "OTHER",
    "SCHEMA_VERSION",
    "TAG_MAX",
    "UNCATEGORIZED",
    "VALUE_TYPECODE",
    "_BAD_DELIMITERS",
    "_ENCODING_DENY",
    "_VALUE_FORMAT_RE",
    "AppSettings",
    "CategoryRule",
    "ColumnRef",
    "DonutStyle",
    "EntryCategory",
    "GraphCreate",
    "GraphDefinition",
    "GraphDraft",
    "GraphId",
    "GraphSummary",
    "GraphUpdate",
    "Link",
    "ManualSource",
    "MongoConnection",
    "MongoSource",
    "NameStr",
    "OptUserCategory",
    "RawLink",
    "SankeyGraph",
    "SourceSpec",
    "StyleSpec",
    "TextFormat",
    "TextSource",
    "Theme",
    "TransformSpec",
    "UserCategory",
    "_Content",
    "_Delimiter",
    "_Model",
    "_color_dict",
    "_name_check",
    "_optional_user_category",
    "_safe_name",
    "_user_category",
]
