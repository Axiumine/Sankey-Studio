# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Fuzz targets for the parsers and guards that read untrusted text (ClusterFuzzLite, Atheris).

The target bodies (``*_targets.py``) import no fuzzing engine and are run by ``test_targets.py``
over the seed corpus and random bytes. The ``*_fuzzer.py`` entry points import ``atheris``, which
only the ``.clusterfuzzlite`` image installs; see ``docs/fuzzing.md``.
"""
