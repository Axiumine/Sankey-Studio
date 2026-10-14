/**
 * The "Change data source" dialog: a guided way to switch the kind of source, opened from the gear
 * next to the title.
 *
 * `openChangeSourceDialog({store, switcher, settings})` lists the five kinds (Text file, Paste,
 * Upload, Manual, MongoDB) as radio buttons, preselects the current one and, when the graph holds
 * edits that only fit its current data (editor/source/overlays.js), says so and offers to keep
 * them (checkbox `change-source-keep`, off by default: they are dropped). "Change source" swaps
 * the draft's source through the same `switcher` the inline tabs use (so Paste -> Manual -> Paste
 * restores the pasted text), opens the Data source section and puts the focus on the inline tab of
 * the new kind, where the person finishes the job (pick the file or collection, paste, type rows).
 * When the chosen kind equals the current one nothing is replaced: the primary button reads "Edit
 * source settings" and only takes the person to that inline tab.
 * The inline tab strip stays the quick path; this dialog is the guided one.
 * Test ids: change-source-dialog, change-source-apply, change-source-keep, dialog-close, and the
 * dynamic change-source-kind-<tab> radios (text|paste|upload|manual|mongo).
 */

import { closePopovers } from "../../core/popover.js";
import { openDialog } from "../../core/dialog.js";
import { h } from "../../core/dom.js";
import { checkbox } from "../../core/form.js";
import { TABS, kindOf, tabOf } from "./model.js";
import { clearOverlays, overlaySummary } from "./overlays.js";

const APPLY = "Change source";
const APPLY_SAME = "Edit source settings";
const NO_MONGO = "No MongoDB connection is configured";
const TEXTS = {
  text: "A CSV, TSV, SankeyMATIC or JSON file from the sources folder.",
  paste: "Text you paste in. It is stored with the graph.",
  upload: "Put a file into the sources folder, then read it from there.",
  manual: "Type the links into a table.",
  mongo: "Read documents from a MongoDB collection.",
};

function radio({ tab, current, disabledReason }) {
  const input = h("input", {
    type: "radio",
    name: "change-source-kind",
    value: tab.id,
    class: "ed-kind-input",
    checked: tab.id === current,
    disabled: Boolean(disabledReason),
    "data-testid": `change-source-kind-${tab.id}`,
  });
  const suffix = tab.id === current ? " (current)" : "";
  const body = h(
    "span",
    { class: "ed-kind-body" },
    h("span", { class: "ed-kind-label" }, `${tab.label}${suffix}`),
    h("span", { class: "ed-kind-text hint" }, disabledReason ?? TEXTS[tab.id]),
  );
  return { input, el: h("label", { class: "ed-kind" }, input, body) };
}

function buildForm({ current, settings, summary }) {
  const noMongo = !(settings?.mongo_connections?.length > 0);
  const radios = TABS.map((tab) => radio({ tab, current, disabledReason: tab.id === "mongo" && noMongo && current !== "mongo" ? NO_MONGO : null }));
  const keep = checkbox({ label: "Keep my graph-only edits", "data-testid": "change-source-keep" });
  const keepNote = h(
    "div",
    { class: "ed-kind-keep stack" },
    h("p", null, `Changing the source drops ${summary.text} unless you keep them.`),
    keep,
  );
  keepNote.hidden = summary.count === 0;
  const el = h(
    "div",
    { class: "stack" },
    h("fieldset", { class: "ed-kinds" }, h("legend", { class: "ed-kinds-legend" }, "Where should the data come from?"), radios.map((item) => item.el)),
    keepNote,
  );
  return {
    el,
    radios,
    keepNote,
    picked: () => radios.find((item) => item.input.checked)?.input.value ?? current,
    keeps: () => keep.querySelector("input").checked,
  };
}

/** Opens the Data source section and puts the focus on the inline tab of `picked`. */
function revealTab(picked) {
  const section = document.querySelector('details[data-section="source"]');
  if (section instanceof HTMLDetailsElement) {
    section.open = true;
  }
  const tab = document.querySelector(`[data-testid="source-tab-${CSS.escape(picked)}"]`);
  if (tab instanceof HTMLElement) {
    if (tab.getAttribute("aria-selected") !== "true") {
      tab.click();
    }
    tab.focus();
  }
}

function commit({ store, switcher, current, choice }) {
  if (kindOf(choice.picked) !== kindOf(current)) {
    store.batch(() => {
      switcher.switchTo(choice.picked);
      if (!choice.keep) {
        clearOverlays(store);
      }
    });
  }
  revealTab(choice.picked);
}

/**
 * Opens the dialog.
 * @param {{store: object, switcher: {switchTo: (tab: string) => boolean}, settings: object | null}} options
 * @returns {{close: (value?: unknown) => void, result: Promise<unknown>}}
 */
export function openChangeSourceDialog({ store, switcher, settings }) {
  closePopovers();
  const current = tabOf(store.get().draft.source);
  const form = buildForm({ current, settings, summary: overlaySummary(store.get()) });
  const dialog = openDialog({
    title: "Change data source",
    testid: "change-source-dialog",
    closeButton: true,
    body: form.el,
    initialFocus: () => form.radios.find((item) => item.input.checked)?.input ?? null,
    actions: [
      { label: "Cancel" },
      {
        label: APPLY_SAME,
        kind: "primary",
        testid: "change-source-apply",
        onClick: (close) => close({ picked: form.picked(), keep: form.keeps() }),
      },
    ],
  });
  const apply = dialog.el.querySelector('[data-testid="change-source-apply"]');
  const paint = () => {
    const same = kindOf(form.picked()) === kindOf(current);
    apply.textContent = same ? APPLY_SAME : APPLY;
    form.keepNote.hidden = same || overlaySummary(store.get()).count === 0;
  };
  form.el.addEventListener("change", paint);
  paint();
  dialog.result.then((choice) => {
    if (choice) {
      commit({ store, switcher, current, choice });
    }
  });
  return { close: dialog.close, result: dialog.result };
}
