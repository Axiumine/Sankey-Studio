/**
 * Saving the settings form (the global "Save settings" button) and discarding changes.
 *
 * Save: early checks first (every problem is shown, the first field is focused, no request), then
 * one `PUT /settings` while the form is locked (`store.saving`: the save button and the fields are
 * disabled, so there is never a second request in flight). The body is the draft on top of a fresh
 * `GET /settings` (that supplies what the form does not edit, `default_style`), taken in the queue
 * of core/theme.js so that a theme save never crosses it. `?migrate=true` is
 * sent only when the storage location changes and the box is ticked. On success the draft is
 * rebuilt from the answer, which also empties every connection string input.
 */

import { announce } from "../core/a11y.js";
import { ApiError, api, isAbort } from "../core/api.js";
import { canWrite } from "../core/boot.js";
import { openDialog } from "../core/dialog.js";
import { formatCount } from "../core/format.js";
import { getTheme, queueSettingsWrite } from "../core/theme.js";
import { toast } from "../core/toast.js";
import { mapServerError } from "./errors.js";
import { buildBody, changedElsewhere } from "./model.js";

function successText(result, switched, migrate) {
  const report = result.copy_report;
  if (report) {
    const copied = `${formatCount(report.copied, "graph")} copied to the new location.`;
    return report.unreadable > 0 ? `Settings saved. ${copied} ${formatCount(report.unreadable, "graph")} could not be read.` : `Settings saved. ${copied}`;
  }
  return switched && !migrate ? "Settings saved. Your existing graphs were not copied." : "Settings saved.";
}

async function refreshGraphCount(store) {
  try {
    const page = await api.get("/graphs", { query: { limit: 1 }, quiet: true });
    store.graphCount = typeof page.total === "number" ? page.total : null;
    store.notify();
  } catch {
    // the count only decorates a label: keep the old one
  }
}

function describeFailure(mapped, store) {
  const first = store.visibleErrors()[0]?.message ?? mapped.general[0] ?? "Check the highlighted settings.";
  return `Settings were not saved. ${first}`;
}

function failed(store, summary, error) {
  if (isAbort(error)) {
    return;
  }
  const apiError = error instanceof ApiError ? error : new ApiError({ status: 0, code: "client_error", message: "Unexpected error" });
  // copying reads the old location, so only a switch away from MongoDB can be stuck on it
  const copying = store.storageChanged() && store.draft.migrate && store.settings.storage_backend === "mongo";
  const mapped = mapServerError(apiError, store.draft, { copying });
  store.setServer(mapped);
  toast.error(describeFailure(mapped, store));
  const first = store.visibleErrors()[0];
  if (!first || !store.focus(first.id)) {
    summary.focus();
  }
}

async function askAboutOverwrite() {
  const dialog = openDialog({
    title: "Settings were changed elsewhere",
    body: "Another window or person saved different settings after you opened this page. Saving now replaces their changes with yours.",
    testid: "confirm-dialog",
    actions: [
      { label: "Cancel", value: "cancel", initial: true },
      { label: "Show their settings", value: "reload", testid: "conflict-reload" },
      { label: "Save mine anyway", value: "overwrite", kind: "danger", testid: "settings-conflict-overwrite" },
    ],
  });
  return (await dialog.result) ?? "cancel";
}

/**
 * Saves the draft inside the settings write queue (core/theme.js): it waits for a theme save that
 * is still running, and a theme change made meanwhile is saved after it (from a GET that already
 * holds these values), so neither overwrites the other. Resolves `{outcome: "saved", ...}`,
 * `{outcome: "reloaded"}` or `{outcome: "cancelled"}`.
 */
function send(store) {
  return queueSettingsWrite(() => sendNow(store));
}

async function sendNow(store) {
  const fresh = await api.get("/settings");
  if (changedElsewhere(store.settings, fresh)) {
    const choice = await askAboutOverwrite();
    if (choice !== "overwrite") {
      return { outcome: choice === "reload" ? "reloaded" : "cancelled", fresh };
    }
  }
  const switched = store.storageChanged();
  const migrate = switched && store.draft.migrate;
  const body = buildBody(store.draft, fresh, getTheme());
  const result = await api.put("/settings", body, { query: migrate ? { migrate: true } : undefined });
  return { outcome: "saved", result, switched, migrate: store.draft.migrate };
}

function afterSend(store, sent) {
  if (sent.outcome === "reloaded") {
    store.reset(sent.fresh);
    toast.info("Showing the settings as they are now. Your edits were dropped.");
  } else if (sent.outcome === "cancelled") {
    toast.info("Nothing was saved.");
  } else {
    store.reset(sent.result.settings);
    store.setReport(sent.result.copy_report ?? null);
    toast.success(successText(sent.result, sent.switched, sent.migrate));
    announce("Settings saved.");
    if (sent.switched) {
      refreshGraphCount(store);
    }
  }
}

/**
 * The page's save and discard handlers.
 * @param {import("./store.js").SettingsStore} store
 * @param {{focus: () => void}} summary  the error summary (receives focus when no field can)
 * @returns {{save: () => Promise<void>, discard: () => void}}
 */
export function createActions(store, summary) {
  async function save() {
    if (!canWrite() || store.saving) {
      return;
    }
    store.attempt();
    const [first] = Object.entries(store.clientErrors());
    if (first) {
      toast.error(`Settings were not saved. ${first[1]}`);
      store.focus(first[0]);
      return;
    }
    const returnTo = store.focusedField();
    store.setSaving(true);
    let failure = null;
    try {
      afterSend(store, await send(store));
    } catch (error) {
      failure = error;
    } finally {
      store.setSaving(false);
    }
    if (failure) {
      failed(store, summary, failure); // after the unlock: a disabled field cannot take focus
    } else {
      store.refocus(returnTo); // the fields were locked while saving, which dropped the focus
    }
  }

  function discard() {
    if (store.saving) {
      return;
    }
    store.reset(store.settings);
    announce("Changes discarded.");
  }

  return { save, discard };
}
