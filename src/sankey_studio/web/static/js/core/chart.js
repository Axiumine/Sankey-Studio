// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Plotly glue: lazy loading, drawing, resizing, cleanup, client-side image download.
 *
 * - `loadPlotly()` injects `/static/vendor/plotly.min.js` ONCE, only when a page draws a chart
 *   (pages without charts never download the 4.8 MB file). A failed load can be retried.
 * - `draw(div, figure, {theme, label, config})` renders a server figure (`bundle.figure` or
 *   `bundle.donut`) with `Plotly.react`, so drawing the same div again updates it in place.
 *   Colours are the server's: the client never recolours; for the other theme ask the API again
 *   with `?theme=` (see core/theme.js `effectiveTheme`/`onThemeChange`). The figure is cloned
 *   first, Plotly never mutates the caller's data, and every text in the copy loses control and
 *   bidirectional characters (`scrubFigure`): node and category names reach the SVG as labels, and a
 *   bell or a right-to-left override has no place there. `figure.layout.height` becomes the
 *   min-height of the div before drawing, so nothing shifts when the chart appears.
 * - A long `layout.title.text` is wrapped with `<br>` to the width of the container (core/title-wrap.js:
 *   Plotly draws a title on one line and cuts it at the edge) and `layout.margin.t` grows with the
 *   extra lines. Only the copy that is drawn changes; a ResizeObserver wraps it again when the
 *   container changes width.
 * - `withoutLegend(figure)` drops the in-figure legend row of a Sankey, for the pages (viewer, editor) that
 *   list the same entries as HTML under the chart; the compare cards and the server exports keep it.
 * - A ResizeObserver keeps the chart fitted to its container (not only to the window).
 * - `draw(..., {nodeEvents})` (the editor only): `nodeEvents()` returns `{click, move}` and is asked at each
 *   event; see core/chart-nodes.js. The viewer, compare and export pass nothing.
 * - `handle.purge()` (or `disposeChart(div)`) frees Plotly's listeners and the observer: call it
 *   when the page or panel that owns the div goes away.
 * - `createChartFrame({height})` returns `{frame, surface}`: a `.chart-frame` with a reserved
 *   height and the inner div to draw into. Put loading/empty/error states (core/states.js) inside
 *   `frame` while there is no chart.
 * - `downloadImage(div, {format, filename, width, height, scale})` is the client-side PNG/SVG
 *   download (Plotly.downloadImage): the fallback when the server export answers 422
 *   export_too_large or 501/502/503/504 (core/download.js `isClientFallback`).
 */

import { attachNodeEvents, detachNodeEvents } from "./chart-nodes.js";
import { h } from "./dom.js";
import { stripBidi } from "./text.js";
import { titleFit, wrapLayoutTitle } from "./title-wrap.js";

const PLOTLY_URL = "/static/vendor/plotly.min.js";

/**
 * Plotly config: responsive, no Plotly logo, no cloud/lasso tools, no built-in camera button.
 * `sendDataToCloud` is the older name and `sendChartToCloud` ("Share chart...") the one of Plotly 4.x:
 * both upload a chart to Plotly Cloud, and this app never sends data anywhere.
 */
export const CHART_CONFIG = Object.freeze({
  responsive: true,
  displaylogo: false,
  displayModeBar: "hover",
  scrollZoom: false,
  doubleClick: "reset",
  showTips: false,
  modeBarButtonsToRemove: ["select2d", "lasso2d", "sendDataToCloud", "sendChartToCloud", "toImage"],
});

let loading = null;
const handles = new WeakMap();
const titles = new WeakMap(); // div -> {source: {title, margin} as the server sent them, applied: {text, marginTop}}

/**
 * Loads plotly.js once and resolves the global `Plotly`.
 * @returns {Promise<any>}
 */
export function loadPlotly() {
  if (window.Plotly) {
    return Promise.resolve(window.Plotly);
  }
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const script = h("script", { src: PLOTLY_URL, async: true });
      script.addEventListener("load", () => resolve(window.Plotly));
      script.addEventListener("error", () => {
        loading = null;
        script.remove();
        reject(new Error("The chart library could not be loaded"));
      });
      document.head.append(script);
    });
  }
  return loading;
}

/**
 * A chart container with a reserved height.
 * @param {{height?: number}} [options]  pixels (default 480)
 * @returns {{frame: HTMLElement, surface: HTMLElement}}
 */
export function createChartFrame(options = {}) {
  const surface = h("div", { class: "chart-surface" });
  const frame = h("div", { class: "chart-frame", style: { "--chart-h": `${options.height ?? 480}px` } }, surface);
  return { frame, surface };
}

/** Wraps the title of the layout that is about to be drawn and remembers the unwrapped one for resizes. */
function fitTitle(div, layout) {
  const source = { title: layout.title, margin: layout.margin };
  const applied = wrapLayoutTitle(layout, div.clientWidth) ?? titleFit(source, Infinity);
  if (applied) {
    titles.set(div, { source, applied });
  } else {
    titles.delete(div);
  }
}

