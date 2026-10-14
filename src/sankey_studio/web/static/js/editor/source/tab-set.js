/**
 * The five source tabs wired to a store, without the section chrome, the reading options or the
 * error notice. `mountSource` (the editor's Data source section) and the new-graph wizard (step 2)
 * share this one implementation.
 *
 * `createTabSet({store, api, toast, settings, switcher, fields, onChange})` -> `{tabs, parts, fields, dispose}`.
 * `tabs` is the core/tabs.js instance (test ids source-tab-text|paste|upload|manual|mongo),
 * `parts` the tab builders by id plus the shared `files` cache, `fields` the object the tabs
 * register their form fields in (the caller may pass its own). `onChange(id)` is called after the
 * selected tab was settled (also for Text file <-> Upload, which does not touch the draft).
 *
 * Choosing another kind of source while the graph holds graph-only edits (overlays.js) asks
 * whether to keep them first: "keep" and "drop" switch (drop clears them in the same batch), a
 * cancelled question puts the previous tab back and leaves the draft alone. Text file and Upload
 * are one kind, so moving between them asks nothing.
 */

import { createTabs } from "../../core/tabs.js";
import { createFiles } from "./files.js";
import { createMongoData } from "./mongo-data.js";
import { TABS, kindOf, tabOf } from "./model.js";
import { askKeepOverlays, clearOverlays, overlaySummary } from "./overlays.js";
import { createManualTab } from "./tab-manual.js";
import { createMongoTab } from "./tab-mongo.js";
import { createPasteTab } from "./tab-paste.js";
import { createTextTab } from "./tab-text.js";
import { createUploadTab } from "./tab-upload.js";

function buildParts({ store, api, toast, settings, fields, goto }) {
  const files = createFiles(api);
  return {
    files,
    text: createTextTab({ store, files, fields, goto }),
    paste: createPasteTab({ store, toast, fields }),
    upload: createUploadTab({ store, files, settings, toast }),
    manual: createManualTab({ store, fields, toast }),
    mongo: createMongoTab({ store, api, data: createMongoData(api), settings, fields }),
  };
}

/**
 * Builds the tabs.
 * @param {{store: object, api: object, toast: object, settings: object | null, switcher: {switchTo: (tab: string) => boolean, current: () => string}, fields?: Record<string, object>, onChange?: (id: string) => void}} options
 * @returns {{tabs: ReturnType<typeof createTabs>, parts: Record<string, any>, fields: Record<string, object>, dispose: () => void}}
 */
export function createTabSet({ store, api, toast, settings, switcher, fields = {}, onChange = null }) {
  let tabs = null;
  let confirmed = tabOf(store.get().draft.source);
  const parts = buildParts({ store, api, toast, settings, fields, goto: (id) => tabs.select(id, true) });

  const apply = (id, keep) => {
    store.batch(() => {
      switcher.switchTo(id);
      if (!keep) {
        clearOverlays(store);
      }
    });
    confirmed = id;
    if (id === "mongo") {
      parts.mongo.onShow();
    }
    onChange?.(id);
  };

  const onSelect = async (id) => {
    const changesKind = kindOf(id) !== kindOf(switcher.current());
    if (!changesKind || overlaySummary(store.get()).count === 0) {
      apply(id, true);
      return;
    }
    const answer = await askKeepOverlays(store);
    if (answer === "cancel") {
      tabs.select(confirmed);
      return;
    }
    apply(id, answer === "keep");
  };

  tabs = createTabs({
    label: "Where the data comes from",
    selected: confirmed,
    tabs: TABS.map((tab) => ({ ...tab, content: parts[tab.id].el })),
    onSelect,
  });
  return {
    tabs,
    parts,
    fields,
    dispose() {
      for (const part of Object.values(parts)) {
        part.dispose?.();
      }
    },
  };
}
