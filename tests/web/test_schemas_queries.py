"""Query models: defaults, exact bounds on both sides, blank filters and the domain options."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from sankey_studio.render.options import EntriesOptions, ImageOptions
from sankey_studio.web.schemas import (
    CollectionsQuery,
    CompareQuery,
    CreateQuery,
    EntriesQuery,
    ExportQuery,
    IdsQuery,
    ListQuery,
    RenderQuery,
    SampleQuery,
    ScopeQuery,
    ThemeQuery,
)
from tests.web.test_schemas_support import Case, check_case, digest, gid

SWITCHES_UNSET = {"node_values": None, "donut_percent": None, "donut_value": None}
LOW = "greater_than_equal"
HIGH = "less_than_equal"
LONG = "string_too_long"
SHORT = "string_too_short"
CHOICE = "literal_error"
PATTERN = "string_pattern_mismatch"


def at_most(char: str, count: int) -> str:
    return char * count


# --------------------------------------------------------------------------- defaults


def test_the_defaults() -> None:
    assert CreateQuery().model_dump() == {"folder": None}
    assert ScopeQuery().model_dump() == {"folder": ""}
    assert ThemeQuery().theme == "light"
    assert ListQuery().model_dump() == {
        "q": None,
        "tag": None,
        "folder": None,
        "limit": 200,
        "offset": 0,
    }
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
        **SWITCHES_UNSET,
    }
    assert RenderQuery().model_dump() == {"theme": "light", **SWITCHES_UNSET}
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
    Case("folder", "root"),
    Case("folder", gid(1)),
    Case("folder", "f" * 32),
    Case("folder", "f" * 31, PATTERN),
    Case("folder", "f" * 33, PATTERN),
    Case("folder", "F" * 32, PATTERN),
    Case("folder", "g" * 32, PATTERN),
    Case("folder", "ROOT", PATTERN),
    Case("folder", "roots", PATTERN),
    Case("folder", "", PATTERN),
]
CREATE = [
    Case("folder", None),
    Case("folder", gid(1)),
    Case("folder", "f" * 31, PATTERN),
    Case("folder", "root", PATTERN),
    Case("folder", "F" * 32, PATTERN),
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
SWITCHES = [
    *[Case(name, value) for name in SWITCHES_UNSET for value in (True, False, None)],
    *[Case(name, "maybe", "bool_parsing") for name in SWITCHES_UNSET],
    *[Case(name, 2, "bool_parsing") for name in SWITCHES_UNSET],
]
RENDER = [*THEME, *SWITCHES]
EXPORT = [
    *SWITCHES,
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


@pytest.mark.parametrize("case", RENDER, ids=repr)
def test_render_query(case: Case) -> None:
    check_case(RenderQuery, case)


@pytest.mark.parametrize("case", LIST, ids=repr)
def test_list_query_bounds(case: Case) -> None:
    check_case(ListQuery, case)


@pytest.mark.parametrize("case", CREATE, ids=repr)
def test_create_query_bounds(case: Case) -> None:
    check_case(CreateQuery, case)


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
    RenderQuery: {},
    CompareQuery: {"ids": gid(1)},
    IdsQuery: {"ids": gid(1)},
    ListQuery: {},
    CreateQuery: {},
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


# --------------------------------------------------------------------------- folder scope


@pytest.mark.parametrize("scope", ["root", "f" * 32])
@pytest.mark.parametrize("search", [{"q": "x"}, {"tag": "t"}, {"q": "x", "tag": "t"}])
def test_a_folder_scope_cannot_be_combined_with_a_search(
    scope: str, search: dict[str, str]
) -> None:
    with pytest.raises(ValidationError) as caught:
        ListQuery.model_validate({"folder": scope, **search})
    assert digest(caught) == [((), "value_error")]
    assert "folder cannot be combined with q or tag" in str(caught.value)


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_search_does_not_count_as_a_search(blank: str) -> None:
    query = ListQuery.model_validate({"folder": "root", "q": blank, "tag": blank})
    assert (query.folder, query.q, query.tag) == ("root", None, None)


def test_a_search_without_a_folder_is_unchanged() -> None:
    query = ListQuery.model_validate({"q": "food", "tag": "t", "limit": 5, "offset": 2})
    assert (query.q, query.tag, query.folder, query.limit, query.offset) == (
        "food",
        "t",
        None,
        5,
        2,
    )


def test_the_folder_of_a_listing_is_trimmed_like_every_other_query_text() -> None:
    assert ListQuery.model_validate({"folder": " root "}).folder == "root"


@pytest.mark.parametrize("value", ["", "nonsense", "../x", gid(1), "x" * 10_000])
def test_the_page_scope_accepts_any_text_and_leaves_the_judging_to_the_route(value: str) -> None:
    assert ScopeQuery.model_validate({"folder": value}).folder == value


def test_the_page_scope_trims_and_ignores_other_parameters() -> None:
    query = ScopeQuery.model_validate({"folder": "  abc  ", "bogus": "1"})
    assert query.model_dump() == {"folder": "abc"}
