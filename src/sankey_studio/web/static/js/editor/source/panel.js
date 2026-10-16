// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Panel "source": where the data comes from.
 *
 * Five tabs, three source types (see model.js): Text file and Upload (a file in the sources
 * folder), Paste (text stored in the graph), Manual (an editable table of links), MongoDB (a
 * collection of a configured connection). Below the tabs, text sources get "How to read the data"
 * (format, column mapping, preview). Switching tabs keeps what was entered on the other tabs.
 * Server problems (422 details, source_error) are shown at the field they are about, or in a
 * notice at the top of the section, with a badge on the header when the section is closed.
 * A file or MongoDB source also shows the write-back status (./write-back-field.js).
 * Test ids: source-tab-text|paste|upload|manual|mongo, section-source (header), source-write-back.
 */

import { createScope, h } from "../../core/dom.js";
import { formatCount } from "../../core/format.js";
import { registerPanel } from "../panels.js";
import { createErrorNotice } from "../meta/notice.js";
import { createSection } from "../meta/section.js";
import { createReading } from "./reading.js";
import { createSwitcher, kindOf, tabOf } from "./model.js";
import { createTabSet } from "./tab-set.js";
import { createWriteBackField } from "./write-back-field.js";

const CODES = ["source_error", "unsafe_source", "source_not_found", "graph_too_large", "payload_too_large"];
const FORMAT_NAMES = { csv: "CSV", tsv: "TSV", sankeymatic: "SankeyMATIC text", json: "JSON" };

function summarise(state) {
  const source = state.draft.source;
  const stats = state.bundle?.stats;
  const tail = stats ? `${formatCount(stats.links, "link")}, ${formatCount(stats.nodes, "node")}` : "";
  const format = FORMAT_NAMES[source.format];
  let head = "";
  if (source.type === "manual") {
    head = "Typed in";
  } else if (source.type === "mongo") {
    head = source.collection ? `${source.connection} / ${source.collection}` : "Choose a collection";
  } else if (source.origin === "file") {
    head = source.path ?? "Choose a file";
  } else {
    head = /\S/.test(source.content ?? "") ? ["Pasted", format].filter(Boolean).join(" ") : "Paste your data";
  }
  return [head, tail].filter(Boolean).join(", ");
}

function modelLevelField(store, fields) {
  const source = store.get().draft.source;
  if (source.type !== "mongo") {
    return null;
  }
  return source.mode === "aggregate" ? fields.pipeline : fields.filter;
}

function makeResolver(store, fields, manual) {
  return (path) => {
    const [, key, index, sub] = path;
    if (key === undefined) {
      return modelLevelField(store, fields);
    }
    if (key === "links") {
      return typeof index === "number" && sub ? manual.resolve(index, sub) : null;
    }
    return fields[key] ?? null;
  };
}

function mountSource(container, ctx) {
  const { store, api, toast, settings } = ctx;
  const scope = createScope();
  const fields = {};
  const switcher = ctx.switcher ?? createSwitcher(store, settings);
  const section = createSection({ id: "source", title: "Data source", icon: "database", open: true, testid: "section-source" });
  const tabSet = createTabSet({ store, api, toast, settings, switcher, fields });
  const { tabs, parts } = tabSet;
  const { manual } = parts;
  const reading = createReading({ store, api, files: parts.files, fields });
  const writeBack = createWriteBackField({ store });
  const notice = createErrorNotice({
    store,
    domain: "source",
    resolve: makeResolver(store, fields, manual),
    codes: CODES,
    badge: (count) => section.setBadge(count ? formatCount(count, "problem") : "", "error"),
  });
  scope.add(store.subscribe((source) => {
    const wanted = tabOf(source);
    if (kindOf(tabs.selected()) !== kindOf(wanted)) {
      tabs.select(wanted);
    }
  }, { select: (state) => state.draft.source }));
  scope.add(store.subscribe((_, state) => section.setSummary(summarise(state)), { select: (state) => state.draft.source, immediate: true }));
  scope.add(store.subscribe((_, state) => section.setSummary(summarise(state)), { select: (state) => state.bundle?.stats }));
  for (const part of [tabSet, reading, notice, writeBack]) {
    scope.add(part.dispose);
  }
  section.body.append(notice.el, h("div", { class: "ed-source-tabs" }, tabs.el), writeBack.el, reading.el);
  container.replaceChildren(section.el);
  return () => scope.dispose();
}

registerPanel("source", mountSource, { order: 20 });
