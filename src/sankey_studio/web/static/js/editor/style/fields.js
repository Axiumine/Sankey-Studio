// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The style fields of the editor, described as data and built from the descriptions.
 *
 * Every field maps 1:1 to `StyleSpec` (models/style.py). Limits shown in the hints are the model's
 * limits; the server stays the judge, its 422 details are placed on the field by the panel.
 * Defaults mirror the model: an empty field removes the key, so the default applies.
 */

import { h } from "../../core/dom.js";
import { checkbox, field, selectInput, textInput } from "../../core/form.js";
import { bindCheck, bindSelect, bindText, cutNotice } from "../meta/bind.js";
import { createSlider } from "../meta/slider.js";

const STYLE = ["draft", "style"];
const DONUT = ["draft", "style", "donut"];

export const COLOR_MODES = [
  { value: "node", label: "By node" },
  { value: "layer", label: "By column" },
  { value: "mono", label: "One colour" },
  { value: "category", label: "By category" },
];

const ORIENTATIONS = [{ value: "h", label: "Horizontal (left to right)" }, { value: "v", label: "Vertical (top to bottom)" }];
const ARRANGEMENTS = [
  { value: "snap", label: "Snap to neighbours" },
  { value: "perpendicular", label: "Across the flow only" },
  { value: "freeform", label: "Anywhere" },
  { value: "fixed", label: "Not draggable" },
];
const BASES = [
  { value: "all", label: "Every entry" },
  { value: "initial", label: "First step only" },
  { value: "terminal", label: "Last step only" },
];
const SORTS = [{ value: "value", label: "Largest first" }, { value: "name", label: "By name" }];
const FORMATS = [
  [",.2~f", "1,234.5 (up to 2 decimals)"],
  [",.0f", "1,235 (no decimals)"],
  [",.1f", "1,234.5 (one decimal)"],
  [",.2f", "1,234.50 (two decimals)"],
  [".2s", "1.2k (short)"],
  ["$,.2f", "$1,234.50"],
  [".1%", "12.3% (as a percentage)"],
];

const NUMBERS = [
  { key: "height", label: "Chart height", unit: "px", min: 240, max: 2400, step: 10, int: true, fallback: 560, testid: "style-height", hint: "240 to 2400." },
  { key: "node_pad", label: "Space between nodes", unit: "px", min: 0, max: 100, int: true, fallback: 16, hint: "0 to 100." },
  { key: "node_thickness", label: "Node width", unit: "px", min: 1, max: 100, int: true, fallback: 18, hint: "1 to 100." },
  { key: "link_opacity", label: "Link opacity", min: 0.05, max: 1, step: 0.05, fallback: 0.4, hint: "0.05 (faint) to 1 (solid)." },
  { key: "font_size", label: "Font size", unit: "px", min: 8, max: 32, int: true, fallback: 13, hint: "8 to 32." },
];

const DONUT_NUMBERS = [
  { key: "max_slices", label: "Slices before “Other”", min: 2, max: 8, int: true, fallback: 6, hint: "Smaller categories fold into one Other slice. 2 to 8." },
  { key: "hole", label: "Hole size", min: 0.3, max: 0.85, step: 0.01, fallback: 0.58, hint: "0.3 (thick ring) to 0.85 (thin ring)." },
];

function selectField(store, spec) {
  const control = selectInput({ options: spec.options, "data-testid": spec.testid ?? null });
  const f = field({ label: spec.label, control, hint: spec.hint });
  const off = bindSelect(store, control, spec.path, { fallback: spec.fallback });
  return { f, off };
}

function checkField(store, spec) {
  const input = checkbox({ label: spec.label, "data-testid": spec.testid ?? null });
  const off = bindCheck(store, input.querySelector("input"), spec.path, { fallback: spec.fallback });
  return { el: input, off };
}

function formatField(store) {
  const list = h("datalist", { id: "style-format-options" }, FORMATS.map(([value, label]) => h("option", { value, label })));
  const control = textInput({ placeholder: ",.2~f", list: list.id });
  const f = field({ label: "Number format", control, hint: "How values are written, in d3-format (for example ,.0f or $,.2f). Pick a preset or type your own." });
  f.el.append(list);
  return { f, off: bindText(store, control, [...STYLE, "value_format"], { removeEmpty: true, max: 24, onWrite: cutNotice(f, 24) }) };
}

function suffixField(store) {
  const control = textInput({ placeholder: "e.g. kWh or EUR" });
  const f = field({ label: "Unit after values (optional)", control, hint: "Added after every value, up to 20 characters." });
  return { f, off: bindText(store, control, [...STYLE, "value_suffix"], { removeEmpty: true, max: 20, onWrite: cutNotice(f, 20) }) };
}

function titleField(store) {
  const control = textInput({ placeholder: "No title", "data-testid": "style-title" });
  const f = field({ label: "Chart title", control, hint: "Shown above the chart and used to name exported files." });
  const useName = h("button", { type: "button", class: "btn", on: { click: () => store.patch([...STYLE, "title"], store.get().meta.name.trim()) } }, "Use graph name");
  const group = h("div", { class: "input-group ed-title-group" });
  control.replaceWith(group);
  group.append(control, useName);
  const sync = () => {
    const name = store.get().meta.name.trim();
    useName.disabled = name === "" || name === control.value;
  };
  const offs = [bindText(store, control, [...STYLE, "title"], { removeEmpty: true, max: 200, onWrite: cutNotice(f, 200) }), store.subscribe(sync, { select: (s) => [s.meta.name, s.draft.style.title].join("\u0000"), immediate: true })];
  return { f, off: () => offs.forEach((off) => off()) };
}

