// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The state of the settings form: the last settings the server sent, the draft being edited, which
 * errors are visible and the registry that lets the error summary focus a field.
 *
 * Sections change `store.draft` (or call `addRow` / `removeRow`) and then `store.edit(id)`; every
 * section listens with `subscribe` and redraws its derived parts (select options, hints, error
 * lines). Nothing here touches the DOM except `focus`, and no secret is ever copied out of a row:
 * `snapshot` records only whether a connection string was typed.
 *
 * Error visibility: a client problem is shown for a field once the user left it (`touch`) or after
 * a failed save attempt (`attempt`); a server problem is shown until that field is edited.
 */

import { blankRow, draftFromSettings, snapshot, storageChanged } from "./model.js";
import { validateDraft } from "./validate.js";

const NO_SERVER_ERRORS = () => ({ fields: {}, general: [] });

// A field that loses focus to a mouse press must not show its error before the press is over: the
// error line pushes everything below it down, the button under the pointer moves away between
// mousedown and mouseup, and the click is lost. Stores wait here until the pointer is released.
const waiting = new Set();
let pointerDown = false;
let tracking = false;

function trackPointer() {
  if (tracking) {
    return;
  }
  tracking = true;
  const release = () =>
    setTimeout(() => {
      pointerDown = false;
      for (const store of [...waiting]) {
        waiting.delete(store);
        store.notify();
      }
    }, 0);
  document.addEventListener("pointerdown", () => { pointerDown = true; }, true);
  document.addEventListener("pointerup", release, true);
  document.addEventListener("pointercancel", release, true);
}

/** The observable state of the settings form. */
export class SettingsStore {
  /**
   * @param {Record<string, any>} settings  the first `SettingsOut`
   * @param {number | null} [graphCount]  how many graphs exist (hint of the copy box), if known
   */
  constructor(settings, graphCount = null) {
    this.settings = settings;
    this.draft = draftFromSettings(settings);
    this.baseline = snapshot(this.draft);
    this.touched = new Set();
    this.attempted = false;
    this.server = NO_SERVER_ERRORS();
    this.saving = false;
    this.report = null;
    this.graphCount = graphCount;
    this.listeners = new Set();
    this.controls = new Map();
    this.probeRevision = 0;
    trackPointer();
  }

  /**
   * Calls `listener()` after every change; returns the unsubscribe function.
   * @param {() => void} listener
   * @returns {() => void}
   */
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Tells every listener that something changed. */
  notify() {
    for (const listener of [...this.listeners]) {
      listener();
    }
    this.pruneControls();
  }

  /** Forgets controls of rows that were rebuilt or removed (a save rebuilds every row). */
  pruneControls() {
    for (const [id, element] of this.controls) {
      if (!element.isConnected) {
        this.controls.delete(id);
      }
    }
  }

  /** True when the draft differs from the last saved settings (or a secret was typed). */
  isDirty() {
    return snapshot(this.draft) !== this.baseline;
  }

  /** True when saving would switch the storage location. */
  storageChanged() {
    return storageChanged(this.draft, this.settings);
  }

  /** @returns {Record<string, string>} every client-side problem, by field id */
  clientErrors() {
    return validateDraft(this.draft);
  }

  /**
   * Remembers the control of field `id` so the error summary can focus it.
   * @param {string} id
   * @param {HTMLElement} element
   */
  register(id, element) {
    this.controls.set(id, element);
  }

  /**
   * Focuses the control of field `id`.
   * @param {string} id
   * @param {FocusOptions} [options]
   * @returns {boolean} false when there is no such control on the page
   */
  focus(id, options) {
    const element = this.controls.get(id);
    if (!element?.isConnected) {
      return false;
    }
    element.focus(options);
    return true;
  }

  /**
   * Which field has keyboard focus: `{id}` for a plain field, `{index, part}` for a connection row
   * (rows get new keys after a save, their position stays), or null when focus is elsewhere.
   * @returns {{id?: string, index?: number, part?: string} | null}
   */
  focusedField() {
    for (const [id, element] of this.controls) {
      if (element !== document.activeElement) {
        continue;
      }
      const match = /^row\.([^.]+)\.(\w+)$/.exec(id);
      const index = match ? this.draft.connections.findIndex((row) => row.key === match[1]) : -1;
      return match ? { index, part: match[2] } : { id };
    }
    return null;
  }

