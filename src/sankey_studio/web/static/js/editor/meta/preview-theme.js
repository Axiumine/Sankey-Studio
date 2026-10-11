/**
 * The theme the editor preview is drawn in.
 *
 * By default it follows the page ("match"); the style panel can pin it to "light" or "dark" to
 * see how the chart will look in the other theme. The choice is not saved with the graph and not
 * remembered: it only exists while the editor is open.
 *
 * `createPreviewTheme()` -> `{mode(), set(mode), resolve(), subscribe(callback)}`; `resolve()`
 * returns "light" or "dark" and is what `createPreview({theme})` calls for every request.
 */

import { effectiveTheme } from "../../core/theme.js";

const MODES = ["match", "light", "dark"];

/**
 * Creates the holder.
 * @returns {{mode: () => string, set: (mode: string) => void, resolve: () => "light"|"dark", subscribe: (callback: (mode: string) => void) => () => void}}
 */
export function createPreviewTheme() {
  let mode = "match";
  const listeners = new Set();
  return {
    mode: () => mode,
    set(next) {
      if (MODES.includes(next) && next !== mode) {
        mode = next;
        listeners.forEach((callback) => callback(mode));
      }
    },
    resolve: () => (mode === "match" ? effectiveTheme() : mode),
    subscribe(callback) {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
  };
}
