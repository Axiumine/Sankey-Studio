"""Image export without Chrome: clamps, caps, the slot, the seam and the error table."""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

import kaleido
import pytest
from choreographer.errors import (
    BrowserDepsError,
    ChannelClosedError,
    DevtoolsProtocolError,
    MessageTooLargeError,
    MessageTypeError,
    MissingKeyError,
)
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
from sankey_studio.render.export import images
from sankey_studio.render.export.images import (
    DEFAULT_IMAGE_HEIGHT,
    ERROR_TABLE,
    EXPORT_MAX_LINKS,
    EXPORT_MAX_NODES,
    EXPORT_MAX_PIXELS,
    EXPORT_WAIT_S,
    KALEIDO_TIMEOUT_S,
    export_image,
    graph_size,
    map_render_error,
    resolve_image,
    transparent_copy,
)
from sankey_studio.render.options import ImageOptions, ResolvedImage


def sankey_like(links: int = 3, nodes: int = 4, height: int | None = 500) -> dict[str, Any]:
    layout: dict[str, Any] = {} if height is None else {"height": height, "paper_bgcolor": "#fff"}
    trace = {"type": "sankey", "link": {"value": [1.0] * links}, "node": {"label": ["n"] * nodes}}
    return {"data": [trace, {"type": "scatter", "x": [None]}], "layout": layout}


class FakeKaleido:
    """Stands in for ``kaleido.calc_fig_sync`` and records what it was given."""

    def __init__(self, result: bytes = b"IMAGE", error: BaseException | None = None) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        self.result = result
        self.error = error

    def __call__(self, fig: dict[str, Any], opts: dict[str, Any], kopts: dict[str, Any]) -> bytes:
        self.calls.append((fig, opts, kopts))
        if self.error is not None:
            raise self.error
        return self.result


class FakeSlot:
    """Stands in for the export semaphore."""

    def __init__(self, free: bool = True) -> None:
        self.timeouts: list[float] = []
        self.released = 0
        self.free = free

    def acquire(self, timeout: float) -> bool:
        self.timeouts.append(timeout)
        return self.free

    def release(self) -> None:
        self.released += 1


@pytest.fixture
def fake_kaleido(monkeypatch: pytest.MonkeyPatch) -> FakeKaleido:
    fake = FakeKaleido()
    monkeypatch.setattr(kaleido, "calc_fig_sync", fake)
    return fake


@pytest.fixture
def fake_slot(monkeypatch: pytest.MonkeyPatch) -> FakeSlot:
    slot = FakeSlot()
    monkeypatch.setattr(images, "_EXPORT_SLOT", slot)
    return slot


def test_constants() -> None:
    assert EXPORT_MAX_PIXELS == 36_000_000
    assert EXPORT_MAX_LINKS == 5000
    assert EXPORT_MAX_NODES == 2000
    assert EXPORT_WAIT_S == 2
    assert KALEIDO_TIMEOUT_S == 30
    assert DEFAULT_IMAGE_HEIGHT == 800
    assert ImageOptions() == ImageOptions(width=1200, height=None, scale=2.0, transparent=False)


class Side(NamedTuple):
    asked: int
    used: int


SIDES = [
    Side(1, 200),
    Side(199, 200),
    Side(200, 200),
    Side(201, 201),
    Side(3999, 3999),
    Side(4000, 4000),
    Side(4001, 4000),
    Side(10**6, 4000),
]


@pytest.mark.parametrize("case", SIDES)
def test_width_and_height_are_clamped_to_200_4000(case: Side) -> None:
    figure = sankey_like(height=500)
    scale = 1.0
    wide = resolve_image(figure, "png", ImageOptions(width=case.asked, height=200, scale=scale))
    tall = resolve_image(figure, "png", ImageOptions(width=200, height=case.asked, scale=scale))
    assert wide.width == case.used
    assert tall.height == case.used


class ScaleCase(NamedTuple):
    asked: float
    used: float


@pytest.mark.parametrize(
    "case",
    [
        ScaleCase(0.0, 1.0),
        ScaleCase(0.5, 1.0),
        ScaleCase(1.0, 1.0),
        ScaleCase(1.5, 1.5),
        ScaleCase(3.99, 3.99),
        ScaleCase(4.0, 4.0),
        ScaleCase(4.5, 4.0),
        ScaleCase(99.0, 4.0),
    ],
)
def test_scale_is_clamped_to_1_4(case: ScaleCase) -> None:
    resolved = resolve_image(
        sankey_like(), "svg", ImageOptions(width=200, height=200, scale=case.asked)
    )
    assert resolved.scale == case.used


