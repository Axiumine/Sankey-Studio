/**
 * The chart panel: Sankey | Donut views of `store.bundle`, with the states of `store.status`.
 *
 * Reads (never writes) `bundle`, `status.previewing`, `status.error` and `draft.style.height`
 * (an error tagged `source: "save"` is the save bar's, not a failed preview, and is ignored):
 * - a bundle draws `bundle.figure` (and `bundle.donut` when that tab is open) with Plotly, lazily;
 * - while a new preview is in flight the old chart stays, dimmed after a short delay, so there is
 *   no skeleton flash and no layout jump; the frame height is reserved from the figure/style;
 * - no bundle yet: skeleton while loading, an error block when the preview failed, otherwise the
 *   empty state; a failed refetch keeps the last good chart and adds a notice above it;
 * - a bundle with zero nodes (every row skipped, or every link filtered out by Transform) is not drawn
 *   (Plotly cannot draw it): the frame says why, the donut hint stays away;
 * - the Donut tab exists only when `donut_available`; otherwise a hint explains how to get one.
 * The header ends with a tool group (`ctx.chartTools`, `div.out-chart-tools`, made by the editor page:
 * the chart settings gear; other features append buttons), which also holds the "Updating" label.
 * Test ids: `sankey-chart`, `donut-chart`, `chart-tab-sankey`, `chart-tab-donut`, `donut-hint`
 * (+ stats, legend, category table and warnings from ./summary.js). Charts are disposed with the
 * panel (`dispose()`).
 */

import { createChartFrame, disposeChart, draw, withoutLegend } from "../../core/chart.js";
import { h, uid } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { errorState } from "../../core/states.js";
import { focusTestId, hasDrawing, plainError, present, sentence, slot } from "../output-panel-kit.js";
import { editsFor } from "../edits/index.js";
import { requestPreview } from "../preview.js";
import { describePreviewError, isTransient, previewError } from "./errors.js";
import { buildOverlay, noLinksReason, overlayFor, setOverlay } from "./frame-state.js";
import { eventsFor, markNodeOrder, mountNodeTools } from "./node-actions.js";
import { createSummary } from "./summary.js";
import { createViewTabs } from "./view-tabs.js";

const SANKEY_HEIGHT = 560;
const DONUT_HEIGHT = 420;
const MIN_HEIGHT = 240;

function pixels(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number >= MIN_HEIGHT ? Math.round(number) : fallback;
}

function chartLabel(view, bundle) {
  if (view === "donut") {
    return `Donut chart of ${bundle.categories.length} categories`;
  }
  return `Sankey diagram with ${bundle.stats.nodes} nodes and ${bundle.stats.links} links`;
}

function donutHint() {
  return h(
    "div",
    { class: "out-hint", "data-testid": "donut-hint" },
    icon("pie-chart", { size: 16 }),
    h("p", null, "No donut yet. Give a few entries a category in the Entries table and a donut chart appears. Categories are optional: without them this is a plain Sankey."),
    h("button", { type: "button", class: "btn btn-sm", on: { click: () => focusTestId("entries-search") } }, "Go to entries"),
  );
}

class ChartPanel {
  constructor(container, ctx) {
    this.store = ctx.store;
    this.container = container;
    this.drawn = { sankey: null, donut: null };
    this.summarised = undefined;
    this.drawError = { sankey: null, donut: null };
    this.overlayKey = { sankey: "", donut: "" };
    this.frames = { sankey: createChartFrame({ height: SANKEY_HEIGHT }), donut: createChartFrame({ height: DONUT_HEIGHT }) };
    this.frames.sankey.surface.setAttribute("data-testid", "sankey-chart");
    this.frames.donut.surface.setAttribute("data-testid", "donut-chart");
    this.status = h("span", { class: "out-updating-label", "aria-hidden": "true", hidden: true }, h("span", { class: "spinner" }), "Updating");
    this.tools = ctx.chartTools ?? h("div", { class: "out-chart-tools" });
    this.tools.prepend(this.status);
    this.edits = editsFor(ctx);
    this.nodeTools = mountNodeTools({ store: this.store, tools: this.tools, edits: this.edits, surface: this.frames.sankey.surface });
    this.notice = h("div", { class: "notice out-notice", "data-kind": "warning", role: "alert" });
    this.slots = { hint: slot(), notice: slot() };
    this.hint = donutHint();
    this.summary = createSummary({ store: this.store });
    this.build();
    this.queued = false;
    this.unsubscribe = [
      this.store.subscribe(() => this.schedule(), { select: (state) => state.bundle }),
      this.store.subscribe(() => this.schedule(), { select: (state) => state.status }),
      this.store.subscribe(() => this.schedule(), { select: (state) => state.draft?.style?.height }),
    ];
    this.render();
  }

