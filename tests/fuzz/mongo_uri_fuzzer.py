# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Atheris entry point (ClusterFuzzLite) for the MongoDB URI guard and masking.

Only the .clusterfuzzlite image has atheris. Imports inside ``instrument_imports`` are the ones
the engine gets coverage feedback from, so only the application package is listed.
"""

from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports(include=["sankey_studio"]):
    from tests.fuzz.guard_targets import fuzz_mongo_uri


def main() -> None:
    atheris.Setup(sys.argv, fuzz_mongo_uri)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
