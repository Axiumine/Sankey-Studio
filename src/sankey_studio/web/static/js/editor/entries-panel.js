/**
 * Registers the "entries" panel (the categorising table). Import this module from the editor
 * composer; it mounts into the container `data-panel="entries"`. Implementation: ./entries/.
 */

import { ensureOutputStyles } from "./output-panel-kit.js";
import { registerPanel } from "./panels.js";
import { createEntriesPanel } from "./entries/panel.js";

registerPanel(
  "entries",
  async (container, ctx) => {
    await ensureOutputStyles();
    const panel = createEntriesPanel(container, ctx);
    return () => panel.dispose();
  },
  { order: 30 },
);
