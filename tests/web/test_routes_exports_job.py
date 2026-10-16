# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``ExportJob``, the value that carries one export through the router: frozen and slotted."""

from __future__ import annotations

import dataclasses

import pytest

from sankey_studio.models import GraphDraft
from sankey_studio.web.routers.exports import ExportJob
from sankey_studio.web.schemas import ExportQuery
from tests.web.test_routes_graphs_support import PLAIN, draft_json


def make_job() -> ExportJob:
    draft = GraphDraft.model_validate(draft_json(*PLAIN))
    return ExportJob(draft, "Household", ExportQuery(format="csv"))


def test_an_export_job_keeps_its_three_parts() -> None:
    job = make_job()
    assert job.title == "Household"
    assert job.query.format == "csv"
    assert job.draft.source.type == "manual"
    assert [field.name for field in dataclasses.fields(job)] == ["draft", "title", "query"]


def test_an_export_job_cannot_be_changed() -> None:
    job = make_job()
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.title = "Other"  # type: ignore[misc]
    assert job.title == "Household"


def test_an_export_job_has_no_instance_dict() -> None:
    assert not hasattr(make_job(), "__dict__")
