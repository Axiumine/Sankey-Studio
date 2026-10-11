/**
 * Debounce and a promise sleep.
 *
 * `debounce(fn, ms)` returns a callable that runs `fn` with the arguments of the LAST call once
 * `ms` milliseconds passed without a new call. It also has `.cancel()`, `.flush()` (run now if a
 * call is pending) and `.pending()` (is a call waiting). Timers are plain setTimeout, so fake
 * timers work in tests.
 */

/**
 * @template {(...args: any[]) => void} F
 * @param {F} fn
 * @param {number} ms
 * @returns {F & {cancel: () => void, flush: () => void, pending: () => boolean}}
 */
export function debounce(fn, ms) {
  let timer = null;
  let lastArgs = null;
  const run = () => {
    timer = null;
    const args = lastArgs;
    lastArgs = null;
    fn(...args);
  };
  const debounced = (...args) => {
    lastArgs = args;
    if (timer !== null) {
      clearTimeout(timer);
    }
    timer = setTimeout(run, ms);
  };
  debounced.cancel = () => {
    if (timer !== null) {
      clearTimeout(timer);
    }
    timer = null;
    lastArgs = null;
  };
  debounced.flush = () => {
    if (timer !== null) {
      clearTimeout(timer);
      run();
    }
  };
  debounced.pending = () => timer !== null;
  return debounced;
}

/**
 * Resolves after `ms` milliseconds.
 * @param {number} ms
 * @returns {Promise<void>}
 */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
