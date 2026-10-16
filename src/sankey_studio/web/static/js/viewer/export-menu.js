// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The export menu of the viewer's chart card: a download icon at the right of the tab row that
 * opens a non-modal popover (core/popover.js) holding the export panel (export.js).
 *
 * The popover stays open while a download runs, so the fallback note and the size line stay in
 * view; it closes on Escape (focus goes back to the icon), on a press outside and when focus
 * leaves it. Opening it closes any other popover.
 *
 * `createExportMenu({graph, charts, display})` takes the options of `createExportPanel` and returns
 * `{el, setActive(kind), setHeights(heights), dispose()}`; `el` goes into the chart tools
 * (`Charts.addTool`).
 *
 * Test ids: export-menu-button, export-menu-panel (and the `export-*` ones of export.js).
 */

import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { createPopover } from "../core/popover.js";
import { createExportPanel } from "./export.js";

const LABEL = "Export settings";

class ExportMenu {
  /** @param {{graph: {id: string, name: string}, charts: object, display?: () => object}} options */
  constructor(options) {
    this.exporter = createExportPanel(options);
    this.trigger = h(
      "button",
      { type: "button", class: "btn btn-ghost btn-icon export-button", "aria-label": LABEL, title: LABEL, "data-testid": "export-menu-button" },
      icon("download", { size: 16 }),
    );
    this.panel = h(
      "div",
      { class: "pop-panel export-menu-panel", role: "dialog", "aria-labelledby": "export-title", hidden: true, "data-testid": "export-menu-panel" },
      this.exporter.el,
    );
    this.el = h("div", { class: "pop export-menu" }, this.trigger, this.panel);
    this.popover = createPopover({ trigger: this.trigger, panel: this.panel, initialFocus: () => this.panel }); // the panel, not Width: no on-screen keyboard on touch
  }

  /** Tells the panel which chart is showing. */
  setActive(kind) {
    this.exporter.setActive(kind);
  }

  /** Remembers the drawn heights (the default image heights). */
  setHeights(heights) {
    this.exporter.setHeights(heights);
  }

  dispose() {
    this.popover.dispose();
  }
}

/**
 * Builds the icon button and its popover.
 * @param {{graph: {id: string, name: string}, charts: object, display?: () => object}} options
 * @returns {ExportMenu}
 */
export function createExportMenu(options) {
  return new ExportMenu(options);
}
