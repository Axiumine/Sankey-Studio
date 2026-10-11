"""E2E A.5 (library): 25 saved graphs listed, searched, filtered by tag and paged in a stable order.

The module's server is filled once and these tests only read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_a_library import GRAPHS, Library, listed_ids, newest_first, seed_library
from tests.e2e.support.stamps import instant

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

    from tests.e2e.support.server import LiveServer

COUNT = 25


@dataclass(frozen=True, slots=True)
class Seeded:
    """A client of the module's server and the graphs it was filled with."""

    api: httpx.Client
    library: Library

    def names(self, **params: Any) -> list[str]:
        items = json_of(self.api.get(GRAPHS, params=params))["items"]
        return [item["name"] for item in items]

    def total(self, **params: Any) -> int:
        return int(json_of(self.api.get(GRAPHS, params=params))["total"])


@pytest.fixture(scope="module")
def seeded(module_server: LiveServer) -> Iterator[Seeded]:
    with make_client(module_server) as api:
        yield Seeded(api, seed_library(api, COUNT))


def test_the_list_is_newest_first_with_ties_in_id_order(seeded: Seeded) -> None:
    page = json_of(seeded.api.get(GRAPHS))
    assert (page["total"], page["limit"], page["offset"]) == (COUNT, 200, 0)
    expected = newest_first(seeded.library.graphs)
    assert [item["id"] for item in page["items"]] == expected
    stamps = [instant(item["updated_at"]) for item in page["items"]]
    assert stamps == sorted(stamps, reverse=True)
    assert page["items"][0]["name"] == "Budget 24"  # the last one created is the newest


def test_a_summary_has_what_the_library_card_shows(seeded: Seeded) -> None:
    [item] = json_of(seeded.api.get(GRAPHS, params={"q": "Budget 05"}))["items"]
    assert item == {
        "id": seeded.library.by_name("Budget 05")["id"],
        "name": "Budget 05",
        "description": "Quarterly report",
        "tags": ["odd", "all"],  # in the order they were given
        "source_type": "text",
        "revision": 1,
        "updated_at": item["updated_at"],
    }
    assert item["updated_at"].endswith("Z")


@pytest.mark.parametrize(("limit", "pages"), [(10, [10, 10, 5]), (25, [25]), (7, [7, 7, 7, 4])])
def test_pages_follow_each_other_without_gaps_or_repeats(
    seeded: Seeded, limit: int, pages: list[int]
) -> None:
    seen: list[str] = []
    for index, size in enumerate(pages):
        page = json_of(seeded.api.get(GRAPHS, params={"limit": limit, "offset": index * limit}))
        assert (page["total"], page["limit"], page["offset"]) == (COUNT, limit, index * limit)
        assert len(page["items"]) == size
        seen += [item["id"] for item in page["items"]]
    assert seen == newest_first(seeded.library.graphs)


def test_a_page_past_the_end_is_empty_but_still_counts_everything(seeded: Seeded) -> None:
    page = json_of(seeded.api.get(GRAPHS, params={"offset": 99}))
    assert (page["items"], page["total"]) == ([], COUNT)
    last = json_of(seeded.api.get(GRAPHS, params={"limit": 1, "offset": COUNT - 1}))
    assert [item["name"] for item in last["items"]] == ["Budget 00"]  # the oldest


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"q": "x" * 201}, {"tag": "x" * 41}]
)
def test_out_of_range_list_parameters_are_a_422(seeded: Seeded, params: dict[str, Any]) -> None:
    error = json_of(seeded.api.get(GRAPHS, params=params), 422)["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0].startswith("query.")


def test_the_edges_of_the_list_parameters_are_accepted(seeded: Seeded) -> None:
    assert len(seeded.names(limit=1)) == 1
    assert len(seeded.names(limit=200)) == COUNT
    assert seeded.total(q="x" * 200) == 0
    assert seeded.total(tag="x" * 40) == 0


def test_search_matches_names_descriptions_and_tags_ignoring_case(seeded: Seeded) -> None:
    assert seeded.names(q="budget 1") == [f"Budget {n}" for n in range(19, 9, -1)]
    assert seeded.total(q="BUDGET") == COUNT
    quarterly = seeded.names(q="quarterly")  # a description
    assert quarterly == [f"Budget {n:02d}" for n in (20, 15, 10, 5, 0)]
    assert seeded.total(q="special") == 1  # a tag
    assert seeded.names(q="special") == ["Budget 03"]
    assert seeded.total(q="all") == COUNT  # the shared tag (and "allocation" has it as a part)


def test_search_text_is_plain_text_not_a_pattern(seeded: Seeded) -> None:
    for text in (".*", "Budget.", "(", "[a-z]", "%", "_", "\\", "' OR 1=1", "$ne"):
        assert seeded.total(q=text) == 0, text
    assert seeded.total(q="   ") == COUNT  # blank means no search
    assert seeded.total(q="") == COUNT


def test_the_tag_filter_is_an_exact_match(seeded: Seeded) -> None:
    assert seeded.total(tag="even") == 13
    assert seeded.total(tag="odd") == 12
    assert seeded.total(tag="all") == COUNT
    assert seeded.names(tag="special") == ["Budget 03"]
    assert seeded.total(tag="spec") == 0  # a part of a tag is not the tag
    assert seeded.total(tag="Special") == 0  # case matters for the exact filter
    assert seeded.total(tag="alloc") == 0
    assert seeded.names(tag="allocation") == ["Budget 07"]


def test_search_tag_and_paging_combine(seeded: Seeded) -> None:
    assert seeded.total(tag="even", q="quarterly") == 3  # 00, 10, 20
    assert seeded.names(tag="even", q="quarterly") == ["Budget 20", "Budget 10", "Budget 00"]
    page = json_of(seeded.api.get(GRAPHS, params={"tag": "even", "limit": 5, "offset": 10}))
    assert (page["total"], len(page["items"])) == (13, 3)
    assert [item["name"] for item in page["items"]] == ["Budget 04", "Budget 02", "Budget 00"]
    assert listed_ids(seeded.api, tag="nothing") == []


def test_the_tag_list_is_sorted_and_complete(seeded: Seeded) -> None:
    assert json_of(seeded.api.get("/api/v1/tags")) == [
        "all",
        "allocation",
        "even",
        "odd",
        "special",
    ]
