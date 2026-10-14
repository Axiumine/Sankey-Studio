/**
 * Inline SVG icons (24x24 stroke set), built with createElementNS: no icon font, no image files.
 *
 * `icon(name, options)` returns an <svg class="icon"> that inherits `currentColor`, so text and
 * data colours are never involved. It is decorative (`aria-hidden`) unless `options.label` is
 * given, which makes it an `img` with that accessible name. Unknown names fall back to "info".
 * `ICON_NAMES` lists what exists.
 */

import { svg } from "./dom.js";

const CIRCLE = (cx, cy, r) => ["circle", { cx, cy, r }];

/** name -> list of path strings and [tag, attrs] shapes */
const SHAPES = {
  plus: ["M12 5v14M5 12h14"],
  x: ["M18 6 6 18M6 6l12 12"],
  check: ["M20 6 9 17l-5-5"],
  "chevron-down": ["m6 9 6 6 6-6"],
  "chevron-up": ["m18 15-6-6-6 6"],
  "chevron-left": ["m15 18-6-6 6-6"],
  "chevron-right": ["m9 18 6-6-6-6"],
  "arrow-up": ["M12 19V5M5 12l7-7 7 7"],
  "arrow-down": ["M12 5v14M19 12l-7 7-7-7"],
  sort: ["m7 15 5 5 5-5M7 9l5-5 5 5"],
  search: [CIRCLE(11, 11, 8), "m21 21-4.3-4.3"],
  filter: ["M22 3H2l8 9.46V19l4 2v-8.54z"],
  trash: ["M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"],
  copy: [["rect", { x: 9, y: 9, width: 13, height: 13, rx: 2 }], "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"],
  edit: ["M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"],
  download: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"],
  upload: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"],
  refresh: ["M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"],
  alert: ["M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z", "M12 9v4M12 17h.01"],
  info: [CIRCLE(12, 12, 10), "M12 16v-4M12 8h.01"],
  "x-circle": [CIRCLE(12, 12, 10), "m15 9-6 6m0-6 6 6"],
  "check-circle": ["M22 11.08V12a10 10 0 1 1-5.93-9.14M22 4 12 14.01l-3-3"],
  lock: [["rect", { x: 3, y: 11, width: 18, height: 11, rx: 2 }], "M7 11V7a5 5 0 0 1 10 0v4"],
  sun: [CIRCLE(12, 12, 4), "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"],
  moon: ["M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"],
  monitor: [["rect", { x: 2, y: 3, width: 20, height: 14, rx: 2 }], "M8 21h8M12 17v4"],
  file: ["M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5ZM14 2v6h6"],
  database: [["ellipse", { cx: 12, cy: 5, rx: 9, ry: 3 }], "M21 12c0 1.66-4 3-9 3s-9-1.34-9-3M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"],
  table: ["M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18"],
  columns: ["M12 3h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7m0-18H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7m0-18v18"],
  "bar-chart": ["M12 20V10M18 20V4M6 20v-4"],
  "pie-chart": ["M21.21 15.89A10 10 0 1 1 8 2.83M22 12A10 10 0 0 0 12 2v10z"],
  settings: [
    CIRCLE(12, 12, 3),
    "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z",
  ],
  sliders: ["M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"],
  "more-horizontal": [CIRCLE(5, 12, 1), CIRCLE(12, 12, 1), CIRCLE(19, 12, 1)],
  folder: ["M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"],
  "folder-plus": ["M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z", "M12 11v6M9 14h6"],
};

/** Every icon name `icon()` knows. */
export const ICON_NAMES = Object.freeze(Object.keys(SHAPES));

function shapeNode(shape) {
  if (typeof shape === "string") {
    return svg("path", { d: shape });
  }
  const [tag, attrs] = shape;
  return svg(tag, attrs);
}

/**
 * Builds an icon.
 * @param {string} name  one of ICON_NAMES
 * @param {{size?: number, label?: string, class?: string}} [options]
 * @returns {SVGElement}
 */
export function icon(name, options = {}) {
  const size = options.size ?? 16;
  const label = options.label;
  return svg(
    "svg",
    {
      class: ["icon", options.class],
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 2,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      focusable: "false",
      role: label ? "img" : null,
      "aria-label": label ?? null,
      "aria-hidden": label ? null : "true",
    },
    (SHAPES[name] ?? SHAPES.info).map(shapeNode),
  );
}