class HeightCase(NamedTuple):
    layout_height: int | None
    asked: int | None
    used: int


@pytest.mark.parametrize(
    "case",
    [
        HeightCase(None, None, 800),
        HeightCase(600, None, 600),
        HeightCase(100, None, 200),
        HeightCase(5000, None, 4000),
        HeightCase(600, 300, 300),
        HeightCase(None, 300, 300),
        HeightCase(None, 0, 200),
    ],
)
def test_height_defaults_to_the_figure_then_to_800(case: HeightCase) -> None:
    figure = sankey_like(height=case.layout_height)
    resolved = resolve_image(figure, "png", ImageOptions(width=1000, height=case.asked, scale=1.0))
    assert resolved == ResolvedImage(fmt="png", width=1000, height=case.used, scale=1.0)


def test_a_figure_without_a_layout_key_uses_the_default_height() -> None:
    resolved = resolve_image({"data": []}, "svg", ImageOptions())
    assert (resolved.fmt, resolved.width, resolved.height, resolved.scale) == (
        "svg",
        1200,
        800,
        2.0,
    )


class Pixels(NamedTuple):
    width: int
    height: int
    scale: float
    allowed: bool


PIXELS = [
    Pixels(3000, 3000, 2.0, True),  # exactly 36,000,000
    Pixels(3001, 3000, 2.0, False),
    Pixels(4000, 4000, 1.5, True),  # exactly 36,000,000
    Pixels(4000, 4000, 1.5000001, False),
    Pixels(4000, 4000, 1.0, True),
    Pixels(4000, 4000, 4.0, False),
    Pixels(1200, 800, 2.0, True),
    Pixels(4000, 2250, 2.0, True),  # exactly 36,000,000
    Pixels(4000, 2251, 2.0, False),
    Pixels(200, 200, 4.0, True),
]


@pytest.mark.parametrize("case", PIXELS)
def test_pixel_cap_is_36_million(case: Pixels) -> None:
    options = ImageOptions(width=case.width, height=case.height, scale=case.scale)
    if case.allowed:
        resolved = resolve_image(sankey_like(), "png", options)
        assert resolved.width * resolved.height * resolved.scale**2 <= EXPORT_MAX_PIXELS
        return
    with pytest.raises(ExportTooLargeError) as caught:
        resolve_image(sankey_like(), "png", options)
    assert caught.value.message.endswith(
        "pixels: lower the size or the scale, or use the browser download"
    )
    assert "36,000,000" in caught.value.message
    assert caught.value.status_code == 422
    assert caught.value.code == "export_too_large"


def test_the_pixel_message_names_the_numbers() -> None:
    with pytest.raises(ExportTooLargeError) as caught:
        resolve_image(sankey_like(), "png", ImageOptions(width=4000, height=4000, scale=4.0))
    assert caught.value.message == (
        "4000x4000 at scale 4 is more than 36,000,000 pixels: "
        "lower the size or the scale, or use the browser download"
    )


class Size(NamedTuple):
    links: int
    nodes: int
    allowed: bool


SIZES = [
    Size(5000, 2000, True),
    Size(5001, 10, False),
    Size(10, 2001, False),
    Size(5001, 2001, False),
    Size(0, 0, True),
    Size(4999, 1999, True),
]


@pytest.mark.parametrize("case", SIZES)
def test_graph_size_caps_are_5000_links_and_2000_nodes(case: Size) -> None:
    figure = sankey_like(links=case.links, nodes=case.nodes)
    if case.allowed:
        resolved = resolve_image(figure, "svg", ImageOptions(width=200, height=200, scale=1.0))
        assert (resolved.width, resolved.height) == (200, 200)
        return
    with pytest.raises(ExportTooLargeError) as caught:
        resolve_image(figure, "svg", ImageOptions())
    assert caught.value.message == (
        f"The graph has {case.links} links and {case.nodes} nodes; image export is limited to "
        "5000 links and 2000 nodes: reduce the graph or use the browser download"
    )


