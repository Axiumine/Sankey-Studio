# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Shared by the source write-back tests: the made-up target, a secret and the refusal helper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import SourceEditRefused
from sankey_studio.storage.mongo_source_writes import SourceTarget

if TYPE_CHECKING:
    from sankey_studio.mongo import MongoClients

SECRET = "mongodb://user:hunter2@db.internal:27017/flows"
DATABASE = "flows"
COLLECTION = "events"
Fun = {"$set": {"cat": "Fun"}}


def target(
    clients: MongoClients, collection: str = COLLECTION, database: str = DATABASE
) -> SourceTarget:
    return SourceTarget(clients, "test", database, collection)


def refusal(call: Any, *args: Any) -> str:
    with pytest.raises(SourceEditRefused) as info:
        call(*args)
    return info.value.reason
