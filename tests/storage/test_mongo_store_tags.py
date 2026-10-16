# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``all_tags`` of the Mongo store only reports text tags, whatever a foreign document holds."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.storage.support import ID_A, ID_B

if TYPE_CHECKING:
    from pymongo.collection import Collection

    from sankey_studio.storage import MongoGraphRepository


def test_non_text_tags_of_a_foreign_document_are_ignored(
    mongo_repo: MongoGraphRepository, mongo_collection: Collection[Any]
) -> None:
    mongo_collection.insert_one({"_id": ID_A, "tags": ["beta", 7, None, "alpha"]})
    mongo_collection.insert_one({"_id": ID_B, "tags": ["alpha", 3.5, True]})
    assert mongo_repo.all_tags() == ["alpha", "beta"]


def test_a_store_without_documents_has_no_tags(mongo_repo: MongoGraphRepository) -> None:
    assert mongo_repo.all_tags() == []
