// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Fits a server figure to the page. The page already names the graph (the heading, or the card
 * header on the compare page), so the figure's own title is dropped: it repeats the name and, on a
 * narrow screen, a wrapped legend row runs into it. When nothing else sits above the plot (no
 * legend row, or a donut whose legend is at the side) the top margin shrinks to the plain
 * margin. Everything else, colours, fonts, data and the legend, is the server's, untouched; the
 * server-side exports keep their title.
 */

/** Margin above the plot when there is neither a title nor a legend row. */
const BARE_TOP_MARGIN = 16;

/**
 * @param {{data: object[], layout?: object}} figure
 * @param {{height?: number}} [options]  a new `layout.height` (default: the figure's own)
 * @returns {{data: object[], layout: object}} a copy
 */
export function fitFigure(figure, options = {}) {
  const layout = { ...figure.layout, title: { ...figure.layout?.title, text: "" } };
  if (Number.isFinite(options.height)) {
    layout.height = options.height;
  }
  const bare = !layout.showlegend || figure.data?.[0]?.type === "pie";
  if (bare) {
    layout.margin = { ...layout.margin, t: BARE_TOP_MARGIN };
  }
  return { ...figure, layout };
}

/**
 * Plotly config for the charts of these pages: no mode bar. Its buttons (zoom, pan, reset axes) do
 * nothing useful on a Sankey or a donut. The list of buttons that must never exist (the Plotly
 * Cloud ones among them) lives in one place, `CHART_CONFIG` of core/chart.js.
 */
export const CHART_CONFIG_OVERRIDE = Object.freeze({ displayModeBar: false });
