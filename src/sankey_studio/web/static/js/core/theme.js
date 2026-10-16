// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Theme: "system" | "light" | "dark", stored in `<html data-theme>`.
 *
 * - The server renders `<html data-theme>` from the stored settings (also `boot().theme`), and
 *   theme-init.js (classic script in <head>) lets a cached device choice override it before the
 *   first paint when the server is read-only; this module owns changes after that. A fresh
 *   browser therefore starts in the saved theme with no request and no flash.
 * - `setTheme(theme)` applies it, caches it in localStorage (guarded: storage can be missing)
 *   and, when the server allows writes, saves it with PUT /api/v1/settings. That route replaces
 *   the whole settings document, so the save is read-modify-write: GET /settings, change `theme`,
 *   PUT the document back (connection URIs are omitted by the API, the stored secrets are kept).
 *   In read-only remote mode nothing is sent: the choice stays on this device (cache only).
 * - Every read-modify-write of that document goes through ONE queue, so two of them never
 *   interleave and overwrite each other's values. `queueSettingsWrite(job)` lets another writer
 *   (the settings page's Save) take a place in it: a theme change made while that job runs is
 *   applied at once and saved right after it, from a fresh GET that already holds its values.
 *   `themeSaved()` resolves when everything queued so far has finished.
 * - `adoptTheme(theme)` applies a theme that came FROM the server (settings page after a save)
 *   without writing it back.
 * - Charts: ask the API for `?theme=effectiveTheme()` and redraw on `onThemeChange(cb)`; the
 *   figure carries its own colours, the client never recolours.
 * - Event: `sankey:theme` on document, detail `{theme, effective}`. `sankey:system-theme`
 *   (detail `{system}`) fires whenever the device's own light/dark setting changes, whatever theme
 *   is chosen (a "System" card can then say what the device does now).
 */

import { api } from "./api.js";
import { canWrite } from "./boot.js";

export const THEMES = Object.freeze(["system", "light", "dark"]);
const STORAGE_KEY = "sankey-studio.theme";
const EVENT = "sankey:theme";
const SYSTEM_EVENT = "sankey:system-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function writeCache(theme) {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // storage is blocked or full: the theme then lasts for this page only
  }
}

/**
 * The chosen theme.
 * @returns {"system"|"light"|"dark"}
 */
export function getTheme() {
  const value = document.documentElement.dataset.theme;
  return THEMES.includes(value) ? value : "system";
}

/**
 * What the device itself asks for ("light" or "dark"), whatever theme is chosen.
 * @returns {"light"|"dark"}
 */
export function systemTheme() {
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

/**
 * The theme actually shown: "light" or "dark" ("system" resolves through the OS setting).
 * @returns {"light"|"dark"}
 */
export function effectiveTheme() {
  const theme = getTheme();
  return theme === "system" ? systemTheme() : theme;
}

function notify() {
  const detail = { theme: getTheme(), effective: effectiveTheme() };
  document.dispatchEvent(new CustomEvent(EVENT, { detail }));
}

/**
 * Sets `<html data-theme>` and tells listeners; nothing is stored or sent.
 * @param {string} theme
 */
export function applyTheme(theme) {
  document.documentElement.dataset.theme = THEMES.includes(theme) ? theme : "system";
  notify();
}

/**
 * Applies and caches a theme that the server reported (no write back).
 * @param {string} theme
 */
export function adoptTheme(theme) {
  applyTheme(theme);
  writeCache(getTheme());
}

/**
 * Calls `callback({theme, effective})` whenever the shown theme can have changed (switch or OS
 * setting while on "system"). Returns the unsubscribe function.
 * @param {(detail: {theme: string, effective: string}) => void} callback
 * @returns {() => void}
 */
export function onThemeChange(callback) {
  const handler = (event) => callback(event.detail);
  document.addEventListener(EVENT, handler);
  return () => document.removeEventListener(EVENT, handler);
}

/**
 * Calls `callback({system})` when the device's light/dark setting changes (also while another
 * theme is chosen, when nothing on the page changes colour). Returns the unsubscribe function.
 * @param {(detail: {system: "light"|"dark"}) => void} callback
 * @returns {() => void}
 */
export function onSystemThemeChange(callback) {
  const handler = (event) => callback(event.detail);
  document.addEventListener(SYSTEM_EVENT, handler);
  return () => document.removeEventListener(SYSTEM_EVENT, handler);
}

let queue = Promise.resolve();

const settle = () => undefined;

/**
 * Runs `job` after every settings write queued before it, and holds the theme saves (and other
 * jobs) queued after it until it has finished. Use it for any read-modify-write of the settings
 * document so that it cannot cross a theme save.
 * @template T
 * @param {() => Promise<T>} job
 * @returns {Promise<T>} what `job` returns (or rejects with)
 */
export function queueSettingsWrite(job) {
  const result = queue.then(job);
  queue = result.then(settle, settle);
  return result;
}

/**
 * Resolves when every settings write queued so far (theme saves and `queueSettingsWrite` jobs)
 * has finished.
 * @returns {Promise<void>}
 */
export function themeSaved() {
  return queue;
}

async function saveToServer(theme) {
  const current = await api.get("/settings", { quiet: true });
  if (current.theme !== theme) {
    await api.put("/settings", { ...current, theme }, { quiet: true });
  }
}

/**
 * Chooses a theme: applies it at once, caches it, and saves it on the server when writes are
 * allowed. Never throws; the result says where the choice was kept.
 * @param {"system"|"light"|"dark"} theme
 * @returns {Promise<{persisted: boolean, error?: Error}>}
 */
export function setTheme(theme) {
  adoptTheme(theme);
  if (!canWrite()) {
    return Promise.resolve({ persisted: false });
  }
  const chosen = getTheme();
  const run = async () => {
    try {
      await saveToServer(chosen);
      return { persisted: true };
    } catch (error) {
      return { persisted: false, error };
    }
  };
  return queueSettingsWrite(run);
}

window.matchMedia(DARK_QUERY).addEventListener("change", () => {
  document.dispatchEvent(new CustomEvent(SYSTEM_EVENT, { detail: { system: systemTheme() } }));
  if (getTheme() === "system") {
    notify();
  }
});
