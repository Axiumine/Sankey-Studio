# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Contract smoke tests: the tooling every other test relies on is wired."""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError

from sankey_studio.errors import UnsafeSourceError
from sankey_studio.models import MongoSource, TextSource
from sankey_studio.mongo_safety import check_pipeline
from sankey_studio.util import mask_uri


def test_mask_uri_hides_password() -> None:
    masked = mask_uri(
        "mongodb://bob:s3cret@db1:27017,db2:27017/app?replicaSet=rs&tlsCertificateKeyFilePassword=x"
    )
    assert "s3cret" not in masked
    assert "bob:***@db1" in masked
    assert "tlsCertificateKeyFilePassword=***" in masked


def test_text_source_rejects_path_escape() -> None:
    with pytest.raises(ValidationError):
        TextSource(origin="file", path="../etc/passwd")


def test_mongo_source_rejects_write_stage() -> None:
    with pytest.raises(UnsafeSourceError):
        check_pipeline([{"$out": "x"}])
    with pytest.raises(ValidationError):
        MongoSource(
            connection="c", collection="flows", mode="aggregate", pipeline=[{"$merge": "x"}]
        )


@pytest.mark.memory
@pytest.mark.limit_memory("64 MB")
def test_memray_plugin_wired() -> None:
    assert sum(range(1000)) == 499500


def test_testclient_imports_without_warnings() -> None:
    """starlette 1.x warns on `httpx`-only installs; httpx2 (dev dependency) silences it.

    Under ``filterwarnings = error`` that warning would kill every web test at import time.
    """
    code = "import fastapi.testclient"
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-W", "error", "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr[-400:]
