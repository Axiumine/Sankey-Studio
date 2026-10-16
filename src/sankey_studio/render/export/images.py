# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""SVG and PNG export through kaleido and Chrome.

The work is split so that every branch is testable without Chrome: ``resolve_image`` is pure
(clamps and caps), ``export_image`` serialises exports and maps errors, and ``_render_image`` is
the ONLY function that touches kaleido (tests monkeypatch it or ``kaleido.calc_fig_sync``).
MathJax stays off: it would be fetched from a CDN on every export.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import TYPE_CHECKING, Any

import kaleido
from choreographer.errors import DevtoolsProtocolError, MessageTypeError, MissingKeyError
from kaleido.errors import (
    BrowserClosedError,
    BrowserFailedError,
    ChromeNotFoundError,
    JavascriptError,
    KaleidoError,
)

from sankey_studio.errors import (
    ExportBusyError,
    ExportFailedError,
    ExportTimeoutError,
    ExportTooLargeError,
    ExportUnavailableError,
    SankeyError,
)
from sankey_studio.render.options import ImageOptions, ResolvedImage

if TYPE_CHECKING:
    from sankey_studio.render.options import ImageFormat

logger = logging.getLogger(__name__)

EXPORT_MIN_SIDE = 200
EXPORT_MAX_SIDE = 4000
EXPORT_MIN_SCALE = 1.0
EXPORT_MAX_SCALE = 4.0
#: ``width * height * scale ** 2`` may not exceed this.
EXPORT_MAX_PIXELS = 36_000_000
EXPORT_MAX_LINKS = 5000
EXPORT_MAX_NODES = 2000
#: Seconds a request waits for the one export slot before ``ExportBusyError``.
EXPORT_WAIT_S = 2
#: Seconds kaleido may take for one image before Chrome is killed.
KALEIDO_TIMEOUT_S = 30
DEFAULT_IMAGE_HEIGHT = 800
TRANSPARENT = "rgba(0,0,0,0)"
TOO_BIG_HINT = "reduce the graph or use the browser download"

#: One export at a time: Chrome is heavy, so a second request is refused instead of queued.
_EXPORT_SLOT = threading.BoundedSemaphore(1)

#: kaleido/Chrome failures, first match wins: (exception types, error to raise, message).
#: ``DevtoolsProtocolError`` (Chrome answered a protocol command with an error; a plain
#: ``Exception``) and the two malformed-reply types (``MessageTypeError`` is a ``TypeError``,
#: ``MissingKeyError`` a ``ValueError``) come from choreographer, kaleido's driver, and are not
#: subclasses of the rows above. Every other choreographer error (``BrowserDepsError``,
#: ``ChannelClosedError``, ``MessageTooLargeError``, ``JSONError``) already is a ``RuntimeError``
#: or an ``OSError``. A bare ``ValueError``/``TypeError`` stays unmapped: it means a bug here.
ERROR_TABLE: tuple[tuple[tuple[type[BaseException], ...], type[SankeyError], str], ...] = (
    (
        (ChromeNotFoundError,),
        ExportUnavailableError,
        "Image export needs Chrome or Chromium: install it, or run plotly_get_chrome",
    ),
    ((TimeoutError,), ExportTimeoutError, "The image export timed out"),
    (
        (
            BrowserClosedError,
            BrowserFailedError,
            KaleidoError,
            JavascriptError,
            DevtoolsProtocolError,
            MessageTypeError,
            MissingKeyError,
            RuntimeError,
            OSError,
        ),
        ExportFailedError,
        "The image export failed",
    ),
)
CAUGHT: tuple[type[BaseException], ...] = tuple(kind for row in ERROR_TABLE for kind in row[0])


def _clamp[T: (int, float)](value: T, low: T, high: T) -> T:
    return max(low, min(value, high))


