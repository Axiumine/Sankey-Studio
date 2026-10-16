# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The JSON scanner's starting state: nothing read, nothing consumed, the stream not at its end.

``json_links`` always calls ``skip_space`` first, which refills the buffer and overwrites every
one of these fields, so no behaviour through the public API tells a wrong start from the right
one. The scanner is a reusable cursor with a contract of its own: a wrong start (a cursor
already past the empty buffer, a stream believed finished before the first read) would be a
bug the day a caller asks it something before the first ``skip_space``.
"""

from __future__ import annotations

import io

from sankey_studio.sources.formats.json_rows import _Scanner


def test_a_fresh_scanner_has_read_and_consumed_nothing() -> None:
    scan = _Scanner(io.StringIO("[1]"), "inline")
    assert scan._buf == ""
    assert scan._pos == 0
    assert scan._line == 1
    assert scan._first is True
    assert scan.peek() == ""


def test_a_fresh_scanner_does_not_think_the_stream_is_over() -> None:
    scan = _Scanner(io.StringIO("[1]"), "inline")
    assert scan._eof is False
    assert scan._can_grow() is True


def test_the_stream_is_over_only_after_a_read_returns_nothing() -> None:
    scan = _Scanner(io.StringIO("  "), "inline")
    assert scan.skip_space() is False
    assert scan._eof is True
    assert scan._can_grow() is False
