/**
 * "N other entries have no category": the follow-up of the FIRST category written into data that
 * had no category at all.
 *
 * Typing a category on one entry of such data gives that entry its name; the others stay
 * "Uncategorized" legitimately (their category cell is empty). Saying so, with a way to list them
 * (the entries table's "Only uncategorised" filter), is how the person finds the rest.
 *
 * - `uncategorisedCount(bundle, edit)` -> how many OTHER entries have no category before the edit,
 *   or 0 when the data already has categories, the entries preview is partial, or the edit clears.
 * - `offerHint(toast, count)` shows the toast with the "Show them" action once per call.
 */

/**
 * @param {{entries?: {source: string, target: string, category?: string | null}[], entries_total?: number} | null} bundle
 * @param {{source: string, target: string, category?: string | null}} edit
 * @returns {number}
 */
export function uncategorisedCount(bundle, edit) {
  const entries = bundle?.entries ?? [];
  if (!edit.category || entries.length === 0 || entries.length < (bundle.entries_total ?? 0)) {
    return 0;
  }
  if (entries.some((row) => row.category != null)) {
    return 0;
  }
  return entries.filter((row) => row.source !== edit.source || row.target !== edit.target).length;
}

/** Ticks the entries table's "Only uncategorised" box (a no-op when it is not on the page). */
export function showUncategorised() {
  const box = document.querySelector('[data-testid="entries-uncategorized-only"]');
  if (box instanceof HTMLInputElement && !box.checked) {
    box.click();
  }
}

/**
 * @param {{info: Function}} toast
 * @param {number} count
 * @returns {boolean} whether a toast was shown
 */
export function offerHint(toast, count) {
  if (count <= 0) {
    return false;
  }
  const text = `${count} other ${count === 1 ? "entry has" : "entries have"} no category.`;
  toast.info(text, { action: { label: "Show them", onClick: showUncategorised } });
  return true;
}
