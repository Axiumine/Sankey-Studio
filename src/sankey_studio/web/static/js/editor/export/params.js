// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Image-size inputs of the export panel, as pure functions.
 *
 * The server clamps width and height to 200..4000 pixels before the scale and refuses images over
 * 36,000,000 pixels after it (422 `export_too_large`, which the UI answers with a browser-side
 * download). The inputs are checked here so a typo gets a plain sentence instead of a surprise.
 *
 * - `readSize({width, height, scale})` takes the raw input texts and returns
 *   `{ok, values: {width, height | null, scale}, errors: {width?, height?, scale?}}`.
 * - `pixelSize(values, figureHeight)` -> `{width, height, total}` of the output image.
 * - `imageQuery(values, transparent)` -> the query parameters for the export route.
 */

export const SIZE_MIN = 200;
export const SIZE_MAX = 4000;
export const SCALE_MIN = 0.5;
export const SCALE_MAX = 4;
export const PIXEL_CAP = 36_000_000;
export const DEFAULTS = Object.freeze({ width: "1200", height: "", scale: "2" });

function whole(text, label, required) {
  const raw = String(text ?? "").trim();
  if (raw === "" && !required) {
    return { value: null };
  }
  const value = Number(raw);
  if (raw === "" || !Number.isInteger(value) || value < SIZE_MIN || value > SIZE_MAX) {
    return { error: `${label} must be a whole number from ${SIZE_MIN} to ${SIZE_MAX}.` };
  }
  return { value };
}

function factor(text) {
  const raw = String(text ?? "").trim();
  const value = Number(raw);
  if (raw === "" || !Number.isFinite(value) || value < SCALE_MIN || value > SCALE_MAX) {
    return { error: `Scale must be a number from ${SCALE_MIN} to ${SCALE_MAX}.` };
  }
  return { value };
}

/**
 * Checks the raw input texts.
 * @param {{width: string, height: string, scale: string}} raw
 * @returns {{ok: boolean, values: {width: number, height: number | null, scale: number}, errors: Record<string, string>}}
 */
export function readSize(raw) {
  const parts = { width: whole(raw.width, "Width", true), height: whole(raw.height, "Height", false), scale: factor(raw.scale) };
  const errors = Object.fromEntries(Object.entries(parts).filter(([, part]) => part.error).map(([key, part]) => [key, part.error]));
  const values = { width: parts.width.value ?? Number(DEFAULTS.width), height: parts.height.value ?? null, scale: parts.scale.value ?? Number(DEFAULTS.scale) };
  return { ok: Object.keys(errors).length === 0, values, errors };
}

/**
 * The size of the finished image.
 * @param {{width: number, height: number | null, scale: number}} values
 * @param {number} figureHeight  the height of the figure on screen (used when height is blank)
 * @returns {{width: number, height: number, total: number}}
 */
export function pixelSize(values, figureHeight) {
  const width = Math.round(values.width * values.scale);
  const height = Math.round((values.height ?? figureHeight) * values.scale);
  return { width, height, total: width * height };
}

/**
 * Query parameters of the image export routes.
 * @param {{width: number, height: number | null, scale: number}} values
 * @param {boolean} transparent
 * @returns {Record<string, unknown>}
 */
export function imageQuery(values, transparent) {
  return { width: values.width, height: values.height ?? undefined, scale: values.scale, transparent: transparent ? true : undefined };
}
