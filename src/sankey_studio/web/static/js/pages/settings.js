/**
 * The settings page (`/settings`): appearance, storage, MongoDB connections, limits and the
 * read-only facts of the running server, with one global "Save settings" bar.
 *
 * Data: nothing but the shell's boot block is embedded, so the page loads `GET /api/v1/settings`
 * (and the graph count for a hint) and draws a skeleton meanwhile. The sections live in
 * `js/settings/`; this module only assembles them and wires the draft store to them:
 *
 *   store (draft, errors, saving)  ->  every section's `sync()` on each change
 *
 * Behaviour in short: edits are held in a draft and saved together; the save bar shows the state
 * and disables itself while a save runs; leaving the page with unsaved changes asks first; on a
 * read-only server every field is disabled; connection strings are write-only (never shown,
 * never stored by the page).
 */

import { ApiError, api } from "../core/api.js";
import { canWrite, pageRoot } from "../core/boot.js";
import { h, mount } from "../core/dom.js";
import { errorState, loadingState } from "../core/states.js";
import { buildAppearance } from "../settings/appearance.js";
import { buildConnections } from "../settings/connections.js";
import { buildEnvironment } from "../settings/environment.js";
import { installLeaveGuard } from "../settings/guard.js";
import { buildLimits } from "../settings/limits.js";
import { createActions } from "../settings/save.js";
import { buildSavebar } from "../settings/savebar.js";
import { SettingsStore } from "../settings/store.js";
import { buildStorage } from "../settings/storage.js";
import { buildSummary } from "../settings/summary.js";

const TEXT_INPUT_TYPES = new Set(["text", "number", "password"]);

async function graphCount() {
  try {
    const page = await api.get("/graphs", { query: { limit: 1 }, quiet: true });
    return typeof page.total === "number" ? page.total : null;
  } catch {
    return null;
  }
}

function saveOnEnter(root, save) {
  root.addEventListener("keydown", (event) => {
    const target = event.target;
    const typing = target instanceof HTMLInputElement && TEXT_INPUT_TYPES.has(target.type);
    if (event.key === "Enter" && typing && !event.isComposing) {
      event.preventDefault();
      save();
    }
  });
}

function assemble(settings, count) {
  const store = new SettingsStore(settings, count);
  const summary = buildSummary(store);
  const form = [buildStorage(store), buildConnections(store), buildLimits(store)];
  const actions = createActions(store, summary);
  const savebar = buildSavebar(store, actions);
  const fieldset = h(
    "fieldset",
    { class: "settings-fieldset" },
    h("legend", { class: "visually-hidden" }, "Editable settings"),
    form.map((part) => part.el),
  );
  const environment = buildEnvironment(settings.bootstrap);
  const el = h("div", { class: "settings", "data-readonly": String(!canWrite()) }, summary.el, buildAppearance(store).el, fieldset, environment.el, savebar.el);
  const sync = () => {
    fieldset.disabled = store.saving || !canWrite();
    el.setAttribute("aria-busy", String(store.saving));
    for (const part of [...form, summary, savebar]) {
      part.sync();
    }
  };
  store.subscribe(sync);
  sync();
  saveOnEnter(el, actions.save);
  installLeaveGuard({ isDirty: () => store.isDirty(), subscribe: (listener) => store.subscribe(listener) });
  return el;
}

async function start() {
  const root = pageRoot();
  mount(root, h("div", { class: "settings-loading" }, loadingState({ label: "Loading settings", lines: 8 })));
  try {
    const [settings, count] = await Promise.all([api.get("/settings"), graphCount()]);
    mount(root, assemble(settings, count));
  } catch (error) {
    const message = error instanceof ApiError ? error.friendly : "The settings could not be shown.";
    mount(root, errorState({ title: "The settings could not be loaded", message, onRetry: start }));
  }
}

start();