def graph_size(figure: dict[str, Any]) -> tuple[int, int]:
    """Total links and nodes over the Sankey traces of ``figure``."""
    links = nodes = 0
    for trace in figure.get("data", []):
        if trace.get("type") == "sankey":
            links += len(trace["link"]["value"])
            nodes += len(trace["node"]["label"])
    return links, nodes


def resolve_image(figure: dict[str, Any], fmt: ImageFormat, options: ImageOptions) -> ResolvedImage:
    """Clamp the size to 200..4000 px and the scale to 1..4, then apply the caps.

    ``height=None`` takes the figure's own height (``DEFAULT_IMAGE_HEIGHT`` when it has none).
    Raises ``ExportTooLargeError`` above the pixel cap or for a graph of more than
    ``EXPORT_MAX_LINKS`` links or ``EXPORT_MAX_NODES`` nodes.
    """
    links, nodes = graph_size(figure)
    if links > EXPORT_MAX_LINKS or nodes > EXPORT_MAX_NODES:
        raise ExportTooLargeError(
            f"The graph has {links} links and {nodes} nodes; image export is limited to "
            f"{EXPORT_MAX_LINKS} links and {EXPORT_MAX_NODES} nodes: {TOO_BIG_HINT}"
        )
    own_height = figure.get("layout", {}).get("height") or DEFAULT_IMAGE_HEIGHT
    height = options.height if options.height is not None else own_height
    width = _clamp(options.width, EXPORT_MIN_SIDE, EXPORT_MAX_SIDE)
    height = _clamp(int(height), EXPORT_MIN_SIDE, EXPORT_MAX_SIDE)
    scale = _clamp(options.scale, EXPORT_MIN_SCALE, EXPORT_MAX_SCALE)
    if width * height * scale**2 > EXPORT_MAX_PIXELS:
        raise ExportTooLargeError(
            f"{width}x{height} at scale {scale:g} is more than {EXPORT_MAX_PIXELS:,} pixels: "
            "lower the size or the scale, or use the browser download"
        )
    return ResolvedImage(fmt=fmt, width=width, height=height, scale=scale)


def transparent_copy(figure: dict[str, Any]) -> dict[str, Any]:
    """A deep copy whose paper and plot backgrounds are fully transparent."""
    clone = copy.deepcopy(figure)
    layout = clone.setdefault("layout", {})
    layout["paper_bgcolor"] = TRANSPARENT
    layout["plot_bgcolor"] = TRANSPARENT
    return clone


def _render_image(figure: dict[str, Any], resolved: ResolvedImage) -> bytes:
    """The ONLY function that touches kaleido (one-shot Chrome, MathJax off, bounded time)."""
    image: bytes = kaleido.calc_fig_sync(
        figure,
        opts={
            "format": resolved.fmt,
            "width": resolved.width,
            "height": resolved.height,
            "scale": resolved.scale,
        },
        kopts={"mathjax": False, "timeout": KALEIDO_TIMEOUT_S},
    )
    return image


def map_render_error(exc: BaseException) -> SankeyError:
    """The domain error for a kaleido/Chrome failure; its message never quotes the driver."""
    _kinds, error, message = next(row for row in ERROR_TABLE if isinstance(exc, row[0]))
    return error(message)


def export_image(
    figure: dict[str, Any], fmt: ImageFormat, options: ImageOptions | None = None
) -> bytes:
    """Render ``figure`` to SVG or PNG bytes (one export at a time, 30 s at most)."""
    options = options or ImageOptions()
    resolved = resolve_image(figure, fmt, options)
    source = transparent_copy(figure) if options.transparent else figure
    if not _EXPORT_SLOT.acquire(timeout=EXPORT_WAIT_S):
        raise ExportBusyError("Another image export is running; try again in a moment")
    try:
        return _render_image(source, resolved)
    except CAUGHT as exc:
        logger.warning("image export failed: %s", type(exc).__name__, exc_info=exc)
        raise map_render_error(exc) from exc
    finally:
        _EXPORT_SLOT.release()
