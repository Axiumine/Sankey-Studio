"""Query-string models: one per route, so a route never takes more than one query parameter.

Every model forbids unknown parameters (a typo is a 422, not a silently ignored filter) and is
used as ``query: Annotated[ExportQuery, Query()]``. List-valued ``ids`` are comma separated
(``?ids=a,b``; a repeated parameter works too), parsed and bounded here, each id checked against
the graph-id pattern: a malformed id is a 422 on the query, an unknown valid id is a 404 later.

The models only reject absurd values. Real clamps live in the domain (``resolve_image`` for image
sizes, ``clamp_sample_size``, ``EntriesOptions.window``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from sankey_studio.models import ENTRIES_PAGE_MAX, NAME_MAX, TAG_MAX, GraphId, StyleSpec, Theme
from sankey_studio.render.options import EntriesOptions, EntrySort, ImageOptions
from sankey_studio.sources.mongo_inspect import SAMPLE_DEFAULT, SAMPLE_MAX, SAMPLE_MIN

__all__ = [
    "COMPARE_IDS_MAX",
    "EXPORT_IDS_MAX",
    "IMAGE_SIDE_MAX",
    "LIST_LIMIT_MAX",
    "CollectionsQuery",
    "CompareQuery",
    "EntriesQuery",
    "ExportChart",
    "ExportFormat",
    "ExportQuery",
    "IdsQuery",
    "ListQuery",
    "RenderQuery",
    "SampleQuery",
    "ThemeQuery",
    "split_ids",
]

#: Graphs in the compare view.
COMPARE_IDS_MAX = 12
#: Graphs in one bundle export.
EXPORT_IDS_MAX = 200
#: Rejects absurd image sides; ``resolve_image`` clamps to 200..4000 and applies the pixel cap.
IMAGE_SIDE_MAX = 100_000
SCALE_MAX = 100.0
LIST_LIMIT_MAX = 200

ExportChart = Literal["sankey", "donut"]
ExportFormat = Literal["svg", "png", "html", "json", "csv"]


class _Query(BaseModel):
    """Base of the query models: no unknown parameters, trimmed text, no echoed input."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


def split_ids(value: object) -> object:
    """``"a,b"`` or ``["a,b", "c"]`` -> ``["a", "b", "c"]``: trimmed, duplicates dropped, in order.

    Anything that is not a string or a list of strings is returned as it is, so pydantic reports
    the type error. An empty piece stays in the list and fails the id pattern (``ids=a,``).
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return value
    return list(dict.fromkeys(part.strip() for item in value for part in item.split(",")))


CompareIds = Annotated[
    list[GraphId], BeforeValidator(split_ids), Field(min_length=1, max_length=COMPARE_IDS_MAX)
]
ExportIds = Annotated[
    list[GraphId], BeforeValidator(split_ids), Field(min_length=1, max_length=EXPORT_IDS_MAX)
]


class _DisplayQuery(_Query):
    """View-time switches of the labels; ``None`` keeps what the saved style says.

    They never change the saved graph: ``styled`` returns the style the figures are drawn with.
    """

    node_values: bool | None = None
    donut_percent: bool | None = None
    donut_value: bool | None = None

    def styled(self, style: StyleSpec) -> StyleSpec:
        """``style`` with the chosen switches applied (``style`` itself when none is chosen)."""
        node = _chosen({"show_values_in_labels": self.node_values})
        donut = _chosen({"show_percent": self.donut_percent, "show_value": self.donut_value})
        if not node and not donut:
            return style
        dumped = style.model_dump()
        return StyleSpec.model_validate({**dumped, **node, "donut": {**dumped["donut"], **donut}})


def _chosen(switches: dict[str, bool | None]) -> dict[str, bool]:
    return {name: value for name, value in switches.items() if value is not None}


class RenderQuery(_DisplayQuery):
    """``?theme=&node_values=&donut_percent=&donut_value=`` of ``GET /graphs/{id}/render``."""

    theme: Theme = "light"


class ThemeQuery(_Query):
    """``?theme=`` of ``POST /preview`` and ``GET /graphs/{id}/render``."""

    theme: Theme = "light"


class CompareQuery(_Query):
    """``?ids=&theme=`` of ``GET /compare/render``: 1..12 distinct graph ids."""

    ids: CompareIds
    theme: Theme = "light"


class IdsQuery(_Query):
    """``?ids=`` of ``GET /graphs/export``: 1..200 distinct graph ids."""

    ids: ExportIds


class ListQuery(_Query):
    """``?q=&tag=&limit=&offset=`` of ``GET /graphs``. A blank ``q`` or ``tag`` means no filter."""

    q: Annotated[str | None, Field(max_length=NAME_MAX)] = None
    tag: Annotated[str | None, Field(max_length=TAG_MAX)] = None
    limit: int = Field(default=LIST_LIMIT_MAX, ge=1, le=LIST_LIMIT_MAX)
    offset: int = Field(default=0, ge=0)

    @field_validator("q", "tag")
    @classmethod
    def _blank(cls, value: str | None) -> str | None:
        return value or None


class EntriesQuery(_Query):
    """``?offset=&limit=&q=&only_uncategorized=&sort=`` of ``POST /entries``."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=ENTRIES_PAGE_MAX)
    q: Annotated[str | None, Field(max_length=NAME_MAX)] = None
    only_uncategorized: bool = False
    sort: EntrySort = "value"

    @field_validator("q")
    @classmethod
    def _blank(cls, value: str | None) -> str | None:
        return value or None

    def options(self) -> EntriesOptions:
        return EntriesOptions(
            q=self.q,
            only_uncategorized=self.only_uncategorized,
            sort=self.sort,
            offset=self.offset,
            limit=self.limit,
        )


class ExportQuery(_DisplayQuery):
    """The export parameters of ``GET /graphs/{id}/export`` and ``POST /export``.

    ``width``, ``height`` and ``scale`` only have to be sane here: ``resolve_image`` clamps them
    and answers 422 ``export_too_large`` above the pixel cap. ``height=None`` takes the figure's.
    """

    chart: ExportChart = "sankey"
    format: ExportFormat = "svg"
    theme: Theme = "light"
    width: int = Field(default=1200, ge=1, le=IMAGE_SIDE_MAX)
    height: int | None = Field(default=None, ge=1, le=IMAGE_SIDE_MAX)
    scale: float = Field(default=2.0, gt=0, le=SCALE_MAX, allow_inf_nan=False)
    transparent: bool = False

    def image_options(self) -> ImageOptions:
        return ImageOptions(
            width=self.width, height=self.height, scale=self.scale, transparent=self.transparent
        )


class CollectionsQuery(_Query):
    """``?database=`` of ``GET /mongo/{name}/collections``; ``mongo_inspect`` checks the name."""

    database: str = Field(min_length=1, max_length=64)


class SampleQuery(_Query):
    """``?database=&collection=&n=`` of ``GET /mongo/{name}/sample`` (``n`` is 1..20)."""

    database: str = Field(min_length=1, max_length=64)
    collection: str = Field(min_length=1, max_length=120)
    n: int = Field(default=SAMPLE_DEFAULT, ge=SAMPLE_MIN, le=SAMPLE_MAX)