  build() {
    const titleId = uid("chart-title");
    const panels = {
      sankey: h("div", { class: "out-view" }, this.frames.sankey.frame),
      donut: h("div", { class: "out-view" }, this.frames.donut.frame),
    };
    this.tabs = createViewTabs({ label: "Chart type", panels, onSelect: () => this.drawActive() });
    const root = h(
      "section",
      { class: "card out-card out-chart", "aria-labelledby": titleId },
      h("h2", { id: titleId, class: "visually-hidden" }, "Chart"),
      h("div", { class: "out-chart-head" }, this.tabs.el, this.tools),
      h("div", { class: "out-chart-body" }, this.slots.hint, this.slots.notice, panels.sankey, panels.donut),
      this.summary.el,
    );
    this.container.replaceChildren(root);
  }

  schedule() {
    if (!this.queued) {
      this.queued = true;
      queueMicrotask(() => {
        this.queued = false;
        this.render();
      });
    }
  }

  render() {
    const state = this.store.get();
    const { bundle } = state;
    const { previewing } = state.status;
    const error = previewError(state.status.error);
    this.tabs.setDonutAvailable(Boolean(bundle?.donut_available));
    present(this.slots.hint, this.hint, hasDrawing(bundle) && !bundle.donut_available);
    this.status.hidden = !(previewing && bundle);
    this.renderNotice(error, bundle);
    this.sizeFrames(bundle, state.draft);
    if (!hasDrawing(bundle)) {
      this.clearPlots(); // nothing to draw: no chart (and no draw error) of an older bundle stays behind the empty state
      this.drawError = { sankey: null, donut: null };
    }
    this.syncOverlay("sankey");
    this.syncOverlay("donut");
    for (const view of ["sankey", "donut"]) {
      this.frames[view].surface.classList.toggle("out-updating", Boolean(previewing && bundle));
    }
    if (bundle !== this.summarised) {
      this.summarised = bundle;
      this.summary.update(bundle);
    }
    this.drawActive();
  }

  sizeFrames(bundle, draft) {
    const sankey = pixels(bundle?.figure?.layout?.height, pixels(draft?.style?.height, SANKEY_HEIGHT));
    this.frames.sankey.frame.style.setProperty("--chart-h", `${sankey}px`);
    this.frames.donut.frame.style.setProperty("--chart-h", `${pixels(bundle?.donut?.layout?.height, DONUT_HEIGHT)}px`);
  }

  renderNotice(error, bundle) {
    present(this.slots.notice, this.notice, Boolean(error && bundle));
    if (!(error && bundle)) {
      return;
    }
    const info = describePreviewError(error);
    const key = `${error.code}|${error.message}`;
    if (key === this.noticeKey && this.notice.childNodes.length > 0) {
      return; // same failure: keep the nodes, so a focused "Try again" is not rebuilt under the keyboard
    }
    this.noticeKey = key;
    this.notice.replaceChildren(
      icon("alert", { size: 16 }),
      h("div", { class: "notice-body" }, h("strong", null, `${info.title}. `), sentence(info.message), " The chart below is the last version that worked.", this.retryButton(error)),
    );
  }

  retryButton(error) {
    return isTransient(error) ? h("div", { class: "notice-actions" }, h("button", { type: "button", class: "btn btn-sm", on: { click: () => this.retryPreview() } }, "Try again")) : null;
  }

