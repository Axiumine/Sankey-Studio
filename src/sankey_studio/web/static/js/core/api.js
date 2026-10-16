// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The ONE fetch wrapper of the app (API.md section 1). Nothing else calls fetch().
 *
 * Rules it enforces
 * - Same origin only: paths are root-relative and are prefixed with `/api/v1`; anything that
 *   could leave the origin (a "//host" or an absolute URL) is a TypeError.
 * - JSON in, JSON out: bodies are `JSON.stringify`-ed with `Content-Type: application/json`;
 *   bodiless unsafe requests (DELETE, duplicate) send no body and no content type; uploads pass a
 *   FormData and the browser sets the multipart boundary. Never an HTML form.
 * - Query strings come from `buildQuery`: null/undefined/"" are dropped, arrays (ids) are joined
 *   with commas, booleans are "true"/"false". Unknown parameters are a 422, so send only
 *   documented ones.
 * - Every failure is an `ApiError {status, code, message, details}` built from the error envelope
 *   `{error: {code, message, details}}`; network failures are status 0 / code "network_error";
 *   a non-JSON answer is code "http_error". Aborted requests rethrow the browser AbortError
 *   (test with `isAbort(err)`).
 * - Busy tracking: a `sankey:busy` event ({detail: {pending}}) fires on `document` while requests
 *   are in flight; core/shell.js turns it into the loading bar (opt out with `quiet: true`).
 *
 * Usage
 *   const graph = await api.get(`/graphs/${id}`);
 *   const saved = await api.put(`/graphs/${id}`, body, { signal });
 *   await api.del(`/graphs/${id}`);                      // resolves to null (204)
 *   const created = await api.upload("/sources/files", formData);
 *   const { blob, headers } = await api.blob(`/graphs/${id}/export`, { query: { format: "csv" } });
 */

export const API_BASE = "/api/v1";
const JSON_TYPE = "application/json";