/**
 * "One colour" picker: shown only in the One colour mode. Empty (the reset button) removes
 * `mono_color`, so the palette colour of the theme applies. The picker starts on the palette colour
 * (`--chart-mono`, the token that mirrors it) while nothing is saved.
 */
function monoColorField(store) {
  const control = h("input", { type: "color", class: "ed-color-input", "data-testid": "style-mono-color", "aria-label": "One colour" });
  const reset = h("button", { type: "button", class: "btn", "data-testid": "style-mono-reset", on: { click: () => store.remove([...STYLE, "mono_color"]) } }, "Use palette colour");
  const f = field({ label: "One colour", control, hint: "The colour of every node and link in One colour mode." });
  f.el.append(reset);
  control.addEventListener("change", (event) => store.patch([...STYLE, "mono_color"], event.target.value));
  const sync = () => {
    const style = store.get().draft.style;
    const saved = style.mono_color ?? null;
    f.el.hidden = (style.color_mode ?? "node") !== "mono";
    control.value = saved ?? getComputedStyle(document.documentElement).getPropertyValue("--chart-mono").trim();
    reset.disabled = saved === null;
  };
  const off = store.subscribe(sync, { select: (state) => `${state.draft.style.color_mode}|${state.draft.style.mono_color}`, immediate: true });
  return { f, off };
}

/**
 * Builds every style field and binds it to the store.
 * @param {object} store
 * @returns {{fields: Record<string, {setError: (message?: string) => void}>, groups: {title: string, hint?: string, nodes: HTMLElement[]}[], colorMode: HTMLSelectElement, unbind: () => void}}
 */
export function buildStyleFields(store) {
  const offs = [];
  const fields = {};
  const take = ({ f, off }, key) => {
    fields[key] = f;
    offs.push(off);
    return f.el;
  };
  const title = take(titleField(store), "title");
  const orientation = take(selectField(store, { label: "Direction", options: ORIENTATIONS, path: [...STYLE, "orientation"], fallback: "h", testid: "style-orientation" }), "orientation");
  const colorMode = selectField(store, { label: "Colour nodes and links", options: COLOR_MODES, path: [...STYLE, "color_mode"], fallback: "node", testid: "style-color-mode", hint: "Colours come from the app palette, so the chart stays readable in light and dark." });
  const colorEl = take(colorMode, "color_mode");
  const monoEl = take(monoColorField(store), "mono_color");
  const arrangement = take(selectField(store, { label: "Dragging nodes", options: ARRANGEMENTS, path: [...STYLE, "arrangement"], fallback: "snap", hint: "How nodes move when you drag them in the chart." }), "arrangement");
  const sliders = NUMBERS.map((spec) => {
    const slider = createSlider({ ...spec, store, path: [...STYLE, spec.key] });
    fields[spec.key] = slider.field;
    offs.push(slider.unbind);
    return slider.field.el;
  });
  const format = take(formatField(store), "value_format");
  const suffix = take(suffixField(store), "value_suffix");
  const labels = checkField(store, { label: "Show values under the node names", path: [...STYLE, "show_values_in_labels"], fallback: false });
  offs.push(labels.off);
  const donut = buildDonut(store, fields, offs);
  const [height, ...looks] = sliders;
  return {
    fields,
    colorMode: colorMode.f.control,
    groups: [
      { title: "Chart", wide: true, nodes: [title, orientation, height] },
      { title: "Colours", nodes: [colorEl, monoEl] },
      { title: "Values", nodes: [format, suffix, labels.el] },
      { title: "Nodes and links", nodes: [...looks, arrangement] },
      { title: "Donut chart", hint: "The donut appears once at least one entry has a category.", nodes: donut },
    ],
    unbind: () => offs.forEach((off) => off()),
  };
}

function buildDonut(store, fields, offs) {
  const nodes = [];
  const basis = selectField(store, {
    label: "Count which entries",
    options: BASES,
    path: [...DONUT, "basis"],
    fallback: "all",
    hint: "First and last step ignore entries in the middle of a flow, so categories set there do not count.",
  });
  fields["donut.basis"] = basis.f;
  offs.push(basis.off);
  nodes.push(basis.f.el);
  for (const spec of DONUT_NUMBERS) {
    const slider = createSlider({ ...spec, store, path: [...DONUT, spec.key] });
    fields[`donut.${spec.key}`] = slider.field;
    offs.push(slider.unbind);
    nodes.push(slider.field.el);
  }
  const sort = selectField(store, { label: "Slice order", options: SORTS, path: [...DONUT, "sort"], fallback: "value" });
  fields["donut.sort"] = sort.f;
  offs.push(sort.off);
  const percent = checkField(store, { label: "Show percentages", path: [...DONUT, "show_percent"], fallback: true });
  const value = checkField(store, { label: "Show values", path: [...DONUT, "show_value"], fallback: false });
  const total = checkField(store, { label: "Show the total in the middle", path: [...DONUT, "show_total"], fallback: true });
  offs.push(percent.off, value.off, total.off);
  nodes.push(sort.f.el, h("div", { class: "stack stack-sm" }, percent.el, value.el, total.el));
  return nodes;
}
