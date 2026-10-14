/**
 * What the save bar's status line says, as plain data and as DOM nodes.
 *
 * - `describeSave({meta, status, busy, problem, writable})` -> `{state, parts}`: `state` is the
 *   `data-state` of the line (`new|dirty|saved|saving|error|readonly`); a part is one of
 *   `{icon}`, `{spinner}`, `{badge}`, `{detail}` or `{text}`.
 * - `statusNode(part)` builds the node of a part (or null for an empty detail).
 */

import { h } from "../../core/dom.js";
import { formatRelative } from "../../core/format.js";
import { icon } from "../../core/icons.js";

/**
 * Describes the status line for the current state of the store and the bar.
 * @param {{meta: object, status: object, busy: boolean, problem: string, writable: boolean}} input
 * @returns {{state: string, parts: object[]}}
 */
export function describeSave({ meta, status, busy, problem, writable }) {
  const saved = meta.updated_at && !status.dirty ? `Saved ${formatRelative(meta.updated_at)}` : "";
  const detail = { detail: [meta.revision ? `Revision ${meta.revision}` : "", saved].filter(Boolean).join(" · ") };
  if (!writable) {
    return { state: "readonly", parts: [{ icon: "lock" }, { text: "Read-only server: saving is turned off. You can still preview and export." }] };
  }
  if (busy || status.saving) {
    return { state: "saving", parts: [{ spinner: true }, { text: "Saving..." }] };
  }
  if (problem) {
    return { state: "error", parts: [{ icon: "alert" }, { text: problem }] };
  }
  if (!meta.id) {
    return { state: "new", parts: [{ badge: "Not saved yet" }, detail] };
  }
  if (status.dirty) {
    return { state: "dirty", parts: [{ badge: "Unsaved changes" }, detail] };
  }
  return { state: "saved", parts: [{ icon: "check-circle" }, { text: "All changes saved" }, detail] };
}

/**
 * Builds the node of one status part.
 * @param {{icon?: string, spinner?: boolean, badge?: string, detail?: string, text?: string}} part
 * @returns {Node | null}
 */
export function statusNode(part) {
  if (part.icon) {
    return icon(part.icon, { size: 15 });
  }
  if (part.spinner) {
    return h("span", { class: "spinner" });
  }
  if (part.badge) {
    return h("span", { class: "badge", "data-status": "warning" }, part.badge);
  }
  if (part.detail !== undefined) {
    return part.detail ? h("span", { class: "out-save-detail" }, part.detail) : null;
  }
  return h("span", null, part.text);
}
