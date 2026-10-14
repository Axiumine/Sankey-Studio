/**
 * The editor page (`/graphs/new` and `/graphs/{id}/edit`): the composer.
 *
 * It owns the page, not the panels. It loads the graph (or starts a blank draft with the default
 * style from the settings), builds the layout with one container per panel and mounts every
 * registered panel through editor/panels.js, connects the store to the live preview
 * (editor/preview.js) and guards against losing unsaved changes. The layout, top to bottom:
 * the chart as a full-width row (`data-panel="chart"`; the gear in its header opens the chart
 * settings popover that holds the `style` and `export` panels), one row with `source` and
 * `transform` side by side (stacked on a phone), the `entries` table at full width and the
 * `savebar`. The name, description and tags live in the details dialog, opened from the gear next
 * to the page title (`editor/title-menu.js`, which also offers "Change data source").
 *
 * A new graph (`/graphs/new`) starts with the two-step wizard (editor/wizard/index.js), drawn into
 * the page before the editor exists; it hands over a seed (name, description, tags, source) that
 * is applied after the unsaved-changes tracking starts, so it is not clean. `#page-root[data-ready]`
 * still means "the editor is mounted". `meta.folder_id` carries the collection a new graph is
 * created in (`boot().folder_id`, from `/graphs/new?folder=<id>`) or the one a saved graph is in.
 *
 * Panel context (`ctx`, second argument of a panel mount): `{boot, api, store, toast, settings,
 * previewTheme, guard, chartTools, switcher, openDetails}`. `settings` is the GET /settings answer
 * or null when it could not be read; `previewTheme` is meta/preview-theme.js; `guard.bypass()`
 * lets the next navigation skip the unsaved-changes prompt; `chartTools` is the tool group at the
 * right of the chart header (`div.out-chart-tools`: the settings gear), where other features
 * append their buttons; `switcher` is the source-kind switcher (editor/source/model.js) and
 * `openDetails({problem})` opens the details dialog (the save bar uses it when the name is empty).
 */

import { announce } from "../core/a11y.js";
import { api, ApiError } from "../core/api.js";
import { boot, lockWriteControls, pageActions, pageRoot, setHeading } from "../core/boot.js";
import { createScope, h, mount } from "../core/dom.js";
import { emptyState, errorState, loadingState } from "../core/states.js";
import { toast } from "../core/toast.js";
import { displayName } from "../library/names.js";
import { createChartSettings } from "../editor/chart-settings.js";
import { openDetailsDialog } from "../editor/details/dialog.js";
import { trackDirty } from "../editor/meta/dirty.js";
import { installLeaveGuard } from "../editor/meta/guard.js";
import { createPreviewTheme } from "../editor/meta/preview-theme.js";
import { ensureEditorStyles } from "../editor/meta/styles.js";
import { ensureOutputStyles } from "../editor/output-panel-kit.js";
import { mountAll } from "../editor/panels.js";
import { createPreview } from "../editor/preview.js";
import { createSwitcher } from "../editor/source/model.js";
import { createStore, initialState } from "../editor/store.js";
import { mountTitleMenu } from "../editor/title-menu.js";
import { applySeed } from "../editor/wizard/seed.js";
import { runWizard } from "../editor/wizard/index.js";
import "../editor/source/panel.js";
import "../editor/transform/panel.js";
import "../editor/style/panel.js";

const SLOTS = ["chart", "source", "transform", "entries", "savebar"];

/** Output panels are written by another module set; a missing one leaves its container empty. */
async function loadOutputPanels() {
  const loaders = [
    () => import("../editor/chart-panel.js"),
    () => import("../editor/entries-panel.js"),
    () => import("../editor/export-panel.js"),
    () => import("../editor/savebar-panel.js"),
  ];
  await Promise.allSettled(loaders.map((load) => load()));
}

async function readSettings() {
  try {
    return await api.get("/settings", { quiet: true });
  } catch {
    return null; // the editor works without them: no default style, no Mongo connection names
  }
}

function slot(name) {
  return h("div", { class: `ed-slot ed-slot-${name}`, "data-panel": name });
}

function buildLayout(chartSettings) {
  const containers = Object.fromEntries(SLOTS.map((name) => [name, slot(name)]));
  Object.assign(containers, chartSettings.containers);
  const el = h(
    "div",
    { class: "ed-root" },
    h("div", { class: "ed-chart-row", id: "editor-output" }, containers.chart, chartSettings.panel),
    h("div", { class: "ed-form-row" }, containers.source, containers.transform),
    containers.entries,
    containers.savebar,
  );
  return { el, containers };
}

