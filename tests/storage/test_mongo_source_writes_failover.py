"""Source write-back on a cluster: a refused update, and a failover in the middle of a write.

A refused ``update_many`` (a collection validator, a shard key that may not change) is the answer
``write_rejected`` like a refused insert; a primary change, a cut connection or a write concern
timeout says to try again (and, for the last one, that the write may have been applied).
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import pytest
from pymongo.errors import (
    AutoReconnect,
    NotPrimaryError,
    PyMongoError,
    WriteError,
    WTimeoutError,
)

from sankey_studio.errors import SourceWriteError
from sankey_studio.storage.mongo_source_writes import insert_document, update_by_ids
from tests.storage.mongo_fakes import broken_clients
from tests.storage.source_write_support import SECRET, Fun, refusal, target

if TYPE_CHECKING:
    from sankey_studio.models import AppSettings


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (WriteError(f"invalid {SECRET}", code=121), "write_rejected"),
        (WriteError("immutable shard key", code=66), "write_rejected"),
        (WriteError("anything", code=None), "write_rejected"),
        (WriteError("denied", code=13), "permission_denied"),
        (WriteError("denied", code=18), "permission_denied"),
    ],
    ids=["validation", "shard key", "no code", "denied 13", "denied 18"],
)
def test_a_rejected_update_is_an_expected_refusal(
    app_settings: AppSettings, error: WriteError, reason: str
) -> None:
    """Like an insert: the edit stays in the graph. Not a 502 (a sharded cluster refuses a change
    of the shard key, a collection validator refuses a value)."""
    clients = broken_clients(app_settings, error)
    assert refusal(update_by_ids, target(clients), [1], {}, Fun) == reason


def test_a_driver_failure_on_update_is_still_an_ordinary_failure(app_settings: AppSettings) -> None:
    clients = broken_clients(app_settings, PyMongoError(f"boom {SECRET}"))
    with pytest.raises(SourceWriteError):
        update_by_ids(target(clients), [1], {}, Fun)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            NotPrimaryError(SECRET),
            "MongoDB connection 'test' has no primary right now; try again shortly",
        ),
        (
            AutoReconnect(SECRET),
            (
                "MongoDB connection 'test' was interrupted (AutoReconnect); try again shortly. "
                "A write in flight may have been applied"
            ),
        ),
        (
            WTimeoutError(SECRET, code=64),
            "MongoDB write on 'test' was not confirmed by enough members; it may have been applied",
        ),
    ],
    ids=["not primary", "reconnect", "write concern timeout"],
)
def test_a_failover_during_a_write_back_says_to_try_again(
    app_settings: AppSettings, error: Exception, message: str
) -> None:
    where = target(broken_clients(app_settings, error))
    for call in (
        partial(update_by_ids, where, [1], {}, Fun),
        partial(insert_document, where, {"a": 1}),
    ):
        with pytest.raises(SourceWriteError) as info:
            call()
        assert info.value.message == message
        assert SECRET not in repr(info.value)
