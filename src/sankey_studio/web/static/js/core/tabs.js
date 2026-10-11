/**
 * Accessible tabs (WAI-ARIA tabs pattern): `role=tablist`, roving tabindex, arrow keys / Home /
 * End move AND activate, `aria-controls`/`aria-labelledby` wired, all panels stay in the DOM
 * (hidden) so form state inside them survives switching.
 *
 * `createTabs({label, tabs, selected, onSelect})` -> `{el, select(id), selected(), panel(id),
 * setDisabled(id, bool), setHidden(id, bool)}`.
 * `tabs` is `[{id, label, content: Node, testid, disabled}]`; `selected` is an id (default: the
 * first enabled tab); `onSelect(id)` fires after a change by the user or by `select`; the initial
 * selection is reported in a microtask, so the handler can already use the returned tabs object.
 */

import { h, uid } from "./dom.js";

function buildItem(prefix, tab, onClick) {
  const tabId = `${prefix}-tab-${tab.id}`;
  const panelId = `${prefix}-panel-${tab.id}`;
  const button = h(
    "button",
    { type: "button", role: "tab", class: "tab", id: tabId, "aria-controls": panelId, "aria-selected": "false", tabindex: "-1", disabled: tab.disabled === true, "data-testid": tab.testid ?? null, on: { click: onClick } },
    tab.label,
  );
  const panel = h("div", { role: "tabpanel", class: "tab-panel", id: panelId, "aria-labelledby": tabId, tabindex: "0", hidden: true }, tab.content);
  return { id: tab.id, button, panel };
}

class Tabs {
  constructor(options) {
    const prefix = uid("tabs");
    this.onSelect = options.onSelect;
    this.current = null;
    this.items = options.tabs.map((tab) => buildItem(prefix, tab, () => this.select(tab.id)));
    const list = h(
      "div",
      { class: "tabs", role: "tablist", "aria-label": options.label, on: { keydown: (event) => this.onKey(event) } },
      this.items.map((item) => item.button),
    );
    this.el = h("div", { class: "tabs-block" }, list, this.items.map((item) => item.panel));
    this.building = true;
    this.select(options.selected ?? this.enabled()[0]?.id);
    this.building = false;
  }

  enabled() {
    return this.items.filter((item) => !item.button.disabled && !item.button.hidden);
  }

  find(id) {
    return this.items.find((item) => item.id === id);
  }

  /** Selects a tab (ignored when it is missing or disabled). */
  select(id, focus = false) {
    const target = this.find(id);
    if (!target || target.button.disabled) {
      return;
    }
    const changed = this.current !== id;
    this.current = id;
    for (const item of this.items) {
      const active = item === target;
      item.button.setAttribute("aria-selected", String(active));
      item.button.tabIndex = active ? 0 : -1;
      item.panel.hidden = !active;
    }
    if (focus) {
      target.button.focus();
    }
    if (changed && this.building) {
      // the caller has no handle on the tabs yet: report the initial selection right after build
      queueMicrotask(() => this.onSelect?.(id));
    } else if (changed) {
      this.onSelect?.(id);
    }
  }

  onKey(event) {
    const list = this.enabled();
    const index = list.findIndex((item) => item.button === document.activeElement);
    const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: list.length - 1 };
    if (index < 0 || !(event.key in moves)) {
      return;
    }
    event.preventDefault();
    this.select(list[(moves[event.key] + list.length) % list.length].id, true);
  }

  selected() {
    return this.current;
  }

  panel(id) {
    return this.find(id)?.panel ?? null;
  }

  setDisabled(id, disabled) {
    this.find(id).button.disabled = disabled;
    this.leaveIfUnavailable(id);
  }

  setHidden(id, hidden) {
    this.find(id).button.hidden = hidden;
    this.leaveIfUnavailable(id);
  }

  leaveIfUnavailable(id) {
    const item = this.find(id);
    if (this.current === id && (item.button.disabled || item.button.hidden)) {
      this.select(this.enabled()[0]?.id);
    }
  }
}

/**
 * Creates the tabs; see the file header for the shape of the options and the result.
 * @param {{label: string, tabs: object[], selected?: string, onSelect?: (id: string) => void}} options
 * @returns {Tabs}
 */
export function createTabs(options) {
  return new Tabs(options);
}
