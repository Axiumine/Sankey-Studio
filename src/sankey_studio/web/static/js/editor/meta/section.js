// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * A collapsible editor section: a native `<details>` (keyboard and screen reader support for
 * free) with a header that shows an icon, a title, a one-line summary of the current settings
 * and an optional status badge, so a closed section still tells what is inside.
 *
 * `createSection({id, title, icon, open, testid})` -> `{el, body, setSummary(text),
 * setBadge(text, kind), setOpen(bool), isOpen()}`. Put the section's content in `body`.
 * The open/closed choice of each section is remembered on this device (guarded localStorage),
 * unless `remember: false` (a section that must start open, e.g. inside a popover, and never
 * stores its state).
 */

import { h } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { stripBidi } from "../../core/text.js";

const STORAGE_KEY = "sankey-studio.editor.sections";

function readState() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeState(id, open) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readState(), [id]: open }));
  } catch {
    // storage is blocked: the section simply starts in its default state next time
  }
}

/**
 * Builds a section.
 * @param {{id: string, title: string, icon?: string, open?: boolean, testid?: string, remember?: boolean}} options
 * @returns {{el: HTMLDetailsElement, body: HTMLElement, setSummary: (text: string) => void, setBadge: (text: string, kind?: string) => void, setOpen: (open: boolean) => void, isOpen: () => boolean}}
 */
export function createSection(options) {
  const remember = options.remember !== false;
  const saved = remember ? readState()[options.id] : undefined;
  const summary = h("span", { class: "ed-section-summary" });
  const badge = h("span", { class: "ed-badge", hidden: true });
  const body = h("div", { class: "ed-section-body" });
  const head = h(
    "summary",
    { class: "ed-section-head", "data-testid": options.testid ?? null },
    h("span", { class: "ed-section-icon" }, icon(options.icon ?? "file", { size: 16 })),
    h("span", { class: "ed-section-text" }, h("span", { class: "ed-section-title" }, options.title), summary),
    badge,
    icon("chevron-down", { size: 16, class: "ed-section-chevron" }),
  );
  const el = h("details", { class: "ed-section", "data-section": options.id, open: typeof saved === "boolean" ? saved : options.open === true }, head, body);
  if (remember) {
    el.addEventListener("toggle", () => writeState(options.id, el.open));
  }
  return {
    el,
    body,
    setSummary(text) {
      summary.textContent = stripBidi(text ?? "");
    },
    setBadge(text, kind = "info") {
      badge.textContent = stripBidi(text ?? "");
      badge.dataset.kind = kind;
      badge.hidden = !text;
    },
    setOpen(open) {
      el.open = open;
    },
    isOpen: () => el.open,
  };
}

/**
 * A titled group of fields inside a section: `<fieldset>` + `<legend>`, an optional hint and a
 * responsive grid (one column on a phone, two when there is room).
 * @param {{title: string, hint?: string, nodes: Node[], wide?: boolean}} group  `wide` stacks the nodes in one column
 * @returns {HTMLFieldSetElement}
 */
export function createGroup(group) {
  return h(
    "fieldset",
    { class: "ed-group" },
    h("legend", null, group.title),
    group.hint ? h("p", { class: "hint ed-group-hint" }, group.hint) : null,
    h("div", { class: ["form-grid", "ed-grid", group.wide ? "is-wide" : null] }, group.nodes),
  );
}
