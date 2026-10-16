// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Source kinds of the editor and how switching between them keeps the user's work.
 *
 * There are five tabs but three source types (`SourceSpec`, models/sources.py):
 *   text   "Text file" and "Upload"  -> {type: "text", origin: "file", path}
 *   paste  "Paste"                    -> {type: "text", origin: "inline", content}
 *   manual "Manual"                   -> {type: "manual", links: [...]}
 *   mongo  "MongoDB"                  -> {type: "mongo", connection, collection, ...}
 * The store holds only the active source. Switching a tab remembers the source that is left in a
 * small in-memory cache and restores the cached one (or a fresh default) for the tab entered, so a
 * pasted table or a manual list is not lost by looking at another tab. Reading options (format,
 * header, columns, delimiter) carry over between the text kinds.
 */

export const TABS = [
  { id: "text", label: "Text file", testid: "source-tab-text" },
  { id: "paste", label: "Paste", testid: "source-tab-paste" },
  { id: "upload", label: "Upload", testid: "source-tab-upload" },
  { id: "manual", label: "Manual", testid: "source-tab-manual" },
  { id: "mongo", label: "MongoDB", testid: "source-tab-mongo" },
];

/** Reading options that make sense for every text source. */
export const READING_KEYS = ["format", "delimiter", "has_header", "source_column", "target_column", "value_column", "category_column", "detect_category", "encoding"];

/**
 * The tab a source belongs to (a loaded graph opens on it).
 * @param {{type?: string, origin?: string}} source
 * @returns {"text"|"paste"|"manual"|"mongo"}
 */
export function tabOf(source) {
  if (source?.type === "manual" || source?.type === "mongo") {
    return source.type;
  }
  return source?.origin === "file" ? "text" : "paste";
}

/** The cache key of a tab: "text" and "upload" are two views of the same file source. */
export function kindOf(tab) {
  return tab === "upload" ? "text" : tab;
}

/**
 * A fresh source for a kind.
 * @param {"text"|"paste"|"manual"|"mongo"} kind
 * @param {{mongo_connections?: {name: string, default_database?: string | null}[]} | null} settings
 * @returns {object}
 */
export function defaultSource(kind, settings) {
  if (kind === "manual") {
    return { type: "manual", links: [] };
  }
  if (kind === "mongo") {
    const first = settings?.mongo_connections?.[0];
    return { type: "mongo", connection: first?.name ?? "", collection: "", mode: "find", filter: {} };
  }
  if (kind === "text") {
    return { type: "text", origin: "file", format: "auto", path: null };
  }
  return { type: "text", origin: "inline", format: "auto", content: "" };
}

/**
 * The connection to pre-select once the settings are read again ("Check again" on the Mongo tab):
 * the only one, and only for a Mongo draft that has no connection or one that is gone. A draft
 * with a connection that is still configured is never changed, and with several connections the
 * choice stays with the person.
 * @param {{type?: string, connection?: string} | null | undefined} source
 * @param {{name: string}[]} connections
 * @returns {string | null} the name to select, or null to leave the draft alone
 */
export function connectionToPreselect(source, connections) {
  if (source?.type !== "mongo" || connections.length !== 1) {
    return null;
  }
  const current = source.connection;
  return current && connections.some((item) => item.name === current) ? null : connections[0].name;
}

function carryReading(from, to) {
  if (from?.type !== "text" || to.type !== "text") {
    return to;
  }
  const kept = Object.fromEntries(READING_KEYS.filter((key) => key in from).map((key) => [key, from[key]]));
  return { ...to, ...kept };
}

/**
 * Creates the tab switcher for a store.
 * @param {{get: () => {draft: {source: object}}, patch: Function}} store
 * @param {object | null} settings
 * @returns {{switchTo: (tab: string) => boolean, remember: () => void, current: () => string}}
 */
export function createSwitcher(store, settings) {
  const cache = new Map();
  const currentKind = () => kindOf(tabOf(store.get().draft.source));
  return {
    current: () => tabOf(store.get().draft.source),
    remember() {
      cache.set(currentKind(), store.get().draft.source);
    },
    /** Replaces the draft's source with the one for `tab`; false when nothing changed. */
    switchTo(tab) {
      const from = store.get().draft.source;
      const kind = kindOf(tab);
      if (kind === currentKind()) {
        return false;
      }
      cache.set(currentKind(), from);
      const next = carryReading(from, cache.get(kind) ?? defaultSource(kind, settings));
      store.patch(["draft", "source"], next);
      return true;
    },
  };
}
