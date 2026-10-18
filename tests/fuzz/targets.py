# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The fuzz targets by name: ``<name>`` has the entry point ``<name>_fuzzer.py`` and the seeds
``corpus/<name>/``."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from tests.fuzz.guard_targets import fuzz_mongo_guard, fuzz_mongo_uri, fuzz_names, fuzz_numfmt
from tests.fuzz.text_targets import fuzz_json_stream, fuzz_rewrite, fuzz_text_source

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

TARGETS: Mapping[str, Callable[[bytes], None]] = MappingProxyType(
    {
        "text_source": fuzz_text_source,
        "json_stream": fuzz_json_stream,
        "rewrite": fuzz_rewrite,
        "mongo_guard": fuzz_mongo_guard,
        "mongo_uri": fuzz_mongo_uri,
        "names": fuzz_names,
        "numfmt": fuzz_numfmt,
    }
)
