/**
 * A section's error notice wired to the store: shows the failure of the last preview or save that
 * belongs to the section (`domain`: "source", "transform", "style"), places each message on its
 * field, and tells the section how many problems there are (for a badge on a closed section).
 *
 * `createErrorNotice({store, domain, resolve, codes, badge})` -> `{el, dispose}`; `resolve(path)`
 * maps a path such as ["style", "height"] to a field with `setError`; `codes` are error codes
 * without a location that the section shows itself (for example "source_error"); `reword(text)`
 * (optional) turns a server sentence into one that names what the person sees on screen.
 */

import { createErrorSink, createNotice } from "./errors.js";

/**
 * Creates the notice and subscribes it to `status.error`.
 * @param {{store: object, domain: string, resolve: Function, codes?: string[], badge?: (count: number) => void, reword?: (text: string) => string}} config
 * @returns {{el: HTMLElement, dispose: () => void}}
 */
export function createErrorNotice(config) {
  const notice = createNotice();
  const sink = createErrorSink({
    owns: (path) => path[0] === config.domain,
    resolve: config.resolve,
    codes: config.codes,
    notice: (messages) => notice.set(config.reword ? messages.map(config.reword) : messages),
  });
  const off = config.store.subscribe((error) => config.badge?.(sink.apply(error)), {
    select: (state) => state.status.error,
    immediate: true,
  });
  return { el: notice.el, dispose: off };
}
