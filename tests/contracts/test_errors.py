# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract tests: the error hierarchy (codes, statuses, details)."""

from __future__ import annotations

import pytest

from sankey_studio import errors
from sankey_studio.models import ManualSource


def _all_errors() -> list[type[errors.SankeyError]]:
    found: list[type[errors.SankeyError]] = []
    stack = [errors.SankeyError]
    while stack:
        cls = stack.pop()
        found.append(cls)
        stack.extend(cls.__subclasses__())
    return found


def test_every_error_has_a_unique_code_and_a_valid_status() -> None:
    classes = _all_errors()
    codes = [c.code for c in classes]
    assert len(codes) == len(set(codes)), "two error classes share one code"
    for cls in classes:
        assert 400 <= cls.status_code <= 599
        assert cls.code == cls.code.lower()
    assert len(classes) >= 20


@pytest.mark.parametrize(
    ("cls", "status", "code"),
    [
        (errors.ForbiddenError, 403, "forbidden"),
        (errors.ReadOnlyModeError, 403, "read_only_mode"),
        (errors.UnsupportedMediaTypeError, 415, "unsupported_media_type"),
        (errors.PayloadTooLargeError, 413, "payload_too_large"),
        (errors.BusyError, 503, "busy"),
        (errors.ExportBusyError, 503, "export_busy"),
        (errors.ExportTooLargeError, 422, "export_too_large"),
        (errors.ExportUnavailableError, 501, "export_unavailable"),
        (errors.ExportFailedError, 502, "export_failed"),
        (errors.ExportTimeoutError, 504, "export_timeout"),
        (errors.NoCategoriesError, 422, "no_categories"),
        (errors.ConflictError, 409, "conflict"),
        (errors.FolderRuleError, 422, "folder_rule"),
        (errors.FolderNameTakenError, 409, "folder_name_taken"),
        (errors.SourceEditRefused, 422, "source_edit_refused"),
        (errors.SourceWriteError, 502, "source_write_failed"),
    ],
)
def test_error_status_and_code(cls: type[errors.SankeyError], status: int, code: str) -> None:
    assert (cls.status_code, cls.code) == (status, code)


def test_a_folder_name_clash_is_not_a_stale_revision() -> None:
    assert not issubclass(errors.FolderNameTakenError, errors.ConflictError)
    assert errors.FolderNameTakenError.code != errors.ConflictError.code
    assert errors.FolderNameTakenError.__bases__ == (errors.SankeyError,)


def test_a_refused_edit_carries_its_reason() -> None:
    refused = errors.SourceEditRefused("no_consent")
    assert refused.reason == "no_consent"
    assert refused.message == "This edit cannot be written back to the source (no_consent)"
    assert refused.details == []
    assert isinstance(refused, errors.SourceError)


def test_a_source_write_error_is_a_plain_sankey_error() -> None:
    failed = errors.SourceWriteError("Writing to connection 'main' failed (OperationFailure)")
    assert type(failed).__bases__ == (errors.SankeyError,)
    assert failed.message.endswith("(OperationFailure)")


def test_error_details_default_to_empty_list() -> None:
    err = errors.SourceError("x")
    assert err.details == []
    assert errors.SourceError("x", details=["a"]).details == ["a"]
    assert isinstance(ManualSource().links, list)
