"""csv column selection (name or index) and the optional category column."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceError
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from sankey_studio.sources.base import SourceContext


class Pick(NamedTuple):
    content: str
    fields: dict[str, Any]
    row: tuple[str, str, float, str | None]


PICKS = [
    # header names are the default, in any order, case-insensitive and trimmed
    Pick("value,source,target\n5,a,b", {}, ("a", "b", 5.0, None)),
    Pick("Source, TARGET ,Value\na,b,5", {}, ("a", "b", 5.0, None)),
    Pick("source,target,value,source\na,b,5,zzz", {}, ("a", "b", 5.0, None)),  # first wins
    # explicit names
    Pick(
        "from,to,amount\na,b,5",
        {"source_column": "from", "target_column": "to", "value_column": "amount"},
        ("a", "b", 5.0, None),
    ),
    Pick(
        "FROM,To,Amount\na,b,5",
        {"source_column": "from", "target_column": " TO ", "value_column": "amount"},
        ("a", "b", 5.0, None),
    ),
    # explicit indexes, with and without a header
    Pick(
        "x,y,z\n5,b,a",
        {"source_column": 2, "target_column": 1, "value_column": 0},
        ("a", "b", 5.0, None),
    ),
    Pick(
        "5,b,a",
        {"has_header": False, "source_column": 2, "target_column": 1, "value_column": 0},
        ("a", "b", 5.0, None),
    ),
    # mixed: one by name, one by index, one default
    Pick("source,n,value\na,b,5", {"target_column": 1}, ("a", "b", 5.0, None)),
    Pick("v,source,target\n5,a,b", {"value_column": "v"}, ("a", "b", 5.0, None)),
    # an index is a position, even when a header has a column with that text
    Pick(
        "1,0,2\na,b,5",
        {"source_column": 0, "target_column": 1, "value_column": 2},
        ("a", "b", 5.0, None),
    ),
]


@pytest.mark.parametrize("case", PICKS, ids=[str(i) for i in range(len(PICKS))])
def test_column_selection(source_ctx: SourceContext, case: Pick) -> None:
    out = inline(source_ctx, case.content, format="csv", **case.fields)
    assert out.rows == [case.row]
    assert out.warnings == []


class Missing(NamedTuple):
    content: str
    fields: dict[str, Any]
    message: str


MISSING = [
    Missing("a,b,c\n1,2,3", {}, "inline: column 'source' is not in the header"),
    Missing("source,b,c\n1,2,3", {}, "inline: column 'target' is not in the header"),
    Missing("source,target,c\n1,2,3", {}, "inline: column 'value' is not in the header"),
    Missing(
        "source,target,value\n1,2,3",
        {"value_column": "amount"},
        "inline: column 'amount' is not in the header",
    ),
    Missing(
        "source,target,value\n1,2,3",
        {"source_column": "from"},
        "inline: column 'from' is not in the header",
    ),
    Missing(
        "source,target,value\n1,2,3",
        {"target_column": "to"},
        "inline: column 'to' is not in the header",
    ),
    Missing(
        "1,2,3",
        {"has_header": False, "source_column": "from"},
        "inline: column 'from' needs a header row",
    ),
    Missing(
        "1,2,3",
        {"has_header": False, "category_column": "cat"},
        "inline: column 'cat' needs a header row",
    ),
    # a NAMED category column that does not exist is the one hard category error
    Missing(
        "source,target,value\na,b,1",
        {"category_column": "kind"},
        "inline: column 'kind' is not in the header",
    ),
    Missing(
        "source,target,value,category\na,b,1,x",
        {"category_column": "kind", "detect_category": False},
        "inline: column 'kind' is not in the header",
    ),
]


@pytest.mark.parametrize("case", MISSING, ids=[str(i) for i in range(len(MISSING))])
def test_a_missing_named_column_is_a_source_error_naming_it(
    source_ctx: SourceContext, case: Missing
) -> None:
    with pytest.raises(SourceError) as info:
        inline(source_ctx, case.content, format="csv", **case.fields)
    assert str(info.value) == case.message


def test_an_index_beyond_the_row_skips_the_row(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "a,b,1\nc,d,2,3\n", format="csv", has_header=False, value_column=3)
    assert out.rows == [("c", "d", 3.0, None)]
    assert out.warnings == ["inline:1: value is missing"]


class Cat(NamedTuple):
    content: str
    fields: dict[str, Any]
    categories: list[str | None]


CATEGORIES = [
    # a "category" header switches categories on by itself
    Cat("source,target,value,category\na,b,1,Food\nc,d,2,Rent", {}, ["Food", "Rent"]),
    Cat("source,target,value,Category\na,b,1,Food", {}, ["Food"]),
    Cat("source,target,value, CATEGORY \na,b,1,Food", {}, ["Food"]),
    Cat("category,source,target,value\nFood,a,b,1", {}, ["Food"]),
    # normalised: trimmed and inner whitespace collapsed
    Cat("source,target,value,category\na,b,1,  Fast   Food ", {}, ["Fast Food"]),
    # no category anywhere: every row is None, nothing is skipped
    Cat("source,target,value\na,b,1\nc,d,2", {}, [None, None]),
    # an empty cell and a short row are uncategorised, rows kept
    Cat("source,target,value,category\na,b,1,\nc,d,2\ne,f,3,Food", {}, [None, None, "Food"]),
    # the unrelated 'category' column is ignored when detection is off ...
    Cat("source,target,value,category\na,b,1,Food", {"detect_category": False}, [None]),
    # ... but an explicit column always wins
    Cat(
        "source,target,value,category\na,b,1,Food",
        {"detect_category": False, "category_column": "category"},
        ["Food"],
    ),
    Cat("source,target,value,kind,category\na,b,1,K,C", {"category_column": "kind"}, ["K"]),
    Cat("source,target,value,kind,category\na,b,1,K,C", {"category_column": 4}, ["C"]),
    Cat("a,b,1,K\nc,d,2,L", {"has_header": False, "category_column": 3}, ["K", "L"]),
    # without a header there is no auto-detection
    Cat("a,b,1,K", {"has_header": False}, [None]),
    # an index beyond every row is just uncategorised
    Cat("source,target,value\na,b,1", {"category_column": 9}, [None]),
]


@pytest.mark.parametrize("case", CATEGORIES, ids=[str(i) for i in range(len(CATEGORIES))])
def test_categories(source_ctx: SourceContext, case: Cat) -> None:
    out = inline(source_ctx, case.content, format="csv", **case.fields)
    assert [row[3] for row in out.rows] == case.categories
    assert out.skipped == 0
    assert out.warnings == []


def test_a_file_without_any_category_yields_none_everywhere(source_ctx: SourceContext) -> None:
    text = "source,target,value\n" + "".join(f"n{i},m{i},{i + 1}\n" for i in range(50))
    out = inline(source_ctx, text)
    assert len(out.rows) == 50
    assert all(row[3] is None for row in out.rows)
    assert out.skipped == 0
    assert out.warnings == []


def test_bad_category_values_keep_the_row_and_add_one_aggregated_warning(
    source_ctx: SourceContext,
) -> None:
    long_name = "x" * 101
    text = (
        "source,target,value,category\n"
        f"a,b,1,{long_name}\n"
        "c,d,2,Other\n"
        "e,f,3,uncategorized\n"
        "g,h,4,Food\n"
    )
    out = inline(source_ctx, text)
    assert [row[3] for row in out.rows] == [None, None, None, "Food"]
    assert out.skipped == 0
    assert out.warnings == [
        (
            "Categories ignored (entries kept uncategorised): 1 longer than 100 characters; "
            "2 using the reserved names Uncategorized/Other"
        )
    ]


def test_a_category_with_a_control_character_is_ignored(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, 'source,target,value,category\na,b,1,"x\x01y"\n')
    assert [row[3] for row in out.rows] == [None]
    assert out.warnings == [
        "Categories ignored (entries kept uncategorised): 1 containing control characters"
    ]


def test_the_category_of_a_skipped_row_is_not_counted(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "source,target,value,category\na,b,oops,Other\nc,d,1,Food\n")
    assert out.rows == [("c", "d", 1.0, "Food")]
    assert out.warnings == ["inline:2: value must be a positive number"]