/** An API failure; `message` is the server's English text, `friendly` suits a toast. */
export class ApiError extends Error {
  /**
   * @param {{status: number, code: string, message: string, details?: string[]}} init
   */
  constructor({ status, code, message, details = [] }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when the server is in read-only remote mode (403 read_only_mode). */
  get readOnly() {
    return this.code === "read_only_mode";
  }

  /** True for a stale revision on PUT (409 conflict). */
  get conflict() {
    return this.status === 409 && this.code === "conflict";
  }

  /** A short sentence for the reader; falls back to the server message. */
  get friendly() {
    return friendlyMessage(this);
  }
}

/**
 * True when `error` is the AbortError of a cancelled request (not a failure to report).
 * @param {unknown} error
 * @returns {boolean}
 */
export function isAbort(error) {
  return error instanceof DOMException && error.name === "AbortError";
}

function formatValue(value) {
  return Array.isArray(value) ? value.map(String).join(",") : String(value);
}

/**
 * Builds "?a=1&ids=x,y" from an object ("" when nothing is left).
 * @param {Record<string, unknown> | null | undefined} params
 * @returns {string}
 */
export function buildQuery(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    const empty = value == null || value === "" || (Array.isArray(value) && value.length === 0);
    if (!empty) {
      search.set(key, formatValue(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function urlFor(path, query) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || path.includes("://")) {
    throw new TypeError(`API paths are root-relative ("/graphs"), got ${JSON.stringify(path)}`);
  }
  return `${API_BASE}${path}${buildQuery(query)}`;
}

function limitText(details) {
  const hit = details.map((d) => /limit_bytes=(\d+)/.exec(d)).find(Boolean);
  if (!hit) {
    return "";
  }
  return ` (limit ${(Number(hit[1]) / (1024 * 1024)).toFixed(1).replace(/\.0$/, "")} MB)`;
}

function friendlyMessage(error) {
  if (error.status === 0) {
    return "Cannot reach the server. Check that Sankey Studio is still running.";
  }
  if (error.code === "payload_too_large") {
    return `That is too large for the server${limitText(error.details)}.`;
  }
  if (error.code === "unsupported_media_type") {
    return "The server did not accept that kind of data.";
  }
  if (error.code === "forbidden") {
    return "The server refused this request because it did not come from the app itself.";
  }
  return error.message;
}

async function readError(response) {
  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    if (isAbort(error)) {
      throw error; // cancelled while the error body was still arriving: not a failure to report
    }
    body = null;
  }
  const envelope = body && typeof body === "object" ? body.error : null;
  if (envelope && typeof envelope === "object") {
    return new ApiError({
      status: response.status,
      code: String(envelope.code ?? "http_error"),
      message: String(envelope.message ?? `Request failed (${response.status})`),
      details: Array.isArray(envelope.details) ? envelope.details.map(String) : [],
    });
  }
  return new ApiError({ status: response.status, code: "http_error", message: `Request failed (${response.status})` });
}

let pending = 0;

function trackBusy(delta) {
  pending = Math.max(0, pending + delta);
  document.dispatchEvent(new CustomEvent("sankey:busy", { detail: { pending } }));
}

function requestInit(method, options) {
  const init = { method, signal: options.signal, credentials: "same-origin", headers: {} };
  if (options.form instanceof FormData) {
    init.body = options.form;
  } else if (options.json !== undefined) {
    init.body = JSON.stringify(options.json);
    init.headers["Content-Type"] = JSON_TYPE;
  }
  if (options.accept) {
    init.headers.Accept = options.accept;
  }
  return init;
}

async function send(method, path, options = {}) {
  const url = urlFor(path, options.query);
  const track = !options.quiet;
  if (track) {
    trackBusy(1);
  }
  try {
    return await fetch(url, requestInit(method, options));
  } catch (error) {
    if (isAbort(error)) {
      throw error;
    }
    throw new ApiError({ status: 0, code: "network_error", message: "Network error" });
  } finally {
    if (track) {
      trackBusy(-1);
    }
  }
}

async function json(method, path, options) {
  const response = await send(method, path, { accept: JSON_TYPE, ...options });
  if (!response.ok) {
    throw await readError(response);
  }
  if (response.status === 204) {
    // drain the (empty) body: an unread body is reported as a failed request (net::ERR_ABORTED)
    await response.text();
    return null;
  }
  try {
    return await response.json();
  } catch (error) {
    if (isAbort(error)) {
      throw error; // cancelled while the body was still arriving: callers test isAbort()
    }
    throw new ApiError({ status: response.status, code: "http_error", message: "The server sent an unreadable answer" });
  }
}

/**
 * Splits validation details ("body.source.text: Value error, ...") into
 * `{field, path, message}`; `field` drops the "body."/"query." prefix. Details without a
 * location keep `field: ""`.
 * @param {ApiError} error
 * @returns {{field: string, path: string[], message: string}[]}
 */
export function fieldErrors(error) {
  return (error.details ?? []).map((detail) => {
    const cut = detail.indexOf(": ");
    const where = cut > 0 ? detail.slice(0, cut) : "";
    const field = where.replace(/^(body|query)\.?/, "");
    return { field, path: field ? field.split(".") : [], message: cut > 0 ? detail.slice(cut + 2) : detail };
  });
}

/**
 * The single place that turns a failure into UI: aborts are ignored, everything else becomes an
 * error toast (pass `toast` from core/toast.js). Returns the ApiError, or null for an abort.
 * @param {unknown} error
 * @param {{error: (message: string) => unknown}} [toast]
 * @returns {ApiError | null}
 */
export function reportError(error, toast) {
  if (isAbort(error)) {
    return null;
  }
  const apiError = error instanceof ApiError
    ? error
    : new ApiError({ status: 0, code: "client_error", message: error instanceof Error ? error.message : "Unexpected error" });
  toast?.error(apiError.friendly);
  return apiError;
}

/**
 * Fetches an attachment as a Blob (exports). Resolves `{blob, headers}`. `method` is `GET` by
 * default; `{method: "POST", json}` sends the draft of an unsaved graph as a JSON body.
 * @param {string} path
 * @param {{method?: "GET"|"POST", json?: unknown, query?: object, signal?: AbortSignal, quiet?: boolean}} [options]
 * @returns {Promise<{blob: Blob, headers: Headers}>}
 */
async function blob(path, options = {}) {
  const { method = "GET", ...rest } = options;
  const response = await send(method, path, { accept: "*/*", ...rest });
  if (!response.ok) {
    throw await readError(response);
  }
  try {
    return { blob: await response.blob(), headers: response.headers };
  } catch (error) {
    if (isAbort(error)) {
      throw error;
    }
    throw new ApiError({ status: 0, code: "network_error", message: "Network error" });
  }
}

/** The API client; every method takes `{query, signal, quiet}` as its last argument. */
export const api = {
  get: (path, options) => json("GET", path, options),
  post: (path, body, options) => json("POST", path, { ...options, json: body }),
  put: (path, body, options) => json("PUT", path, { ...options, json: body }),
  patch: (path, body, options) => json("PATCH", path, { ...options, json: body }),
  del: (path, options) => json("DELETE", path, options),
  /** Bodiless POST such as /graphs/{id}/duplicate. */
  action: (path, options) => json("POST", path, options),
  /** Multipart upload; the FormData is sent as is and the browser sets the boundary. */
  upload: (path, form, options) => json("POST", path, { ...options, form }),
  blob,
};