def test_graph_size_adds_up_every_sankey_trace_and_ignores_the_rest() -> None:
    figure = sankey_like(links=2, nodes=3)
    figure["data"].append(sankey_like(links=5, nodes=7)["data"][0])
    figure["data"].append({"type": "pie", "values": [1, 2, 3]})
    assert graph_size(figure) == (7, 10)
    assert graph_size({"data": []}) == (0, 0)
    assert graph_size({}) == (0, 0)


def test_transparent_copy_clears_both_backgrounds_and_leaves_the_original() -> None:
    figure = sankey_like()
    clone = transparent_copy(figure)
    assert clone["layout"]["paper_bgcolor"] == "rgba(0,0,0,0)"
    assert clone["layout"]["plot_bgcolor"] == "rgba(0,0,0,0)"
    assert figure["layout"] == {"height": 500, "paper_bgcolor": "#fff"}
    assert clone["layout"]["height"] == 500
    clone["data"][0]["link"]["value"].append(9.0)
    assert len(figure["data"][0]["link"]["value"]) == 3
    assert transparent_copy({"data": []})["layout"]["paper_bgcolor"] == "rgba(0,0,0,0)"


def test_the_chrome_seam_passes_the_clamped_numbers_and_switches_mathjax_off(
    fake_kaleido: FakeKaleido,
) -> None:
    figure = sankey_like()
    resolved = ResolvedImage(fmt="png", width=900, height=450, scale=1.5)
    assert images._render_image(figure, resolved) == b"IMAGE"
    ((sent, opts, kopts),) = fake_kaleido.calls
    assert sent is figure
    assert opts == {"format": "png", "width": 900, "height": 450, "scale": 1.5}
    assert kopts == {"mathjax": False, "timeout": 30}
    assert kopts["mathjax"] is False


def test_export_image_resolves_then_renders_and_returns_the_bytes(
    fake_kaleido: FakeKaleido, fake_slot: FakeSlot
) -> None:
    figure = sankey_like(height=300)
    data = export_image(figure, "svg", ImageOptions(width=5000, scale=9.0, height=None))
    assert data == b"IMAGE"
    ((sent, opts, _kopts),) = fake_kaleido.calls
    assert sent is figure
    assert opts == {"format": "svg", "width": 4000, "height": 300, "scale": 4.0}
    assert fake_slot.released == 1


def test_default_options_are_1200_wide_at_scale_2(
    fake_kaleido: FakeKaleido, fake_slot: FakeSlot
) -> None:
    export_image(sankey_like(height=500), "png")
    ((_fig, opts, _kopts),) = fake_kaleido.calls
    assert opts == {"format": "png", "width": 1200, "height": 500, "scale": 2.0}
    assert fake_slot.timeouts == [2]


def test_transparent_renders_a_transparent_copy(
    fake_kaleido: FakeKaleido, fake_slot: FakeSlot
) -> None:
    figure = sankey_like()
    export_image(figure, "png", ImageOptions(transparent=True))
    export_image(figure, "png", ImageOptions(transparent=False))
    (first, _o1, _k1), (second, _o2, _k2) = fake_kaleido.calls
    assert first is not figure
    assert first["layout"]["paper_bgcolor"] == "rgba(0,0,0,0)"
    assert second is figure
    assert figure["layout"]["paper_bgcolor"] == "#fff"
    assert fake_slot.released == 2


def test_a_too_large_request_is_refused_before_the_slot_is_taken(
    fake_kaleido: FakeKaleido, fake_slot: FakeSlot
) -> None:
    with pytest.raises(ExportTooLargeError):
        export_image(sankey_like(links=6000), "png")
    assert fake_slot.timeouts == []
    assert fake_slot.released == 0
    assert fake_kaleido.calls == []


