// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Chart settings: a gear in the chart header that opens a non-modal popover with two tabs,
 * "Style" and "Export". The popover does not dim or block the page, so the chart keeps redrawing
 * while the person edits the style.
 *
 * `createChartSettings({store})` returns `{trigger, panel, containers: {style, export}, open(tab),
 * close(), dispose()}`. The editor page puts `trigger` into the chart header tools
 * (`ctx.chartTools`), `panel` into the chart row and mounts the style and export panels into the
 * two containers (they are `data-panel` slots like every other panel).
 *
 * The gear shows an error badge (`data-badge="error"`, a longer accessible name) while the server
 * rejected a `style.*` value; opening the popover then selects the Style tab.
 * Test ids: chart-settings-button, chart-settings-panel, chart-settings-close,
 * chart-settings-tab-style, chart-settings-tab-export.
 */

import { createPopover } from "../core/popover.js";
import { formatCount } from "../core/format.js";
import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { createTabs } from "../core/tabs.js";
import { parseDetails } from "./meta/errors.js";

const LABEL = "Chart settings";

/** How many validation problems of the last failed preview or save are about `style.*`. */
function styleProblemCount(error) {
  return parseDetails(error).filter((entry) => entry.path[0] === "style").length;
}

function slotFor(name) {
  return h("div", { class: `ed-slot ed-slot-${name}`, "data-panel": name });
}

function buildTrigger() {
  return h(
    "button",
    { type: "button", class: "btn btn-ghost btn-icon", "aria-label": LABEL, title: LABEL, "data-testid": "chart-settings-button" },
    icon("settings", { size: 16 }),
  );
}

function buildPanel(tabs) {
  const close = h(
    "button",
    { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": "Close chart settings", title: "Close chart settings", "data-testid": "chart-settings-close" },
    icon("x", { size: 16 }),
  );
  const panel = h(
    "div",
    { class: "pop-panel ed-settings", id: "ed-chart-settings", role: "dialog", "aria-label": LABEL, hidden: true, "data-testid": "chart-settings-panel" },
    h("div", { class: "ed-settings-head" }, h("h2", { class: "ed-settings-title" }, LABEL), close),
    tabs.el,
  );
  return { panel, close };
}

/** Marks the gear while the server rejected a `style.*` value; `onCount` gets the number of problems. */
function bindProblemBadge({ store, trigger, onCount }) {
  return store.subscribe(
    (count) => {
      onCount(count);
      const label = count > 0 ? `${LABEL}, ${formatCount(count, "problem")}` : LABEL;
      trigger.setAttribute("aria-label", label);
      trigger.title = label;
      if (count > 0) {
        trigger.dataset.badge = "error";
      } else {
        delete trigger.dataset.badge;
      }
    },
    { select: (state) => styleProblemCount(state.status.error), immediate: true },
  );
}

/**
 * Builds the gear and the popover.
 * @param {{store: object}} options
 * @returns {{trigger: HTMLElement, panel: HTMLElement, containers: {style: HTMLElement, export: HTMLElement}, open: (tab?: string) => void, close: () => void, dispose: () => void}}
 */
export function createChartSettings({ store }) {
  const trigger = buildTrigger();
  const containers = { style: slotFor("style"), export: slotFor("export") };
  const tabs = createTabs({
    label: LABEL,
    selected: "style",
    tabs: [
      { id: "style", label: "Style", content: containers.style, testid: "chart-settings-tab-style" },
      { id: "export", label: "Export", content: containers.export, testid: "chart-settings-tab-export" },
    ],
  });
  const { panel, close } = buildPanel(tabs);
  let problems = 0;
  let requested = null;
  const popover = createPopover({
    trigger,
    panel,
    onOpen: () => {
      tabs.select(requested ?? (problems > 0 ? "style" : tabs.selected()));
      requested = null;
    },
    initialFocus: () => panel.querySelector('[role="tab"][aria-selected="true"]'),
  });
  close.addEventListener("click", () => popover.close({ focus: true }));
  const unsubscribe = bindProblemBadge({ store, trigger, onCount: (count) => { problems = count; } });
  return {
    trigger,
    panel,
    containers,
    open(tab = "style") {
      requested = tab;
      popover.open();
      requested = null;
    },
    close: () => popover.close(),
    dispose() {
      unsubscribe();
      popover.dispose();
    },
  };
}
