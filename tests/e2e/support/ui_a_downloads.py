"""Real browser downloads and the image formats the exports produce (UI-A suites).

``download(page, button)``  - click ``button`` and return the file the browser saved
                              (``Downloaded.name`` is the file name the user would see).
``png_info(data)``          - ``PngInfo``: the IHDR size and colour type, plus the alpha value of
                              the top-left pixel (255 = opaque, 0 = transparent background).
``image_size_hint(page)``   - the ``(width, height)`` in the "Image size" line of the export card,
                              which the PNG files must agree with.

Only the standard library reads the PNG: IHDR is fixed at bytes 16-26, the first pixel is the
first four bytes after the filter byte of the first scanline (every PNG filter is the identity
for the very first pixel, because its left, upper and upper-left neighbours do not exist).
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

DOWNLOAD_TIMEOUT_MS: Final = 90_000
PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
SVG_PREFIX: Final = b"<svg"
IHDR_SLICE: Final = slice(16, 26)
RGBA: Final = 6
OPAQUE: Final = 255
CHUNK_HEAD: Final = 8
CHUNK_TAIL: Final = 4
TIMES: Final = "x\N{MULTIPLICATION SIGN}"
SIZE_LINE: Final = re.compile(
    rf"(?:Image size:|Images come out)\s*([\d,]+)\s*[{TIMES}]\s*([\d,]+)\s*px"
)


@dataclass(frozen=True, slots=True)
class Downloaded:
    """A file the browser saved: the name it got and its bytes."""

    name: str
    data: bytes

    @property
    def text(self) -> str:
        return self.data.decode("utf-8")


@dataclass(frozen=True, slots=True)
class PngInfo:
    """What the tests need to know about a PNG file."""

    width: int
    height: int
    color_type: int
    corner_alpha: int


def download(page: Page, button: Locator) -> Downloaded:
    """Click ``button``, wait for the download to finish and return the saved file."""
    with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as pending:
        button.click()
    saved = pending.value
    return Downloaded(saved.suggested_filename, Path(saved.path()).read_bytes())


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    out: list[tuple[bytes, bytes]] = []
    at = len(PNG_MAGIC)
    while at + CHUNK_HEAD <= len(data):
        (length,) = struct.unpack(">I", data[at : at + CHUNK_TAIL])
        kind = data[at + CHUNK_TAIL : at + CHUNK_HEAD]
        out.append((kind, data[at + CHUNK_HEAD : at + CHUNK_HEAD + length]))
        at += CHUNK_HEAD + length + CHUNK_TAIL
    return out


def png_info(data: bytes) -> PngInfo:
    """Parse the PNG ``data``; fails the test when it is not a PNG."""
    assert data.startswith(PNG_MAGIC), f"not a PNG file: {data[:8]!r}"
    width, height, depth, color_type = struct.unpack(">IIBB", data[IHDR_SLICE])
    pixels = b"".join(body for kind, body in _chunks(data) if kind == b"IDAT")
    corner = zlib.decompressobj().decompress(pixels, 8)
    has_alpha = color_type == RGBA and depth == 8
    return PngInfo(width, height, color_type, corner[4] if has_alpha else OPAQUE)


def expect_image_size(page: Page, width: int, height: int | None = None) -> None:
    """The export card announces ``width`` (and ``height``) pixels; retries until it does."""
    tall = r"[\d,]+" if height is None else f"{height:,}"
    line = re.compile(rf"(?:Image size:|Images come out)\s*{width:,}\s*[{TIMES}]\s*{tall}\s*px")
    expect(page.locator("main")).to_contain_text(line)


def image_size_hint(page: Page) -> tuple[int, int]:
    """The pixel size the export card announces ("Image size: 2,400 x 1,120 px")."""
    text = page.locator("main").inner_text()
    found = SIZE_LINE.search(text)
    assert found, f"no image size line on the page:\n{text[:400]}"
    return int(found.group(1).replace(",", "")), int(found.group(2).replace(",", ""))
