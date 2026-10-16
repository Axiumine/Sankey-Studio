// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The "File colours" choice of the export panel: which colour theme the downloaded files wear.
 *
 * The preview follows the page or the Style panel's "Preview colours"; a download is a different
 * thing (a slide, a document), so it has its own choice and starts on Light, like the viewer's
 * export. "Same as the preview" follows whatever the chart on screen is drawn in.
 *
 * - `createThemeField(value, onChange)` -> `{el, select, hint}` (the hint sits under the whole row); test id `export-theme` (the same name the
 *   viewer's export uses for the same control).
 * - `normalizeTheme(value)` -> a known choice or the default (saved preferences may be stale).
 * - `resolveTheme(choice, previewTheme)` -> `"light" | "dark"` for the `theme=` query parameter.
 */

import { h, uid } from "../../core/dom.js";

export const DEFAULT_THEME = "light";
const CHOICES = Object.freeze([
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "match", label: "Same as the preview" },
]);

/**
 * @param {unknown} value
 * @returns {"light" | "dark" | "match"}
 */
export function normalizeTheme(value) {
  return CHOICES.some((choice) => choice.value === value) ? /** @type {"light" | "dark" | "match"} */ (value) : DEFAULT_THEME;
}

/**
 * @param {"light" | "dark" | "match"} choice
 * @param {() => "light" | "dark"} previewTheme  the colours the chart on screen is drawn in
 * @returns {"light" | "dark"}
 */
export function resolveTheme(choice, previewTheme) {
  return choice === "match" ? previewTheme() : choice;
}

/**
 * @param {string} value  the starting choice
 * @param {() => void} onChange
 * @returns {{el: HTMLElement, select: HTMLSelectElement, hint: HTMLElement}}
 */
export function createThemeField(value, onChange) {
  const id = uid("export-theme");
  const select = h(
    "select",
    { id, class: "select", "aria-describedby": `${id}-hint`, "data-testid": "export-theme", on: { change: onChange } },
    CHOICES.map((choice) => h("option", { value: choice.value }, choice.label)),
  );
  select.value = normalizeTheme(value);
  const hint = h("p", { class: "hint", id: `${id}-hint` }, "Colours of the downloaded files. The preview keeps its own.");
  return { el: h("div", { class: "field out-theme-field" }, h("label", { for: id }, "File colours"), select), select, hint };
}
