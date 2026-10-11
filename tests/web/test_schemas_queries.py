"""Query models: defaults, exact bounds on both sides, blank filters and the domain options."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from sankey_studio.render.options import EntriesOptions, ImageOptions
from sankey_studio.web.schemas import (
    CollectionsQuery,
    CompareQuery,
    EntriesQuery,
    ExportQuery,
    IdsQuery,
    ListQuery,
    SampleQuery,
    ThemeQuery,
)
from tests.web.test_schemas_support import Case, check_case, digest, gid

LOW = "greater_than_equal"
HIGH = "less_than_equal"
LONG = "string_too_long"
SHORT = "string_too_short"
CHOICE = "literal_error"


def at_most(char: str, count: int) -> str:
    return char * count


# --------------------------------------------------------------------------- defaults


def test_the_defaults() -> None:
    assert ThemeQuery().theme == "light"
    assert ListQuery().model_dump() == {"q": None, "tag": None, "limit": 200, "offset": 0}
    assert EntriesQuery().model_dump() == {
        "offset": 0,
        "limit": 100,
        "q": None,
        "only_uncategorized": False,
        "sort": "value",
    }
    assert ExportQuery().model_dump() == {
        "chart": "sankey",
        "format": "svg",
        "theme": "light",
        "width": 1200,
        "height": None,
        "scale": 2.0,
        "transparent": False,
    }
    assert SampleQuery(database="d", collection="c").n == 5
    assert CompareQuery.model_validate({"ids": gid(1)}).theme == "light"


# --------------------------------------------------------------------------- bounds


THEME = [Case("theme", "light"), Case("theme", "dark"), Case("theme", "system", CHOICE)]
LIST = [
    Case("limit", 1),
    Case("limit", 200),
    Case("limit", 0, LOW),
    Case("limit", -1, LOW),
    Case("limit", 201, HIGH),
    Case("offset", 0),
    Case("offset", 12345),
    Case("offset", -1, LOW),
    Case("q", at_most("q", 200)),
    Case("q", at_most("q", 201), LONG),
    Case("tag", at_most("t", 40)),
    Case("tag", at_most("t", 41), LONG),
]
ENTRIES = [
    Case("offset", 0),
    Case("offset", -1, LOW),
    Case("limit", 1),
    Case("limit", 500),
    Case("limit", 0, LOW),
    Case("limit", 501, HIGH),
    Case("q", at_most("q", 200)),
    Case("q", at_most("q", 201), LONG),
    *[Case("sort", name) for name in ("value", "source", "target", "category")],
    Case("sort", "name", CHOICE),
    Case("sort", "", CHOICE),
    Case("only_uncategorized", True),
    Case("only_uncategorized", "maybe", "bool_parsing"),
]
EXPORT = [
    *[Case("chart", name) for name in ("sankey", "donut")],
    Case("chart", "pie", CHOICE),
    *[Case("format", name) for name in ("svg", "png", "html", "json", "csv")],
    Case("format", "pdf", CHOICE),
    Case("theme", "dark"),
    Case("theme", "system", CHOICE),
    Case("width", 1),
    Case("width", 100_000),
    Case("width", 0, LOW),
    Case("width", 100_001, HIGH),
    Case("height", None),
    Case("height", 1),
    Case("height", 100_000),
    Case("height", 0, LOW),
    Case("height", 100_001, HIGH),
    Case("scale", 0.001),
    Case("scale", 4.0),
    Case("scale", 100.0),
    Case("scale", 0.0, "greater_than"),
    Case("scale", -1.0, "greater_than"),
    Case("scale", 100.5, HIGH),
    Case("scale", float("nan"), "finite_number"),
    Case("scale", float("inf"), "finite_number"),
    Case("transparent", True),
]
COLLECTIONS = [
    Case("database", "d"),
    Case("database", at_most("d", 64)),
    Case("database", "", SHORT),
    Case("database", at_most("d", 65), LONG),
]
SAMPLE = [
    Case("database", at_most("d", 64)),
    Case("database", "", SHORT),
    Case("database", at_most("d", 65), LONG),
    Case("collection", at_most("c", 120)),
    Case("collection", "", SHORT),
    Case("collection", at_most("c", 121), LONG),
    Case("n", 1),
    Case("n", 20),
    Case("n", 0, LOW),
    Case("n", 21, HIGH),
]


@pytest.mark.parametrize("case", THEME, ids=repr)
def test_theme_query(case: Case) -> None:
    check_case(ThemeQuery, case)


@pytest.mark.parametrize("case", LIST, ids=repr)
def test_list_query_bounds(case: Case) -> None:
    check_case(ListQuery, case)


@pytest.mark.parametrize("case", ENTRIES, ids=repr)
def test_entries_query_bounds(case: Case) -> None:
    check_case(EntriesQuery, case)


@pytest.mark.parametrize("case", EXPORT, ids=repr)
def test_export_query_bounds(case: Case) -> None:
    check_case(ExportQuery, case)


@pytest.mark.parametrize("case", COLLECTIONS, ids=repr)
def test_collections_query_bounds(case: Case) -> None:
    check_case(CollectionsQuery, case)


@pytest.mark.parametrize("case", SAMPLE, ids=repr)
def test_sample_query_bounds(case: Case) -> None:
    check_case(SampleQuery, case, {"database": "d", "collection": "c"})


def test_the_nan_scale_is_refused_even_as_text() -> None:
    with pytest.raises(ValidationError) as caught:
        ExportQuery.model_validate({"scale": "nan"})
    assert digest(caught) == [(("scale",), "finite_number")]


# --------------------------------------------------------------------------- unknown parameters

REQUIRED: dict[type[BaseModel], dict[str, Any]] = {
    ThemeQuery: {},
    CompareQuery: {"ids": gid(1)},
    IdsQuery: {"ids": gid(1)},
    ListQuery: {},
    EntriesQuery: {},
    ExportQuery: {},
    CollectionsQuery: {"database": "d"},
    SampleQuery: {"database": "d", "collection": "c"},
}


@pytest.mark.parametrize("model", list(REQUIRED), ids=lambda model: model.__name__)
def test_an_unknown_parameter_is_refused(model: type[BaseModel]) -> None:
    model.model_validate(REQUIRED[model])
    with pytest.raises(ValidationError) as caught:
        model.model_validate({**REQUIRED[model], "bogus": "1"})
    assert digest(caught) == [(("bogus",), "extra_forbidden")]


@pytest.mark.parametrize(
    ("model", "missing"),
    [
        (CollectionsQuery, "database"),
        (SampleQuery, "database"),
        (SampleQuery, "collection"),
        (CompareQuery, "ids"),
        (IdsQuery, "ids"),
    ],
)
def test_a_required_parameter_must_be_given(model: type[BaseModel], missing: str) -> None:
    data = {key: value for key, value in REQUIRED[model].items() if key != missing}
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    assert digest(caught) == [((missing,), "missing")]


# --------------------------------------------------------------------------- text filters


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_filter_means_no_filter(blank: str) -> None:
    assert ListQuery(q=blank, tag=blank).model_dump(include={"q", "tag"}) == {
        "q": None,
        "tag": None,
    }
    assert EntriesQuery(q=blank).q is None


def test_filters_are_trimmed() -> None:
    assert ListQuery(q="  food ", tag=" tag\n").model_dump(include={"q", "tag"}) == {
        "q": "food",
        "tag": "tag",
    }
    assert EntriesQuery(q="  Rent ").q == "Rent"
    assert CollectionsQuery(database=" flows ").database == "flows"


def test_the_length_limit_counts_the_trimmed_text() -> None:
    assert ListQuery(q="  " + at_most("q", 200) + "  ").q == at_most("q", 200)


# --------------------------------------------------------------------------- domain options


def test_entries_query_becomes_entries_options() -> None:
    query = EntriesQuery(offset=7, limit=33, q="foo", only_uncategorized=True, sort="category")
    assert query.options() == EntriesOptions(
        q="foo", only_uncategorized=True, sort="category", offset=7, limit=33
    )
    assert EntriesQuery().options() == EntriesOptions()


def test_export_query_becomes_image_options() -> None:
    query = ExportQuery(width=640, height=480, scale=1.5, transparent=True, format="png")
    assert query.image_options() == ImageOptions(width=640, height=480, scale=1.5, transparent=True)
    assert ExportQuery().image_options() == ImageOptions()