/** The container changed width: wrap the title again when that changes its lines. */
function refitTitle(div, Plotly) {
  const known = titles.get(div);
  const fit = known && div.clientWidth > 0 ? titleFit(known.source, div.clientWidth) : null;
  if (fit && (fit.text !== known.applied.text || fit.marginTop !== known.applied.marginTop)) {
    known.applied = fit;
    Plotly.relayout(div, { "title.text": fit.text, "margin.t": fit.marginTop });
  }
}

function watchSize(div, Plotly) {
  if (typeof ResizeObserver === "undefined") {
    return null;
  }
  let scheduled = false;
  const observer = new ResizeObserver(() => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        if (div.isConnected && div.data) {
          refitTitle(div, Plotly);
          Plotly.Plots.resize(div);
        }
      });
    }
  });
  observer.observe(div);
  return observer;
}

function makeHandle(div, Plotly) {
  const observer = watchSize(div, Plotly);
  const handle = {
    div,
    update: (figure, options) => draw(div, figure, options),
    resize: () => Plotly.Plots.resize(div),
    purge: () => {
      observer?.disconnect();
      detachNodeEvents(div);
      Plotly.purge(div);
      handles.delete(div);
      titles.delete(div);
    },
    downloadImage: (options) => downloadImage(div, options),
  };
  handles.set(div, handle);
  return handle;
}

/**
 * Removes control and bidirectional characters from every string of a figure, in place (the figure
 * is the copy `draw` made). Numbers, colours and typed arrays are left alone.
 * @param {object} node  an object or array of the figure
 * @returns {object} the same node
 */
export function scrubFigure(node) {
  for (const key of Array.isArray(node) ? node.keys() : Object.keys(node)) {
    const value = node[key];
    if (typeof value === "string") {
      node[key] = stripBidi(value);
    } else if (value !== null && typeof value === "object" && !ArrayBuffer.isView(value)) {
      scrubFigure(value);
    }
  }
  return node;
}

/** `LEGEND_BAND` of render/layout.py: the top margin the server adds for the legend row. */
const LEGEND_BAND = 40;

/**
 * A copy of a server Sankey figure without its legend row, for a page that lists the same entries
 * as HTML under the chart. The legend traces go, the Sankey takes back the band they held and the
 * top margin loses it. A figure with no legend row, or a donut, comes back as it is; the server
 * exports and the compare cards keep the in-figure legend.
 * @param {{data?: object[], layout?: object}} figure
 * @returns {{data?: object[], layout?: object}}
 */
export function withoutLegend(figure) {
  const [sankey] = figure.data ?? [];
  const { layout } = figure;
  if (sankey?.type !== "sankey" || !layout?.showlegend) {
    return figure;
  }
  const domain = { ...sankey.domain, y: [sankey.domain?.y?.[0] ?? 0, 1] };
  const top = Math.max((layout.margin?.t ?? LEGEND_BAND) - LEGEND_BAND, 0);
  return {
    ...figure,
    data: [{ ...sankey, domain }],
    layout: { ...layout, showlegend: false, margin: { ...layout.margin, t: top } },
  };
}

function prepare(div, copy, options) {
  const height = copy.layout?.height;
  if (Number.isFinite(height)) {
    div.style.minHeight = `${height}px`;
  }
  if (options.theme) {
    div.dataset.chartTheme = options.theme;
  }
  if (options.label) {
    div.setAttribute("role", "img");
    div.setAttribute("aria-label", options.label);
  }
}

/**
 * Draws (or redraws) a Plotly figure into `div`.
 *
 * Timing hook for tests and scripts: `div.dataset.ready` is "false" from the moment a draw starts,
 * "true" once `Plotly.react` has resolved and "error" when loading plotly.js or drawing failed.
 * @param {HTMLElement} div
 * @param {{data: object[], layout?: object}} figure
 * @param {{theme?: string, label?: string, config?: object, nodeEvents?: () => object}} [options]
 * @returns {Promise<{div: HTMLElement, update: Function, resize: Function, purge: Function, downloadImage: Function}>}
 */
export async function draw(div, figure, options = {}) {
  div.dataset.ready = "false";
  try {
    const Plotly = await loadPlotly();
    const copy = scrubFigure(structuredClone(figure));
    prepare(div, copy, options);
    copy.layout ??= {};
    fitTitle(div, copy.layout);
    await Plotly.react(div, copy.data, copy.layout, { ...CHART_CONFIG, ...options.config });
    if (options.nodeEvents) {
      attachNodeEvents(div, options.nodeEvents);
    }
    div.dataset.ready = "true";
    return handles.get(div) ?? makeHandle(div, Plotly);
  } catch (error) {
    div.dataset.ready = "error";
    throw error;
  }
}

/**
 * Frees the chart in `div` (no-op when nothing was drawn there).
 * @param {HTMLElement} div
 */
export function disposeChart(div) {
  handles.get(div)?.purge();
}

/**
 * Saves the chart as an image in the browser (no server involved).
 * @param {HTMLElement} div  a div that `draw` rendered
 * @param {{format?: "png"|"svg"|"jpeg"|"webp", filename?: string, width?: number, height?: number, scale?: number}} [options]
 * @returns {Promise<string>} the file name Plotly used
 */
export async function downloadImage(div, options = {}) {
  const Plotly = await loadPlotly();
  const { format = "png", filename = "chart", width, height, scale = 2 } = options;
  return Plotly.downloadImage(div, { format, filename, width, height, scale });
}
