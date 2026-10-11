/**
 * Client-side image download: the answer when the server cannot draw an image (422
 * `export_too_large`, 501 no Chrome, 502 failed, 503 busy, 504 too slow).
 *
 * `clientImage({figure, format, filename, size})` draws the server's figure (the one on screen) into
 * an off-screen div of the wanted pixel size and calls Plotly's own image download (core/chart.js
 * `downloadImage`), then removes the div. Colours stay the server's; "transparent" only clears the
 * two background fills, as the person asked.
 * `figureForTheme({onScreen, chart, theme, previewTheme, draft})` -> the figure to draw: the one on
 * screen when it already wears the wanted colours, else the server's figure of the draft in those
 * colours (a plain preview request, no Chrome involved).
 * `fallbackReason(error)` -> the sentence for the `export-fallback-note`.
 * `browserFailure(error)` -> the toast for an image that neither the server nor the browser could draw.
 */

import { api } from "../../core/api.js";
import { disposeChart, downloadImage, draw } from "../../core/chart.js";
import { h } from "../../core/dom.js";

const REASONS = {
  export_too_large: "The server limits images to 36 million pixels",
  export_unavailable: "This server cannot draw images (Chrome is not available)",
  export_failed: "The server could not draw the image",
  export_busy: "The server is busy with another export",
  export_timeout: "The server took too long to draw the image",
};
const BY_STATUS = { 501: REASONS.export_unavailable, 502: REASONS.export_failed, 503: REASONS.export_busy, 504: REASONS.export_timeout };

function serverReason(error) {
  return REASONS[error?.code] ?? BY_STATUS[error?.status] ?? "The server could not draw the image";
}

/**
 * @param {{code?: string, status?: number}} error  why the server could not draw the image
 * @returns {string}
 */
export function fallbackReason(error) {
  return `${serverReason(error)}, so your browser drew it instead. It looks the same, but fonts and spacing can differ slightly.`;
}

/**
 * @param {{code?: string, status?: number}} error  why the server could not draw the image
 * @returns {string}
 */
export function browserFailure(error) {
  return `${serverReason(error)}, and your browser could not draw it either. Try a smaller size or another format.`;
}

/**
 * @param {{onScreen: object, chart: "sankey" | "donut", theme: string, previewTheme: string, draft: object}} options
 * @returns {Promise<object>}
 */
export async function figureForTheme({ onScreen, chart, theme, previewTheme, draft }) {
  if (theme === previewTheme) {
    return onScreen;
  }
  const bundle = await api.post("/preview", draft, { query: { theme }, quiet: true });
  return (chart === "donut" ? bundle.donut : bundle.figure) ?? onScreen;
}

function sizedFigure(figure, size, transparent) {
  const copy = structuredClone(figure);
  copy.layout = { ...copy.layout, width: size.width, height: size.height, autosize: false };
  if (transparent) {
    copy.layout.paper_bgcolor = "transparent";
    copy.layout.plot_bgcolor = "transparent";
  }
  return copy;
}

/**
 * Downloads the figure as an image made by the browser.
 * @param {{figure: object, format: "svg" | "png", filename: string, size: {width: number, height: number, scale: number, transparent: boolean}}} options
 * @returns {Promise<void>}
 */
export async function clientImage({ figure, format, filename, size }) {
  const stage = h("div", { class: "out-stage", "aria-hidden": "true", style: { "--stage-w": `${size.width}px`, "--stage-h": `${size.height}px` } });
  document.body.append(stage);
  try {
    await draw(stage, sizedFigure(figure, size, size.transparent), { config: { staticPlot: true, displayModeBar: false, responsive: false } });
    await downloadImage(stage, { format, filename, width: size.width, height: size.height, scale: size.scale });
  } finally {
    disposeChart(stage);
    stage.remove();
  }
}
