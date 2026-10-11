/**
 * The "copy existing graphs" report shown after a storage switch with `migrate=true`
 * (`copy_report` of PUT /settings): how many graphs were copied, skipped (already at the target)
 * and unreadable (could not be read, so not copied), with the ids of the unreadable ones (the
 * server lists at most the first 50).
 */

import { h } from "../core/dom.js";
import { formatCount, formatNumber } from "../core/format.js";
import { icon } from "../core/icons.js";

const LISTED_MAX = 50;

function stat(label, value, extra) {
  return h(
    "div",
    { class: "report-stat", "data-kind": extra ?? null },
    h("dt", null, label),
    h("dd", { class: "nums" }, formatNumber(value, { maximumFractionDigits: 0 })),
  );
}

function unreadableBlock(report) {
  if (report.unreadable === 0) {
    return null;
  }
  const hidden = report.unreadable - report.unreadable_ids.length;
  return h(
    "div",
    { class: "report-unreadable" },
    h("p", null, `${formatCount(report.unreadable, "graph")} could not be read, so ${report.unreadable === 1 ? "it was" : "they were"} not copied. They are still in the old location.`),
    report.unreadable_ids.length > 0
      ? h("ul", { class: "report-ids list-reset text-mono", "data-testid": "settings-copy-unreadable" }, report.unreadable_ids.slice(0, LISTED_MAX).map((id) => h("li", null, id)))
      : null,
    hidden > 0 ? h("p", { class: "hint report-more" }, `And ${formatNumber(hidden, { maximumFractionDigits: 0 })} more that are not listed.`) : null,
  );
}

/**
 * Builds the report notice.
 * @param {{copied: number, skipped: number, unreadable: number, unreadable_ids: string[]}} report
 * @param {() => void} onDismiss
 * @returns {HTMLElement}
 */
export function copyReportNotice(report, onDismiss) {
  const clean = report.unreadable === 0;
  const title = clean ? "Your graphs were copied to the new location." : "Some graphs could not be copied.";
  return h(
    "div",
    {
      class: "notice settings-report",
      "data-kind": clean ? "success" : "warning",
      role: "status",
      tabindex: "-1",
      "data-testid": "settings-copy-report",
      "data-copied": report.copied,
      "data-skipped": report.skipped,
      "data-unreadable": report.unreadable,
    },
    icon(clean ? "check-circle" : "alert", { size: 18 }),
    h(
      "div",
      { class: "notice-body stack stack-sm" },
      h("p", { class: "text-strong" }, title),
      h(
        "dl",
        { class: "report-stats" },
        stat("Copied", report.copied),
        stat("Already there, skipped", report.skipped),
        stat("Could not be read", report.unreadable),
      ),
      unreadableBlock(report),
    ),
    h("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": "Dismiss the copy report", on: { click: onDismiss } }, icon("x")),
  );
}
