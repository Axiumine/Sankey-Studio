/**
 * Panel registry of the editor page, so several agents add panels without editing one file.
 *
 *   // in editor/source-panel.js (one agent)
 *   import { registerPanel } from "./panels.js";
 *   registerPanel("source", (container, ctx) => {
 *     // build DOM into container with core/dom.js; read/write ctx.store; call ctx.api
 *     return () => cleanup();   // the disposer is optional
 *   });
 *
 *   // in pages/editor.js (the composer): import each panel module (importing registers it),
 *   // then mount them all
 *   const mounted = mountAll({ source: el1, preview: el2 }, { boot, api, store, toast });
 *   // later: mounted.dispose();
 *
 * - `registerPanel(name, mount, {order})`: names are unique (a second registration throws, so two
 *   agents cannot silently shadow each other); `order` (default 100) sorts mounting, then
 *   registration order.
 * - `mountAll(containers, ctx)`: containers is `{name: HTMLElement}` (or a Map). Each registered
 *   panel with a container is mounted with `mount(container, ctx)`; the mount may return a
 *   disposer or a promise of one. A panel that throws gets an error state in its container and an
 *   error toast; the others still mount. Returns `{mounted: string[], failed: {name, error}[],
 *   dispose()}`.
 * - `panelNames()`, `unregisterPanel(name)` (tests).
 * ctx is `{boot, api, store, toast}`; panels must treat it as shared and read-mostly.
 */

import { errorState } from "../core/states.js";

const registry = new Map();
const DEFAULT_ORDER = 100;

/**
 * Registers a panel.
 * @param {string} name
 * @param {(container: HTMLElement, ctx: object) => void | (() => void) | Promise<void | (() => void)>} mount
 * @param {{order?: number}} [options]
 */
export function registerPanel(name, mount, options = {}) {
  if (registry.has(name)) {
    throw new Error(`Panel "${name}" is already registered`);
  }
  registry.set(name, { name, mount, order: options.order ?? DEFAULT_ORDER, seq: registry.size });
}

/**
 * Removes a registration.
 * @param {string} name
 */
export function unregisterPanel(name) {
  registry.delete(name);
}

/**
 * Names of the registered panels in mount order.
 * @returns {string[]}
 */
export function panelNames() {
  return sorted().map((panel) => panel.name);
}

function sorted() {
  return Array.from(registry.values()).sort((a, b) => a.order - b.order || a.seq - b.seq);
}

function containerFor(containers, name) {
  return containers instanceof Map ? containers.get(name) : containers[name];
}

function showFailure(panel, container, error, ctx) {
  const message = error instanceof Error ? error.message : String(error);
  container.replaceChildren(errorState({ title: "This part could not be loaded", message, compact: true }));
  ctx.toast?.error(`The "${panel.name}" panel could not start.`);
}

/**
 * Mounts every registered panel that has a container.
 * @param {Record<string, HTMLElement> | Map<string, HTMLElement>} containers
 * @param {{boot: object, api: object, store: object, toast: object}} ctx
 * @returns {{mounted: string[], failed: {name: string, error: unknown}[], dispose: () => void}}
 */
export function mountAll(containers, ctx) {
  const mounted = [];
  const failed = [];
  const disposers = [];
  for (const panel of sorted()) {
    const container = containerFor(containers, panel.name);
    if (!container) {
      continue;
    }
    try {
      const result = Promise.resolve(panel.mount(container, ctx));
      result.catch((error) => {
        failed.push({ name: panel.name, error });
        showFailure(panel, container, error, ctx);
      });
      disposers.push(result);
      mounted.push(panel.name);
    } catch (error) {
      failed.push({ name: panel.name, error });
      showFailure(panel, container, error, ctx);
    }
  }
  return {
    mounted,
    failed,
    dispose() {
      for (const pending of disposers.splice(0).reverse()) {
        pending.then((dispose) => (typeof dispose === "function" ? dispose() : undefined)).catch(() => undefined);
      }
    },
  };
}