def test_the_slot_wait_is_two_seconds_and_a_busy_slot_is_refused(
    fake_kaleido: FakeKaleido, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = FakeSlot(free=False)
    monkeypatch.setattr(images, "_EXPORT_SLOT", slot)
    with pytest.raises(ExportBusyError) as caught:
        export_image(sankey_like(), "png")
    assert slot.timeouts == [2]
    assert slot.released == 0
    assert fake_kaleido.calls == []
    assert caught.value.code == "export_busy"
    assert caught.value.status_code == 503
    assert caught.value.message == "Another image export is running; try again in a moment"


class Failure(NamedTuple):
    error: BaseException
    mapped: type[SankeyError]
    message: str


# devtools messages: the choreographer stubs want TypedDicts, the tests only need their text
SECRET_COMMAND: Any = {"secret": "see /tmp/secret"}
SECRET_REPLY: Any = {"error": {"code": -32000, "message": "Target closed /tmp/secret"}}
UNAVAILABLE = "Image export needs Chrome or Chromium: install it, or run plotly_get_chrome"
FAILURES = [
    Failure(ChromeNotFoundError("/usr/bin/secret-chrome"), ExportUnavailableError, UNAVAILABLE),
    Failure(
        TimeoutError("took 31s at /tmp/secret"), ExportTimeoutError, "The image export timed out"
    ),
    Failure(BrowserClosedError("closed /tmp/secret"), ExportFailedError, "The image export failed"),
    Failure(BrowserFailedError("failed /tmp/secret"), ExportFailedError, "The image export failed"),
    Failure(
        KaleidoError(5, "bad figure /tmp/secret"), ExportFailedError, "The image export failed"
    ),
    Failure(JavascriptError("js /tmp/secret"), ExportFailedError, "The image export failed"),
    Failure(RuntimeError("boom /tmp/secret"), ExportFailedError, "The image export failed"),
    Failure(OSError("spawn /tmp/secret"), ExportFailedError, "The image export failed"),
    # choreographer, kaleido's driver: a protocol error is a plain Exception, so it needs its row
    Failure(
        DevtoolsProtocolError(SECRET_REPLY),
        ExportFailedError,
        "The image export failed",
    ),
    Failure(
        MessageTypeError("id /tmp/secret", 5, str), ExportFailedError, "The image export failed"
    ),
    Failure(
        MissingKeyError("id", SECRET_COMMAND),
        ExportFailedError,
        "The image export failed",
    ),
    Failure(BrowserDepsError(), ExportFailedError, "The image export failed"),
    Failure(ChannelClosedError("pipe /tmp/secret"), ExportFailedError, "The image export failed"),
    Failure(
        MessageTooLargeError(2, 1, "payload /tmp/secret"),
        ExportFailedError,
        "The image export failed",
    ),
]


@pytest.mark.parametrize("case", FAILURES, ids=lambda case: type(case.error).__name__)
def test_every_kaleido_failure_maps_to_a_domain_error_without_the_driver_text(
    case: Failure, fake_slot: FakeSlot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kaleido, "calc_fig_sync", FakeKaleido(error=case.error))
    with pytest.raises(case.mapped) as caught:
        export_image(sankey_like(), "png")
    assert type(caught.value) is case.mapped
    assert caught.value.message == case.message
    assert "secret" not in caught.value.message
    assert caught.value.__cause__ is case.error
    assert fake_slot.released == 1


def test_the_error_table_order_lets_the_specific_rows_win() -> None:
    assert ChromeNotFoundError.__mro__[1] is RuntimeError
    assert TimeoutError.__mro__[1] is OSError
    assert type(map_render_error(ChromeNotFoundError("x"))) is ExportUnavailableError
    assert type(map_render_error(TimeoutError("x"))) is ExportTimeoutError
    assert [row[1] for row in ERROR_TABLE] == [
        ExportUnavailableError,
        ExportTimeoutError,
        ExportFailedError,
    ]


def test_other_exceptions_pass_through_and_still_release_the_slot(
    fake_slot: FakeSlot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kaleido, "calc_fig_sync", FakeKaleido(error=ValueError("bug")))
    with pytest.raises(ValueError, match="bug"):
        export_image(sankey_like(), "png")
    assert fake_slot.released == 1


@pytest.mark.usefixtures("fake_slot")
def test_a_failed_export_is_logged_with_the_exception_class_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(kaleido, "calc_fig_sync", FakeKaleido(error=RuntimeError("detail")))
    with (
        caplog.at_level(logging.WARNING, logger=images.logger.name),
        pytest.raises(ExportFailedError),
    ):
        export_image(sankey_like(), "png")
    (record,) = caplog.records
    assert record.getMessage() == "image export failed: RuntimeError"
    assert record.exc_info is not None


def test_the_real_slot_is_released_after_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeKaleido(error=RuntimeError("x"))
    monkeypatch.setattr(kaleido, "calc_fig_sync", fake)
    for _ in range(3):
        with pytest.raises(ExportFailedError):
            export_image(sankey_like(), "png")
    fake.error = None
    assert export_image(sankey_like(), "png") == b"IMAGE"
    assert len(fake.calls) == 4
