// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The Sankey | Donut switch of the chart panel (WAI-ARIA tabs: roving tabindex, arrow keys, Home
 * and End move AND activate). Unlike core/tabs.js the Donut tab really leaves the DOM while there
 * is no donut (`data-testid="chart-tab-donut"` exists only when the donut is available).
 *
 * `createViewTabs({label, panels, onSelect})` -> `{el, select(id, {focus}), selected(),
 * setDonutAvailable(bool), tabId(id)}`; `panels` is `{sankey: HTMLElement, donut: HTMLElement}`
 * (the tabpanels, wired with ids and `aria-labelledby` here).
 */

import { h, uid } from "../../core/dom.js";
import { icon } from "../../core/icons.js";

const VIEWS = [
  { id: "sankey", label: "Sankey", icon: "bar-chart", testid: "chart-tab-sankey" },
  { id: "donut", label: "Donut", icon: "pie-chart", testid: "chart-tab-donut" },
];

class ViewTabs {
  constructor({ label, panels, onSelect }) {
    this.prefix = uid("chart-view");
    this.panels = panels;
    this.onSelect = onSelect;
    this.current = "sankey";
    this.donutAvailable = false;
    this.buttons = new Map(VIEWS.map((view) => [view.id, this.button(view)]));
    for (const view of VIEWS) {
      const panel = panels[view.id];
      panel.id = `${this.prefix}-panel-${view.id}`;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", this.tabId(view.id));
    }
    this.el = h("div", { class: "tabs out-tabs", role: "tablist", "aria-label": label, on: { keydown: (event) => this.onKey(event) } });
    this.paint();
  }

  tabId(id) {
    return `${this.prefix}-tab-${id}`;
  }

  button(view) {
    return h(
      "button",
      {
        type: "button",
        role: "tab",
        class: "tab out-tab",
        id: this.tabId(view.id),
        "aria-controls": `${this.prefix}-panel-${view.id}`,
        "data-testid": view.testid,
        on: { click: () => this.select(view.id) },
      },
      icon(view.icon, { size: 15 }),
      view.label,
    );
  }

  available() {
    return VIEWS.filter((view) => view.id === "sankey" || this.donutAvailable).map((view) => view.id);
  }

  /** Adds or removes the Donut button without touching the others (focus stays put). */
  syncButtons() {
    const sankey = this.buttons.get("sankey");
    const donut = this.buttons.get("donut");
    if (sankey.parentElement !== this.el) {
      this.el.prepend(sankey);
    }
    if (this.donutAvailable && donut.parentElement !== this.el) {
      this.el.append(donut);
    } else if (!this.donutAvailable && donut.parentElement) {
      donut.remove();
    }
  }

  /** Sets which tab buttons exist, which tab is active (roving tabindex) and which panel shows. */
  paint() {
    this.syncButtons();
    const ids = this.available();
    for (const [id, button] of this.buttons) {
      const active = id === this.current;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      this.panels[id].hidden = !active || !ids.includes(id);
    }
  }

  select(id, { focus = false } = {}) {
    if (!this.available().includes(id)) {
      return;
    }
    const changed = id !== this.current;
    this.current = id;
    this.paint();
    if (focus) {
      this.buttons.get(id).focus();
    }
    if (changed) {
      this.onSelect?.(id);
    }
  }

  setDonutAvailable(available) {
    if (available === this.donutAvailable) {
      return;
    }
    const hadFocus = this.el.contains(document.activeElement);
    this.donutAvailable = available;
    if (!available && this.current === "donut") {
      this.current = "sankey";
      this.paint();
      if (hadFocus) {
        this.buttons.get("sankey").focus();
      }
      this.onSelect?.("sankey");
      return;
    }
    this.paint();
  }

  onKey(event) {
    const ids = this.available();
    const index = ids.indexOf(this.current);
    const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: ids.length - 1 };
    if (!(event.key in moves) || ids.length < 2 || !this.el.contains(document.activeElement)) {
      return;
    }
    event.preventDefault();
    this.select(ids[(moves[event.key] + ids.length) % ids.length], { focus: true });
  }

  selected() {
    return this.current;
  }
}

/**
 * Creates the view switch.
 * @param {{label: string, panels: {sankey: HTMLElement, donut: HTMLElement}, onSelect?: (id: string) => void}} options
 * @returns {ViewTabs}
 */
export function createViewTabs(options) {
  return new ViewTabs(options);
}
