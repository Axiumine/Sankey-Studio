/**
 * The export options (size, scale, transparency, file colours) remembered between visits, in the
 * browser's own storage only (never sent anywhere). Blocked or broken storage just means the options
 * start from their defaults next time.
 *
 * `loadPrefs()` -> the saved object (`{}` when there is none or it is unreadable);
 * `savePrefs(prefs)` stores it.
 */

const STORAGE_KEY = "sankey-studio.export";

/**
 * @returns {Record<string, unknown>}
 */
export function loadPrefs() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * @param {Record<string, unknown>} prefs
 */
export function savePrefs(prefs) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // blocked storage: the sizes simply reset next time
  }
}
