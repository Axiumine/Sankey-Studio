// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Registers the "export" panel (SVG/PNG of both charts, HTML/JSON/CSV). Import this module from the
 * editor composer; it mounts into the container `data-panel="export"`. Implementation: ./export/.
 */

import { ensureOutputStyles } from "./output-panel-kit.js";
import { registerPanel } from "./panels.js";
import { createExportPanel } from "./export/panel.js";

registerPanel(
  "export",
  async (container, ctx) => {
    await ensureOutputStyles();
    const panel = createExportPanel(container, ctx);
    return () => panel.dispose();
  },
  { order: 40 },
);
