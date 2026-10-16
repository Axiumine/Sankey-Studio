// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * A menu button (WAI-ARIA "menu button" pattern) built on core/popover.js.
 *
 * `createMenu({label, icon, testid, panelTestid, items})` returns `{el, button, panel, popover,
 * setBadge(count, label), dispose}`. `el` is a `div.pop` holding the icon button and the menu
 * panel (`role=menu`, one `button[role=menuitem]` per item). `items` is `[{id, label, icon,
 * testid, onSelect}]`.
 *
 * - Enter, Space or a click on the button open the menu with the first item focused; ArrowDown
 *   does too, ArrowUp opens it on the last item.
 * - In the menu ArrowDown / ArrowUp move (and wrap), Home / End jump, Tab closes it and lets the
 *   focus continue, Escape closes it and puts the focus back on the button.
 * - Choosing an item closes the menu with the focus on the button FIRST and only then calls
 *   `onSelect` (in a microtask), so a dialog opened by the item remembers the button as the place
 *   to return to when it closes.
 * - `setBadge(count, label)` marks the button with a problem dot and a longer accessible name
 *   ("Graph settings, 2 problems") while `count` is above zero.
 */

import { formatCount } from "./format.js";
import { createPopover } from "./popover.js";
import { h } from "./dom.js";
import { icon } from "./icons.js";

function buildItem(item, choose) {
  return h(
    "button",
    { type: "button", class: "pop-item", role: "menuitem", tabindex: "-1", "data-testid": item.testid ?? null, on: { click: () => choose(item) } },
    item.icon ? icon(item.icon, { size: 16 }) : null,
    h("span", null, item.label),
  );
}

const EDGE = 8; // px kept free between the panel and the window edge

/** Slides a panel that would leave the window back inside it (the gear can sit far from the left edge). */
function keepInWindow(panel) {
  panel.style.removeProperty("--pop-left");
  const overflow = panel.getBoundingClientRect().right - (document.documentElement.clientWidth - EDGE);
  if (overflow > 0) {
    const left = panel.getBoundingClientRect().left - panel.offsetParent.getBoundingClientRect().left;
    panel.style.setProperty("--pop-left", `${Math.round(left - overflow)}px`);
  }
}

function stepTo(buttons, key) {
  const index = buttons.indexOf(document.activeElement);
  const last = buttons.length - 1;
  const next = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: last }[key];
  buttons[(next + buttons.length) % buttons.length].focus();
}

function buildDom(options, buttons) {
  const button = h(
    "button",
    { type: "button", class: "btn btn-ghost btn-icon", "aria-label": options.label, title: options.label, "data-testid": options.testid },
    icon(options.icon ?? "settings", { size: 16 }),
  );
  const panel = h("div", { class: "pop-panel pop-menu", role: "menu", "aria-label": options.label, hidden: true, "data-testid": options.panelTestid }, buttons);
  return { button, panel, el: h("div", { class: "pop" }, button, panel) };
}

/** The keys of the button (ArrowDown / ArrowUp open) and of the open menu (move, jump, Tab closes). */
function wireKeys({ button, panel, buttons, popover, start }) {
  const onTriggerKey = (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      start.last = event.key === "ArrowUp";
      popover.open();
      start.last = false;
    }
  };
  const onMenuKey = (event) => {
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      stepTo(buttons, event.key);
    } else if (event.key === "Tab") {
      popover.close();
    }
  };
  button.addEventListener("keydown", onTriggerKey);
  panel.addEventListener("keydown", onMenuKey);
  return () => {
    button.removeEventListener("keydown", onTriggerKey);
    panel.removeEventListener("keydown", onMenuKey);
  };
}

function badgeSetter(button, defaultLabel) {
  return (count, label = defaultLabel) => {
    const text = count > 0 ? `${label}, ${formatCount(count, "problem")}` : label;
    button.setAttribute("aria-label", text);
    button.title = text;
    if (count > 0) {
      button.dataset.badge = "error";
    } else {
      delete button.dataset.badge;
    }
  };
}

/**
 * Builds the menu.
 * @param {{label: string, icon?: string, testid: string, panelTestid: string, items: {id: string, label: string, icon?: string, testid?: string, onSelect: () => void}[]}} options
 * @returns {{el: HTMLElement, button: HTMLElement, panel: HTMLElement, popover: ReturnType<typeof createPopover>, setBadge: (count: number, label?: string) => void, dispose: () => void}}
 */
export function createMenu(options) {
  const state = { popover: null };
  const choose = (item) => {
    state.popover.close({ focus: true });
    queueMicrotask(item.onSelect);
  };
  const buttons = options.items.map((item) => buildItem(item, choose));
  const { button, panel, el } = buildDom(options, buttons);
  const start = { last: false };
  const popover = createPopover({
    trigger: button,
    panel,
    haspopup: "menu",
    align: "start",
    onOpen: () => keepInWindow(panel),
    initialFocus: () => (start.last ? buttons[buttons.length - 1] : buttons[0]),
  });
  state.popover = popover;
  const unwire = wireKeys({ button, panel, buttons, popover, start });
  return {
    el,
    button,
    panel,
    popover,
    setBadge: badgeSetter(button, options.label),
    dispose() {
      unwire();
      popover.dispose();
      el.remove();
    },
  };
}
