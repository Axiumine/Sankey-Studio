# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers of ``test_routes_exports*.py``: the Chrome seam as a recorder (no tests here)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from sankey_studio.render.export import images
from tests.web.test_routes_graphs_support import API

if TYPE_CHECKING:
    import pytest
    from httpx2 import Response

    from sankey_studio.render.options import ResolvedImage
    from tests.web.conftest import WebApp

#: What the fake Chrome returns per format.
IMAGES: Final = {"svg": b"<svg>fake</svg>", "png": b"\x89PNG fake"}
MEDIA: Final = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "html": "text/html; charset=utf-8",
    "json": "application/json",
    "csv": "text/csv; charset=utf-8",
}


class FakeRender:
    """Stands in for ``images._render_image``: records what it got, returns bytes or raises."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], ResolvedImage]] = []
        self.error: BaseException | None = None

    def __call__(self, figure: dict[str, Any], resolved: ResolvedImage) -> bytes:
        self.calls.append((figure, resolved))
        if self.error is not None:
            raise self.error
        return IMAGES[resolved.fmt]


class FakeSlot:
    """Stands in for the one-at-a-time export semaphore."""

    def __init__(self, *, free: bool = True) -> None:
        self.free = free
        self.released = 0

    def acquire(self, timeout: float) -> bool:  # noqa: ARG002 - the semaphore's signature
        return self.free

    def release(self) -> None:
        self.released += 1


def install_render(monkeypatch: pytest.MonkeyPatch) -> FakeRender:
    fake = FakeRender()
    monkeypatch.setattr(images, "_render_image", fake)
    return fake


def install_slot(monkeypatch: pytest.MonkeyPatch, *, free: bool) -> FakeSlot:
    slot = FakeSlot(free=free)
    monkeypatch.setattr(images, "_EXPORT_SLOT", slot)
    return slot


def export_saved(web: WebApp, graph_id: str, **params: Any) -> Response:
    return web.client.get(f"{API}/graphs/{graph_id}/export", params=params)


def export_draft(web: WebApp, draft: dict[str, Any], **params: Any) -> Response:
    return web.client.post(f"{API}/export", params=params, json=draft)


def disposition(name: str, ext: str) -> str:
    """The expected Content-Disposition of a plain ASCII ``name``."""
    return f"attachment; filename=\"{name}.{ext}\"; filename*=UTF-8''{name}.{ext}"
