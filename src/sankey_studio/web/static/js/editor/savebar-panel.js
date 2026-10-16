// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Registers the "savebar" panel (sticky Save / Save as copy, revision, dirty indicator, conflict
 * banner). Import this module from the editor composer; it mounts into the container
 * `data-panel="savebar"`: it draws a `.savebar` inside the container and sets the container to
 * `display: contents` so `position: sticky` works against the page. Implementation: ./savebar/.
 */

import { ensureOutputStyles } from "./output-panel-kit.js";
import { registerPanel } from "./panels.js";
import { createSaveBar } from "./savebar/panel.js";

registerPanel(
  "savebar",
  async (container, ctx) => {
    await ensureOutputStyles();
    const bar = createSaveBar(container, ctx);
    return () => bar.dispose();
  },
  { order: 90 },
);