/** A blank draft: the default style of the settings, without a title and without a node order (that one belongs to the data of another graph). */
function seedNewDraft(store, settings) {
  const style = settings?.default_style;
  if (style && typeof style === "object") {
    const { title: _title, node_order: _order, ...rest } = style;
    store.patch(["draft", "style"], rest, { clean: true });
  }
  const folder = boot().folder_id;
  if (typeof folder === "string" && folder) {
    store.patch(["meta", "folder_id"], folder, { clean: true });
  }
}

function showLoadError(error, retry) {
  const gone = error instanceof ApiError && error.status === 404;
  if (gone) {
    mount(
      pageRoot(),
      emptyState({
        title: "This graph no longer exists",
        message: "It may have been deleted in another window.",
        icon: "alert",
        actions: [h("a", { class: "btn btn-primary", href: "/" }, "Back to the library")],
      }),
    );
    return;
  }
  const message = error instanceof ApiError ? error.friendly : "The editor could not start.";
  mount(pageRoot(), errorState({ title: "The graph could not be loaded", message, onRetry: retry }));
}

function trackHeading(store) {
  const paint = (_, state) => {
    const { id, name } = state.meta;
    setHeading(id ? `Edit ${displayName(name)}` : name.trim() ? `New graph: ${displayName(name)}` : "New graph");
  };
  return store.subscribe(paint, { select: (state) => `${state.meta.id ?? ""}|${state.meta.name}`, immediate: true });
}

/** Links to the viewer once the graph is saved; keeps the address right after the first save. */
function trackSaved(store) {
  const link = h("a", { class: "btn", href: "/", hidden: true, "data-testid": "view-graph" }, "View graph");
  pageActions().replaceChildren(link);
  return store.subscribe(
    (id) => {
      link.hidden = !id;
      if (id) {
        link.href = `/graphs/${id}`;
        if (window.location.pathname === "/graphs/new") {
          window.history.replaceState(null, "", `/graphs/${id}/edit`);
        }
      }
    },
    { select: (state) => state.meta.id, immediate: true },
  );
}

async function loadDefinition(id) {
  return id ? api.get(`/graphs/${encodeURIComponent(id)}`) : null;
}

function startEditor(definition, settings, seed = null) {
  const store = createStore(initialState());
  if (definition) {
    store.load(definition);
  } else {
    seedNewDraft(store, settings);
  }
  const scope = createScope();
  scope.add(trackDirty(store));
  applySeed(store, seed); // after trackDirty and not clean: the typed wizard input must be protected from an accidental leave
  const chartSettings = createChartSettings({ store });
  const { el, containers } = buildLayout(chartSettings);
  mount(pageRoot(), el);
  const previewTheme = createPreviewTheme();
  const preview = createPreview(store, { theme: () => previewTheme.resolve() });
  const guard = installLeaveGuard(store);
  scope.add(previewTheme.subscribe(() => preview.refresh({ immediate: true })));
  scope.add(trackHeading(store));
  scope.add(trackSaved(store));
  scope.add(guard.dispose);
  scope.add(preview.dispose);
  scope.add(chartSettings.dispose);
  const chartTools = h("div", { class: "out-chart-tools" }, chartSettings.trigger);
  const switcher = createSwitcher(store, settings);
  const openDetails = (options) => openDetailsDialog({ store, api, ...options });
  const ctx = { boot: boot(), api, store, toast, settings, previewTheme, guard, chartTools, switcher, openDetails };
  scope.add(mountTitleMenu({ store, switcher, settings, openDetails }));
  const mounted = mountAll(containers, ctx);
  lockWriteControls(el);
  preview.refresh({ immediate: true });
  scope.add(() => mounted.dispose());
  return { store, ctx, dispose: () => scope.dispose() };
}

async function run() {
  mount(pageRoot(), loadingState({ label: "Loading the editor", lines: 6 }));
  // the output sheet is loaded before the panels mount, so the chart header (with the settings gear) is built in the same tick
  await Promise.all([ensureEditorStyles(), ensureOutputStyles(), loadOutputPanels()]);
  try {
    const [definition, settings] = await Promise.all([loadDefinition(boot().graph?.id ?? null), readSettings()]);
    const seed = definition ? null : await runWizard({ api, settings, toast });
    const editor = startEditor(definition, settings, seed);
    pageRoot().dataset.ready = "true";
    if (seed) {
      document.getElementById("main")?.focus({ preventScroll: true });
      announce(`Editing ${displayName(seed.meta.name)}`);
    }
    return editor;
  } catch (error) {
    showLoadError(error, run);
    return null;
  }
}

run();
