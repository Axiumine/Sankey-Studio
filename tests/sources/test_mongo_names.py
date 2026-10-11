"""Connection names that reach ``require_connection`` from raw query parameters.

``CONNECTION_NAME_RE`` ends in ``$``, which also matches before a trailing line feed, so a
name such as ``test\\n`` must be told apart from ``test`` by ``fullmatch``: it is never echoed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import SourceNotFoundError
from sankey_studio.sources.mongo_inspect import (
    CollectionRef,
    list_collections,
    list_databases,
    sample_documents,
)
from sankey_studio.sources.mongo_source import require_connection
from tests.sources.test_mongo_fakes import FakeMongo

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.sources.base import SourceContext
    from tests.sources.conftest import FakeCtxFactory

UNKNOWN_ODD = "Unknown MongoDB connection '?'"


class Name(NamedTuple):
    raw: str
    shown: str


NAMES = {
    "plain": Name("other", "other"),
    "all allowed punctuation": Name("A-b_c.9", "A-b_c.9"),
    "64 characters": Name("a" * 64, "a" * 64),
    "65 characters": Name("a" * 65, "?"),
    "trailing line feed": Name("other\n", "?"),
    "only a line feed": Name("\n", "?"),
    "line feed in the middle": Name("ot\nher", "?"),
    "trailing carriage return": Name("other\r", "?"),
    "trailing space": Name("other ", "?"),
    "empty": Name("", "?"),
}


@pytest.mark.parametrize("case", NAMES.values(), ids=NAMES)
def test_an_unknown_name_is_echoed_only_when_it_looks_like_a_connection_name(
    case: Name, source_ctx: SourceContext
) -> None:
    with pytest.raises(SourceNotFoundError) as info:
        require_connection(source_ctx, case.raw)
    assert info.value.message == f"Unknown MongoDB connection '{case.shown}'"


def test_the_configured_name_is_found_and_a_trailing_line_feed_is_not_the_same_name(
    source_ctx: SourceContext,
) -> None:
    assert require_connection(source_ctx, "test").name == "test"
    with pytest.raises(SourceNotFoundError):
        require_connection(source_ctx, "test\n")


def test_every_inspect_call_hides_a_line_feed_terminated_name(
    mongo_fake_ctx: FakeCtxFactory,
) -> None:
    fake = FakeMongo(names=["a"])
    ctx = mongo_fake_ctx(fake)
    calls: list[Callable[[], object]] = [
        lambda: list_databases(ctx, "test\n"),
        lambda: list_collections(ctx, "test\n", "flows"),
        lambda: sample_documents(ctx, CollectionRef("test\n", "flows", "events")),
    ]
    for call in calls:
        with pytest.raises(SourceNotFoundError) as info:
            call()
        assert info.value.message == UNKNOWN_ODD
    assert fake.calls == []
    assert ctx.mongo._slots == {}
