# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``edits.reasons``: one fixed sentence for every reason that is not silent."""

from __future__ import annotations

from typing import get_args

import pytest

from sankey_studio.edits.reasons import NOTICES, REFORMATTED_NOTICE, notice_for
from sankey_studio.models.edits import SILENT_REASONS, Reason

REASONS = set(get_args(Reason))


def test_the_notices_and_the_silent_reasons_cover_every_reason_exactly() -> None:
    assert len(REASONS) == 25
    assert set(NOTICES) | SILENT_REASONS == REASONS
    assert not set(NOTICES) & SILENT_REASONS
    assert {"preference", "order_in_graph"} == SILENT_REASONS


@pytest.mark.parametrize("reason", sorted(NOTICES))
def test_a_notice_is_one_ascii_english_sentence(reason: str) -> None:
    text = NOTICES[reason]
    assert text.isascii()
    assert text.endswith(".")
    assert text[0].isupper()
    assert "\n" not in text
    assert len(text) < 200


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        (
            "read_only_mode",
            (
                "This server is read-only here: your change stays in this graph and is not "
                "written to the source."
            ),
        ),
        (
            "no_category_field",
            "Choose the category field in the Source panel to save categories in MongoDB.",
        ),
        (
            "would_recolour",
            (
                "Rows were not reordered because that would change the colours. The order is "
                "kept in this graph."
            ),
        ),
        (
            "unsafe_value",
            "That text could be read as a spreadsheet formula, so it was kept in this graph only.",
        ),
    ],
)
def test_the_four_sentences_of_the_design_are_exact(reason: str, text: str) -> None:
    assert NOTICES[reason] == text


def test_the_reformat_sentence() -> None:
    assert REFORMATTED_NOTICE == "Your JSON text was re-formatted."


def test_notice_for_answers_none_for_no_reason_and_for_silent_reasons() -> None:
    assert notice_for(None) is None
    assert notice_for("preference") is None
    assert notice_for("order_in_graph") is None
    assert notice_for("no_match") == NOTICES["no_match"]
