# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Turn the raw bytes of one fuzz input into typed choices (no fuzzing engine is imported).

Seeds are plain text files, so options are not a binary header: they are the LAST bytes of the
input, each XOR 0x0a (a newline). A seed that ends with newlines therefore decodes to "all
defaults", and a mutation of the final bytes switches an option on.
"""

from __future__ import annotations

from dataclasses import dataclass

NEWLINE = 0x0A


@dataclass(slots=True)
class Reader:
    """Pops option bytes from the end of the input; what is left is the text."""

    data: bytes

    def option(self) -> int:
        """The last byte XOR a newline (0 on empty input); the byte is removed."""
        if not self.data:
            return 0
        last, self.data = self.data[-1], self.data[:-1]
        return last ^ NEWLINE

    def text(self) -> str:
        """The remaining bytes as text; invalid bytes become lone surrogates, never an error."""
        return self.data.decode("utf-8", "surrogateescape")


def pick[T](choices: tuple[T, ...], index: int) -> T:
    """``choices[index]``, wrapping around."""
    return choices[index % len(choices)]
