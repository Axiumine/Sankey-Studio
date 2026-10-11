"""Read exported images without an imaging library: PNG header and pixels, SVG text.

``png_info`` checks the magic and the IHDR chunk. ``png_pixels`` decodes an 8-bit RGBA PNG (what
the exporter writes, colour type 6) into rows of ``(r, g, b, a)``, which is what "a transparent
export really has transparent pixels" needs: the colour type alone is 6 for opaque and transparent
files alike. ``svg_texts`` / ``svg_tags`` parse an SVG export as XML (it must be well-formed) and
return what is drawn as text and which elements exist.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from collections.abc import Iterator

PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
RGBA: Final = 6
BYTES_PER_PIXEL: Final = 4
Pixel = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class PngInfo:
    """The IHDR fields that matter: size, bit depth and colour type (6 = RGBA)."""

    width: int
    height: int
    bit_depth: int
    color_type: int


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    assert data.startswith(PNG_MAGIC), f"not a PNG: {data[:8]!r}"
    position = len(PNG_MAGIC)
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        yield kind, data[position + 8 : position + 8 + length]
        position += 12 + length  # length + type + payload + crc


def png_info(data: bytes) -> PngInfo:
    """The IHDR of ``data`` (asserts the PNG magic and that IHDR is the first chunk)."""
    kind, payload = next(_chunks(data))
    assert kind == b"IHDR", f"first chunk is {kind!r}"
    width, height, depth, color = struct.unpack(">IIBB", payload[:10])
    return PngInfo(width, height, depth, color)


def _paeth(left: int, up: int, corner: int) -> int:
    estimate = left + up - corner
    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
    return (left, up, corner)[distances.index(min(distances))]


def _unfilter(kind: int, line: bytearray, previous: bytearray) -> None:
    """Undo PNG filter ``kind`` of one scanline in place (``previous`` is the line above)."""
    step = BYTES_PER_PIXEL
    for index in range(len(line)):
        left = line[index - step] if index >= step else 0
        up = previous[index]
        corner = previous[index - step] if index >= step else 0
        predictor = (0, left, up, (left + up) // 2, _paeth(left, up, corner))[kind]
        line[index] = (line[index] + predictor) & 0xFF


def png_pixels(data: bytes) -> list[list[Pixel]]:
    """Every pixel of an 8-bit RGBA PNG, row by row (small images only: pure Python)."""
    info = png_info(data)
    assert (info.bit_depth, info.color_type) == (8, RGBA), f"not RGBA8: {info}"
    raw = zlib.decompress(b"".join(body for kind, body in _chunks(data) if kind == b"IDAT"))
    stride = info.width * BYTES_PER_PIXEL
    assert len(raw) == (stride + 1) * info.height, "unexpected amount of pixel data"
    rows: list[list[Pixel]] = []
    previous = bytearray(stride)
    for y in range(info.height):
        start = y * (stride + 1)
        line = bytearray(raw[start + 1 : start + 1 + stride])
        _unfilter(raw[start], line, previous)
        rows.append([(line[i], line[i + 1], line[i + 2], line[i + 3]) for i in range(0, stride, 4)])
        previous = line
    return rows


def alpha_range(data: bytes) -> tuple[int, int]:
    """The lowest and the highest alpha value of an RGBA PNG."""
    alphas = [pixel[3] for row in png_pixels(data) for pixel in row]
    return min(alphas), max(alphas)


def svg_root(svg: str) -> ET.Element:
    """Parse an SVG export (asserts it is well-formed XML); the text comes from our own server."""
    return ET.fromstring(svg)  # noqa: S314 - SVG produced by the app under test, not input


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def svg_tags(svg: str) -> set[str]:
    """The local names of every element in the SVG."""
    return {_local(element.tag) for element in svg_root(svg).iter()}


def svg_texts(svg: str) -> list[str]:
    """What the SVG draws as text: the text of every ``text`` / ``tspan`` element, in order."""
    elements = svg_root(svg).iter()
    return [e.text for e in elements if _local(e.tag) in {"text", "tspan"} and e.text]