  /**
   * Gives focus back to a field found by `focusedField` (without scrolling).
   * @param {{id?: string, index?: number, part?: string} | null} token
   */
  refocus(token) {
    if (!token) {
      return;
    }
    const row = token.index === undefined ? null : this.draft.connections[token.index];
    const id = row ? `row.${row.key}.${token.part}` : token.id;
    if (id) {
      this.focus(id, { preventScroll: true });
    }
  }

  /**
   * The user changed field `id`: its server error and the general failure no longer apply.
   * @param {string} id
   */
  edit(id) {
    if (!id.startsWith("limits.")) {
      this.probeRevision += 1; // a test result no longer describes the form
    }
    const group = id.startsWith("storage.") ? "storage." : id;
    for (const key of Object.keys(this.server.fields)) {
      if (key.startsWith(group)) {
        delete this.server.fields[key];
      }
    }
    this.server.general = [];
    this.notify();
  }

  /**
   * The user left field `id`: from now on its client problem is shown (after the mouse button is
   * released when the field lost focus to a click).
   * @param {string} id
   */
  touch(id) {
    this.touched.add(id);
    if (pointerDown) {
      waiting.add(this);
    } else {
      this.notify();
    }
  }

  /**
   * The message to show under field `id` ("" for none).
   * @param {string} id
   * @returns {string}
   */
  message(id) {
    const server = this.server.fields[id];
    if (server) {
      return server;
    }
    return this.attempted || this.touched.has(id) ? (validateDraft(this.draft)[id] ?? "") : "";
  }

  /** @returns {{id: string, message: string}[]} the errors that are visible now */
  visibleErrors() {
    const ids = new Set([...Object.keys(validateDraft(this.draft)), ...Object.keys(this.server.fields)]);
    return [...ids].map((id) => ({ id, message: this.message(id) })).filter((item) => item.message);
  }

  /** A save was tried: show every client problem. */
  attempt() {
    this.attempted = true;
    this.notify();
  }

  /**
   * @param {{fields: Record<string, string>, general: string[]}} mapped  from errors.js
   */
  setServer(mapped) {
    this.server = mapped;
    this.notify();
  }

  /** @param {boolean} value */
  setSaving(value) {
    this.saving = value;
    this.notify();
  }

  /** @param {{copied: number, skipped: number, unreadable: number, unreadable_ids: string[]} | null} report */
  setReport(report) {
    this.report = report;
    this.notify();
  }

  /** Appends an empty connection row and returns it. */
  addRow() {
    const row = blankRow();
    this.probeRevision += 1;
    this.draft.connections.push(row);
    this.notify();
    return row;
  }

  /**
   * Removes a connection row (and the storage choice that pointed at it).
   * @param {string} key
   * @returns {{row: object, index: number, wasStorage: boolean} | null}
   */
  removeRow(key) {
    const index = this.draft.connections.findIndex((row) => row.key === key);
    if (index < 0) {
      return null;
    }
    this.probeRevision += 1;
    const [row] = this.draft.connections.splice(index, 1);
    const wasStorage = this.draft.storage_connection === key;
    if (wasStorage) {
      this.draft.storage_connection = null;
    }
    this.notify();
    return { row, index, wasStorage };
  }

  /**
   * Puts a removed row back (undo), with its storage choice.
   * @param {{row: object, index: number, wasStorage: boolean}} removed
   */
  restoreRow(removed) {
    const rows = this.draft.connections;
    this.probeRevision += 1;
    rows.splice(Math.min(removed.index, rows.length), 0, removed.row);
    if (removed.wasStorage) {
      this.draft.storage_connection = removed.row.key;
    }
    this.notify();
  }

  /**
   * Adopts a fresh `SettingsOut` after a save: new draft, no typed secrets, no errors.
   * @param {Record<string, any>} settings
   */
  reset(settings) {
    this.settings = settings;
    this.probeRevision += 1;
    this.draft = draftFromSettings(settings, this.draft.migrate);
    this.baseline = snapshot(this.draft);
    this.touched = new Set();
    this.attempted = false;
    this.server = NO_SERVER_ERRORS();
    this.notify();
  }
}
