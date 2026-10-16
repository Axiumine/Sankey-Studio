# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Source specs: manual links, text documents and MongoDB collections."""

from __future__ import annotations

import codecs
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from sankey_studio.errors import UnsafeSourceError
from sankey_studio.models.base import (
    CONNECTION_NAME_RE,
    FIELD_PATH_RE,
    MAX_INLINE_CHARS,
    MAX_MANUAL_LINKS,
    NAME_MAX,
    _Model,
)
from sankey_studio.models.fields import NameStr, OptUserCategory, _safe_name
from sankey_studio.models.writeback import WriteBackPref
from sankey_studio.mongo_safety import (
    check_filter,
    check_pipeline,
    validate_collection_name,
    validate_db_name,
)


class Link(_Model):
    """One manually entered flow. ``category`` is optional (``None``/empty = uncategorised)."""

    source: NameStr
    target: NameStr
    value: float = Field(gt=0, allow_inf_nan=False)
    category: OptUserCategory = None


class ManualSource(_Model):
    """Links typed into the web editor and stored inside the graph definition.

    For a manual source the entries table edits ``Link.category`` in place and never writes
    ``TransformSpec.entry_categories`` (one authority per source type).
    """

    type: Literal["manual"] = "manual"
    links: list[Link] = Field(default_factory=list, max_length=MAX_MANUAL_LINKS)


TextFormat = Literal["auto", "csv", "tsv", "sankeymatic", "json"]

#: ``delimiter`` / ``content`` must survive verbatim: a tab or space delimiter and a leading
#: tab in the first TSV row are significant, so these two override the model-wide strip.
_Delimiter = Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=1)]
_Content = Annotated[str, StringConstraints(strip_whitespace=False, max_length=MAX_INLINE_CHARS)]
#: A column reference: header name or 0-based index.
ColumnRef = (
    Annotated[str, Field(min_length=1, max_length=NAME_MAX)]
    | Annotated[int, Field(ge=0, le=10_000)]
)

#: Python codecs that exist, are "text" encodings, and yet make no sense for a data file.
_ENCODING_DENY = frozenset(
    {"undefined", "idna", "punycode", "unicode-escape", "raw-unicode-escape", "charmap"}
)
_BAD_DELIMITERS = frozenset('"\n\r\0')


