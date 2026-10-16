// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Registers the "chart" panel (Sankey | Donut views, legend, category table, stats, warnings).
 * Import this module from the editor composer; it mounts into the container `data-panel="chart"`.
 * The implementation lives in ./chart/.
 */

import { ensureOutputStyles } from "./output-panel-kit.js";
import { registerPanel } from "./panels.js";
import { createChartPanel } from "./chart/panel.js";

registerPanel(
  "chart",
  async (container, ctx) => {
    await ensureOutputStyles();
    const panel = createChartPanel(container, ctx);
    return () => panel.dispose();
  },
  { order: 20 },
);
