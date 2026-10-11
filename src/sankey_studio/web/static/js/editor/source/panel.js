/**
 * Panel "source": where the data comes from.
 *
 * Five tabs, three source types (see model.js): Text file and Upload (a file in the sources
 * folder), Paste (text stored in the graph), Manual (an editable table of links), MongoDB (a
 * collection of a configured connection). Below the tabs, text sources get "How to read the data"
 * (format, column mapping, preview). Switching tabs keeps what was entered on the other tabs.
 * Server problems (422 details, source_error) are shown at the field they are about, or in a
 * notice at the top of the section, with a badge on the header when the section is closed.
 * Test ids: source-tab-text|paste|upload|manual|mongo, section-source (header).
 */

import { createScope, h } from "../../core/dom.js";
import { formatCount } from "../../core/format.js";
import { createTabs } from "../../core/tabs.js";
import { registerPanel } from "../panels.js";
import { createErrorNotice } from "../meta/notice.js";
import { createSection } from "../meta/section.js";
import { createFiles } from "./files.js";
import { createManualTab } from "./tab-manual.js";
import { createMongoData } from "./mongo-data.js";
import { createMongoTab } from "./tab-mongo.js";
import { createPasteTab } from "./tab-paste.js";
import { createReading } from "./reading.js";
import { createTextTab } from "./tab-text.js";
import { createUploadTab } from "./tab-upload.js";
import { TABS, createSwitcher, kindOf, tabOf } from "./model.js";

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
  const files = createFiles(api);
  const switcher = createSwitcher(store, settings);
  const section = createSection({ id: "source", title: "Data source", icon: "database", open: true, testid: "section-source" });
  let tabs = null;
  const goto = (id) => tabs.select(id, true);
  const text = createTextTab({ store, files, fields, goto });
  const paste = createPasteTab({ store, toast, fields });
  const upload = createUploadTab({ store, files, settings, toast });
  const manual = createManualTab({ store, fields, toast });
  const mongo = createMongoTab({ store, api, data: createMongoData(api), settings, fields });
  const reading = createReading({ store, api, files, fields });
  const contents = { text: text.el, paste: paste.el, upload: upload.el, manual: manual.el, mongo: mongo.el };
  tabs = createTabs({
    label: "Where the data comes from",
    selected: tabOf(store.get().draft.source),
    tabs: TABS.map((tab) => ({ ...tab, content: contents[tab.id] })),
    onSelect: (id) => {
      switcher.switchTo(id);
      if (id === "mongo") {
        mongo.onShow();
      }
    },
  });
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
  for (const part of [text, paste, upload, manual, mongo, reading, notice]) {
    scope.add(part.dispose);
  }
  section.body.append(notice.el, h("div", { class: "ed-source-tabs" }, tabs.el), reading.el);
  container.replaceChildren(section.el);
  return () => scope.dispose();
}

registerPanel("source", mountSource, { order: 20 });
