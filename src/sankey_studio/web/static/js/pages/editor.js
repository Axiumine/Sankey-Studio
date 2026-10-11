/**
 * The editor page (`/graphs/new` and `/graphs/{id}/edit`): the composer.
 *
 * It owns the page, not the panels. It loads the graph (or starts a blank draft with the default
 * style from the settings), builds the layout with one container per panel and mounts every
 * registered panel through editor/panels.js, connects the store to the live preview
 * (editor/preview.js) and guards against losing unsaved changes. The layout, top to bottom:
 * two panes side by side (`data-panel="meta|source|transform|style"` on the left, the sticky
 * `chart|export` on the right), the entries table at full width (a wide table does not belong in
 * a pane that scrolls on its own) and the `savebar`.
 *
 * Panel context (`ctx`, second argument of a panel mount): `{boot, api, store, toast, settings,
 * previewTheme, guard}`. `settings` is the GET /settings answer or null when it could not be read;
 * `previewTheme` is meta/preview-theme.js; `guard.bypass()` lets the next navigation skip the
 * unsaved-changes prompt.
 */

import { api, ApiError } from "../core/api.js";
import { boot, lockWriteControls, pageActions, pageRoot, setHeading } from "../core/boot.js";
import { createScope, h, mount } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { emptyState, errorState, loadingState } from "../core/states.js";
import { toast } from "../core/toast.js";
import { displayName } from "../library/names.js";
import { trackDirty } from "../editor/meta/dirty.js";
import { installLeaveGuard } from "../editor/meta/guard.js";
import { createPreviewTheme } from "../editor/meta/preview-theme.js";
import { ensureEditorStyles } from "../editor/meta/styles.js";
import { mountAll } from "../editor/panels.js";
import { createPreview } from "../editor/preview.js";
import { createStore, initialState } from "../editor/store.js";
import "../editor/meta/panel.js";
import "../editor/source/panel.js";
import "../editor/transform/panel.js";
import "../editor/style/panel.js";

const LEFT = ["meta", "source", "transform", "style"];
const RIGHT = ["chart", "export"];
const BELOW = ["entries", "savebar"];

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

function buildLayout() {
  const containers = Object.fromEntries([...LEFT, ...RIGHT, ...BELOW].map((name) => [name, slot(name)]));
  const el = h(
    "div",
    { class: "ed-root" },
    h(
      "div",
      { class: "editor-layout ed-layout" },
      h("div", { class: "editor-pane ed-pane-form" }, LEFT.map((name) => containers[name])),
      h("div", { class: "editor-pane editor-pane-preview ed-pane-output", id: "editor-output" }, RIGHT.map((name) => containers[name])),
    ),
    ...BELOW.map((name) => containers[name]),
  );
  return { el, containers };
}

function seedNewDraft(store, settings) {
  const style = settings?.default_style;
  if (style && typeof style === "object") {
    const { title: _title, ...rest } = style;
    store.patch(["draft", "style"], rest, { clean: true });
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
    setHeading(id ? `Edit ${displayName(name)}` : "New graph");
  };
  return store.subscribe(paint, { select: (state) => `${state.meta.id ?? ""}|${state.meta.name}`, immediate: true });
}

/** Links to the viewer once the graph is saved; keeps the address right after the first save. */
function trackSaved(store) {
  const link = h("a", { class: "btn", href: "/", hidden: true, "data-testid": "view-graph" }, "View graph");
  const jump = h("a", { class: "btn ed-jump", href: "#editor-output" }, icon("bar-chart", { size: 14 }), "Go to the chart");
  pageActions().replaceChildren(jump, link);
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

function startEditor(definition, settings) {
  const store = createStore(initialState());
  if (definition) {
    store.load(definition);
  } else {
    seedNewDraft(store, settings);
  }
  const scope = createScope();
  scope.add(trackDirty(store));
  const { el, containers } = buildLayout();
  mount(pageRoot(), el);
  const previewTheme = createPreviewTheme();
  const preview = createPreview(store, { theme: () => previewTheme.resolve() });
  const guard = installLeaveGuard(store);
  scope.add(previewTheme.subscribe(() => preview.refresh({ immediate: true })));
  scope.add(trackHeading(store));
  scope.add(trackSaved(store));
  scope.add(guard.dispose);
  scope.add(preview.dispose);
  const ctx = { boot: boot(), api, store, toast, settings, previewTheme, guard };
  const mounted = mountAll(containers, ctx);
  lockWriteControls(el);
  preview.refresh({ immediate: true });
  scope.add(() => mounted.dispose());
  return { store, ctx, dispose: () => scope.dispose() };
}

async function run() {
  mount(pageRoot(), loadingState({ label: "Loading the editor", lines: 6 }));
  await Promise.all([ensureEditorStyles(), loadOutputPanels()]);
  try {
    const [definition, settings] = await Promise.all([loadDefinition(boot().graph?.id ?? null), readSettings()]);
    const editor = startEditor(definition, settings);
    pageRoot().dataset.ready = "true";
    return editor;
  } catch (error) {
    showLoadError(error, run);
    return null;
  }
}

run();
