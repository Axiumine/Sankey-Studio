// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Panel "style": how the chart looks (title, direction, colours, sizes, number format, donut).
 *
 * Writes `draft.style.*` with field level patches (an empty field removes its key, so the server
 * default applies). The "By category" colour mode is offered only when the preview found at
 * least one category (`bundle.donut_available`), or when the graph already uses it. A "Preview
 * colours" switch draws the editor preview in the light or dark chart theme regardless of the
 * page theme (`ctx.previewTheme`); it never changes the saved graph.
 * Test ids: style-title, style-color-mode, style-orientation, style-height, section-style (header).
 */

import { createScope, h } from "../../core/dom.js";
import { formatCount } from "../../core/format.js";
import { registerPanel } from "../panels.js";
import { createSegmented } from "../meta/bind.js";
import { createErrorNotice } from "../meta/notice.js";
import { createGroup, createSection } from "../meta/section.js";
import { COLOR_MODES, buildStyleFields } from "./fields.js";

const LABELS = Object.fromEntries(COLOR_MODES.map((mode) => [mode.value, mode.label.toLowerCase()]));

function summarise(style) {
  const direction = style.orientation === "v" ? "Vertical" : "Horizontal";
  const colours = LABELS[style.color_mode ?? "node"] ?? "by node";
  return `${direction}, ${colours}, ${style.height ?? 560} px high`;
}

function syncColorOptions(select, state) {
  const mode = state.draft.style.color_mode ?? "node";
  const offered = state.bundle?.donut_available === true || mode === "category";
  const options = COLOR_MODES.filter((item) => item.value !== "category" || offered);
  const same = Array.from(select.options).map((o) => o.value).join() === options.map((o) => o.value).join();
  if (!same) {
    select.replaceChildren(...options.map((item) => h("option", { value: item.value }, item.value === "category" && state.bundle?.donut_available !== true ? `${item.label} (no categories yet)` : item.label)));
  }
  select.value = mode;
}

function themeSwitch(previewTheme) {
  const segmented = createSegmented({
    label: "Preview colours",
    value: previewTheme.mode(),
    options: [
      { value: "match", label: "Match page" },
      { value: "light", label: "Light" },
      { value: "dark", label: "Dark" },
    ],
    onChange: (value) => previewTheme.set(value),
  });
  const group = h("div", { class: "field" }, h("span", { class: "label" }, "Preview colours"), segmented.el, h("p", { class: "hint" }, "Only changes how the chart is drawn while you edit. Pick a theme for downloads in the export options."));
  return { el: group, set: segmented.set };
}

function mountStyle(container, ctx) {
  const { store } = ctx;
  const scope = createScope();
  const section = createSection({ id: "style", title: "Style", icon: "bar-chart", testid: "section-style", open: true, remember: false });
  const built = buildStyleFields(store);
  const notice = createErrorNotice({
    store,
    domain: "style",
    resolve: (path) => built.fields[path.slice(1).join(".")] ?? null,
    badge: (count) => section.setBadge(count ? `${formatCount(count, "problem")}` : "", "error"),
  });
  const theme = themeSwitch(ctx.previewTheme);
  scope.add(built.unbind);
  scope.add(notice.dispose);
  scope.add(store.subscribe((_, state) => syncColorOptions(built.colorMode, state), { select: (state) => `${state.bundle?.donut_available}|${state.draft.style.color_mode}`, immediate: true }));
  scope.add(store.subscribe((style) => section.setSummary(summarise(style)), { select: (state) => state.draft.style, immediate: true }));
  section.body.append(notice.el, ...built.groups.map(createGroup), theme.el);
  container.replaceChildren(section.el);
  return () => scope.dispose();
}

registerPanel("style", mountStyle, { order: 40 });