  /** Swaps the overlay of a frame only when what it shows changed (the skeleton must not restart). */
  syncOverlay(view) {
    const { bundle, status } = this.store.get();
    const model = { bundle, previewing: status.previewing, error: previewError(status.error) };
    const basisEmpty = view === "donut" && bundle?.donut_empty_reason === "basis_empty";
    const kind = view === "sankey" ? overlayFor(model) : basisEmpty ? "basis" : null;
    const reason = kind === "nolinks" ? this.noLinks(bundle) : null;
    const drawFailed = this.drawError[view];
    const detail = kind === "error" ? model.error?.message : reason?.message;
    const key = drawFailed ? `draw:${drawFailed.message}` : `${kind}:${detail ?? ""}`;
    if (key === this.overlayKey[view]) {
      return;
    }
    this.overlayKey[view] = key;
    const frame = this.frames[view].frame;
    if (drawFailed) {
      setOverlay(frame, errorState({ title: "The chart could not be drawn", message: plainError(drawFailed), compact: true, onRetry: () => this.retry(view) }));
    } else {
      setOverlay(frame, kind ? buildOverlay(kind, model.error, () => this.retryPreview(), reason) : null);
    }
  }

  /** Why a bundle has nothing to draw, worded once per bundle (the draft may already have moved on). */
  noLinks(bundle) {
    if (this.reasonOf !== bundle) {
      this.reasonOf = bundle;
      this.reason = noLinksReason(bundle, this.store.get().draft?.transform);
    }
    return this.reason;
  }

  /** Asks the composer's live preview again: a new draft object (same content) triggers one request. */
  retryPreview() {
    requestPreview(this.store);
  }

  retry(view) {
    this.drawError[view] = null;
    this.drawn[view] = null;
    this.render();
  }

  clearPlots() {
    for (const view of ["sankey", "donut"]) {
      if (this.drawn[view]) {
        disposeChart(this.frames[view].surface);
        this.drawn[view] = null;
      }
    }
    markNodeOrder(this.frames.sankey.surface, null);
  }

  drawActive() {
    const view = this.tabs.selected();
    const bundle = this.store.get().bundle;
    const figure = view === "donut" ? bundle?.donut : bundle?.figure;
    if (view === "donut" && bundle?.donut_empty_reason === "basis_empty") {
      this.syncOverlay(view); // the server figure is only default axes: show the empty state instead
      disposeChart(this.frames.donut.surface);
      this.drawn.donut = null;
      return;
    }
    if (!hasDrawing(bundle) || !figure || this.drawn[view] === figure) {
      return;
    }
    this.drawn[view] = figure;
    this.drawError[view] = null;
    this.syncOverlay(view);
    const { surface } = this.frames[view];
    const nodeEvents = view === "sankey" ? eventsFor(bundle, { edits: this.edits }) : undefined;
    draw(surface, withoutLegend(figure), { label: chartLabel(view, bundle), nodeEvents }).then(
      () => this.afterDraw(view, null, figure),
      (error) => this.afterDraw(view, error, figure),
    );
  }

  afterDraw(view, error, figure) {
    if (!error) {
      const bundle = this.store.get().bundle;
      if (view === "sankey" && bundle?.figure === figure) {
        markNodeOrder(this.frames.sankey.surface, bundle);
      }
      return;
    }
    if (this.drawn[view] === figure) {
      this.drawn[view] = null;
    }
    this.drawError[view] = error;
    this.syncOverlay(view);
  }

  dispose() {
    for (const off of this.unsubscribe) {
      off();
    }
    this.clearPlots();
    this.nodeTools.dispose();
    this.status.remove();
    this.container.replaceChildren();
  }
}

/**
 * Builds the chart panel into `container`.
 * @param {HTMLElement} container
 * @param {{store: object}} ctx
 * @returns {{dispose: () => void}}
 */
export function createChartPanel(container, ctx) {
  const panel = new ChartPanel(container, ctx);
  return { dispose: () => panel.dispose() };
}
