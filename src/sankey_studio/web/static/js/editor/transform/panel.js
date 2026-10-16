// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Panel "transform": clean-up and categorisation rules applied to the loaded links.
 *
 * Writes `draft.transform.*` with field level patches and never replaces the whole transform, so
 * the per-entry categories the entries table writes (`entry_categories`) are left alone.
 * Fields: smallest link value, top N links, hidden nodes, merged nodes, category rules (ordered,
 * first match wins) with "rules override data", what to do about cycles, and strict/lenient
 * reading. An empty number removes the key, so the server default applies.
 * Test ids: transform-min-value, transform-top-links, transform-hide-nodes, transform-merge-nodes
 * (the table), transform-on-cycle, transform-strict, transform-rules (the table), section-transform.
 */

import { createScope, h } from "../../core/dom.js";
import { formatCount } from "../../core/format.js";
import { checkbox, field, numberInput, selectInput } from "../../core/form.js";
import { plainText } from "../chart/errors.js";
import { registerPanel } from "../panels.js";
import { bindCheck, bindNumber, bindSelect } from "../meta/bind.js";
import { createChipInput } from "../meta/chips.js";
import { createErrorNotice } from "../meta/notice.js";
import { createGroup, createSection } from "../meta/section.js";
import { knownNodeNames } from "../meta/util.js";
import { createMergeEditor, createRulesEditor } from "./editors.js";

const T = ["draft", "transform"];
const HIDE_MAX = 1000;
const NONE = Object.freeze([]);
const reword = plainText; // the server names the loop setting by its field name; the person sees the select's label

function describe(transform) {
  const parts = [];
  if (transform.min_link_value > 0) {
    parts.push(`links of at least ${transform.min_link_value}`);
  }
  if (transform.top_links) {
    parts.push(`top ${transform.top_links} links`);
  }
  const counts = [
    [(transform.hide_nodes ?? []).length, "hidden node"],
    [Object.keys(transform.merge_nodes ?? {}).length, "merge"],
    [(transform.category_rules ?? []).length, "category rule"],
  ];
  for (const [count, name] of counts) {
    if (count > 0) {
      parts.push(formatCount(count, name));
    }
  }
  if (transform.on_cycle === "break") {
    parts.push("cycles broken");
  }
  if (transform.strict) {
    parts.push("strict");
  }
  return parts.length > 0 ? parts.join(", ") : "No changes";
}

function numberField(store, spec) {
  const control = numberInput({ min: spec.min, step: spec.step ?? 1, placeholder: spec.placeholder, "data-testid": spec.testid });
  const f = field({ label: spec.label, control, hint: spec.hint });
  return { f, off: bindNumber(store, f, [...T, spec.key], { min: spec.min, int: spec.int === true }) };
}

function cycleField(store) {
  const control = selectInput({
    options: [
      { value: "error", label: "Stop and show an error" },
      { value: "break", label: "Drop the links that close the loop" },
    ],
    "data-testid": "transform-on-cycle",
  });
  const f = field({ label: "If the links form a loop", control, hint: "A Sankey diagram cannot draw loops (A to B to A)." });
  return { f, off: bindSelect(store, control, [...T, "on_cycle"], { fallback: "error" }) };
}

function checkRow(store, spec) {
  const label = checkbox({ label: spec.label, "data-testid": spec.testid ?? null });
  const off = bindCheck(store, label.querySelector("input"), [...T, spec.key], { fallback: false });
  return { el: h("div", { class: "ed-check" }, label, h("p", { class: "hint" }, spec.hint)), off };
}

function hideField(store, scope) {
  const sync = (items, chips) => {
    if (items.join("\u0000") !== chips.getItems().join("\u0000")) {
      chips.setItems(items);
    }
  };
  const chips = createChipInput({
    label: "Hide these nodes",
    itemName: "node",
    items: store.get().draft.transform.hide_nodes ?? NONE,
    maxItems: HIDE_MAX,
    maxLength: 200,
    placeholder: "Type a name, press Enter",
    hint: "The node and every link to or from it disappear from the chart.",
    suggestions: () => knownNodeNames(store.get().bundle),
    testid: "transform-hide-nodes",
    onChange: (items) => store.patch([...T, "hide_nodes"], items),
  });
  scope.add(store.subscribe((items) => sync(items, chips), { select: (state) => state.draft.transform.hide_nodes ?? NONE }));
  return chips;
}

function buildGroups(ctx, scope, fields) {
  const { store } = ctx;
  const min = numberField(store, { key: "min_link_value", label: "Smallest link to draw", min: 0, placeholder: "0 (draw everything)", hint: "Links below this value are left out.", testid: "transform-min-value" });
  const top = numberField(store, { key: "top_links", label: "Only the largest links", min: 1, int: true, placeholder: "All links", hint: "Keep this many links, the biggest first.", testid: "transform-top-links" });
  const hide = hideField(store, scope);
  const merge = createMergeEditor(store);
  const rules = createRulesEditor(store);
  const cycle = cycleField(store);
  const strict = checkRow(store, { key: "strict", label: "Strict reading", testid: "transform-strict", hint: "Stop at the first bad row. Off: bad rows are skipped and listed as warnings." });
  const override = checkRow(store, { key: "rules_override", label: "Rules win over categories in the data", hint: "Off: a category that comes with the data is kept." });
  for (const off of [min.off, top.off, cycle.off, strict.off, override.off]) {
    scope.add(off);
  }
  scope.add(store.subscribe((value) => merge.sync(value), { select: (state) => state.draft.transform.merge_nodes, immediate: true }));
  scope.add(store.subscribe((value) => rules.sync(value), { select: (state) => state.draft.transform.category_rules, immediate: true }));
  Object.assign(fields, { min_link_value: min.f, top_links: top.f, on_cycle: cycle.f });
  return {
    rules,
    groups: [
      { title: "Filter links", nodes: [min.f.el, top.f.el] },
      { title: "Nodes", wide: true, nodes: [hide.el, h("div", { class: "field" }, h("span", { class: "label" }, "Merge nodes"), h("p", { class: "hint" }, "Two names for the same thing become one node; their links add up."), merge.el)] },
      { title: "Category rules", wide: true, hint: "Optional. Give entries a category by node name instead of one by one.", nodes: [rules.el, override.el] },
      { title: "Problems in the data", nodes: [cycle.f.el, strict.el] },
    ],
  };
}

function resolver(fields, rules) {
  return (path) => {
    const [, key, ...rest] = path;
    return key === "category_rules" ? rules.resolve(rest) : (fields[key] ?? null);
  };
}

function mountTransform(container, ctx) {
  const { store } = ctx;
  const scope = createScope();
  const section = createSection({ id: "transform", title: "Transform", icon: "filter", testid: "section-transform" });
  const fields = {};
  const { groups, rules } = buildGroups(ctx, scope, fields);
  const notice = createErrorNotice({
    store,
    domain: "transform",
    resolve: resolver(fields, rules),
    codes: ["graph_build_error"],
    reword,
    badge: (count) => section.setBadge(count ? formatCount(count, "problem") : "", "error"),
  });
  scope.add(notice.dispose);
  scope.add(store.subscribe((transform) => section.setSummary(describe(transform)), { select: (state) => state.draft.transform, immediate: true }));
  section.body.append(notice.el, ...groups.map(createGroup));
  container.replaceChildren(section.el);
  return () => scope.dispose();
}

registerPanel("transform", mountTransform, { order: 30 });