class TextSource(_Model):
    """A text document: pasted/uploaded (``inline``) or a file under the sources dir (``file``).

    Formats: ``csv``/``tsv`` (columns source,target,value), ``sankeymatic``
    (``Source [value] Target`` lines, ``//`` comments), ``json`` (array of
    ``{source,target,value}`` objects, or NDJSON). ``auto`` sniffs the content.
    ``content`` and ``delimiter`` are NOT whitespace-stripped.
    """

    type: Literal["text"] = "text"
    origin: Literal["inline", "file"] = "inline"
    content: _Content | None = None
    path: str | None = Field(default=None, max_length=255)
    format: TextFormat = "auto"
    #: Single character; ``None`` -> sniff (csv/tsv). A tab or a space is allowed.
    delimiter: _Delimiter | None = None
    has_header: bool = True
    #: Header name or 0-based column index. ``None`` -> "source"/"target"/"value" header
    #: names when a header exists, otherwise columns 0/1/2.
    source_column: ColumnRef | None = None
    target_column: ColumnRef | None = None
    value_column: ColumnRef | None = None
    #: Optional category column. A column NAME that is not in the header is a ``SourceError``.
    #: ``None`` -> a "category" header is used when ``detect_category`` is true (without a
    #: header: the fourth column), else no category.
    #: In ``sankeymatic`` text a category is appended as ``| category``.
    category_column: ColumnRef | None = None
    #: Off switch for the category auto-detection, i.e. the "category" header or, without a
    #: header, the fourth column (an unrelated column named "category" must not switch
    #: categories on). An explicit ``category_column`` always wins.
    detect_category: bool = True
    #: Any Python TEXT codec (``utf-8``, ``utf-8-sig``, ``utf-16``, ``cp1252``, ...); stored in
    #: canonical form. Byte-to-byte codecs (zlib, base64, ...) are refused: they would inflate.
    encoding: str = Field(default="utf-8", max_length=32)
    #: Whether edits are written back to the file. ``None`` = ask. Ignored for ``inline``.
    write_back: WriteBackPref | None = None

    @field_validator("path")
    @classmethod
    def _safe_relative_path(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v or v.startswith(("/", "~")) or "\\" in v or "\0" in v:
            raise ValueError("path must be a relative POSIX path inside the sources directory")
        if any(part in {"", ".", ".."} for part in v.split("/")):
            raise ValueError("path must not contain '.', '..' or empty segments")
        return v

    @field_validator("delimiter")
    @classmethod
    def _delimiter(cls, v: str | None) -> str | None:
        if v is not None and v in _BAD_DELIMITERS:
            raise ValueError("delimiter must not be a quote, a line break or NUL")
        return v

    @field_validator("encoding")
    @classmethod
    def _text_encoding(cls, v: str) -> str:
        try:
            info = codecs.lookup(v)
        except LookupError, ValueError:
            raise ValueError("unknown encoding") from None
        # noinspection PyProtectedMember
        if not info._is_text_encoding or info.name in _ENCODING_DENY:  # noqa: SLF001 - no public text-codec flag
            raise ValueError("encoding must be a text encoding such as 'utf-8' or 'cp1252'")
        return info.name

    @model_validator(mode="after")
    def _origin_fields(self) -> TextSource:
        if self.origin == "inline" and self.content is None:
            raise ValueError("content is required when origin is 'inline'")
        if self.origin == "file" and not self.path:
            raise ValueError("path is required when origin is 'file'")
        return self


class MongoSource(_Model):
    """Documents from a MongoDB collection (read-only unless the owner opts into write-back).

    ``find`` mode: ``filter`` selects documents, each document is one flow.
    ``aggregate`` mode: ``pipeline`` output documents are the flows.
    ``value_field = None`` counts every document as value 1 (event logs).
    The category field is optional: a document without it (or with an unusable value) is kept
    uncategorised.
    """

    type: Literal["mongo"] = "mongo"
    #: Name of a ``MongoConnection`` in ``AppSettings.mongo_connections``.
    connection: str = Field(pattern=CONNECTION_NAME_RE.pattern)
    #: ``None`` -> the connection's ``default_database``. ``admin``/``local``/``config`` refused.
    database: str | None = Field(default=None, max_length=64)
    collection: str = Field(min_length=1, max_length=120)
    mode: Literal["find", "aggregate"] = "find"
    filter: dict[str, Any] = Field(default_factory=dict)
    pipeline: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    source_field: str = "source"
    target_field: str = "target"
    value_field: str | None = "value"
    #: Optional dotted path of the entry's category.
    category_field: str | None = None
    limit: int = Field(default=10_000, ge=1, le=1_000_000)
    max_time_ms: int | None = Field(default=None, ge=100, le=300_000)
    #: Whether edits are written back to the collection. ``None`` = ask.
    write_back: WriteBackPref | None = None

    @field_validator("database")
    @classmethod
    def _db_name(cls, v: str | None) -> str | None:
        return v if v is None else _safe_name(validate_db_name, v)

    @field_validator("collection")
    @classmethod
    def _collection_name(cls, v: str) -> str:
        return _safe_name(validate_collection_name, v)

    @field_validator("source_field", "target_field", "value_field", "category_field")
    @classmethod
    def _field_path(cls, v: str | None) -> str | None:
        if v is not None and not FIELD_PATH_RE.match(v):
            raise ValueError("field must be a dotted path such as 'from' or 'meta.flow'")
        return v

    @model_validator(mode="after")
    def _read_only(self) -> MongoSource:
        try:
            check_filter(self.filter)
            check_pipeline(self.pipeline)
        except UnsafeSourceError as exc:
            # Re-raise as ValueError so pydantic reports a normal 422 validation error.
            raise ValueError(exc.message) from exc
        if self.mode == "aggregate" and not self.pipeline:
            raise ValueError("pipeline must not be empty in 'aggregate' mode")
        return self


SourceSpec = Annotated[ManualSource | TextSource | MongoSource, Field(discriminator="type")]
