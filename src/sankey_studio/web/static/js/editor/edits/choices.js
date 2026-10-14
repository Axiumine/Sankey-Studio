/**
 * What the person already answered in the consent dialog during this page session.
 *
 * Pure bookkeeping (no DOM), so it can be tested on its own:
 * - a plain "Keep in this graph" is remembered for the consent KEY (the opaque string the server
 *   built for the target), never persisted: a reload asks again;
 * - `share(key, start)` keeps ONE in-flight question per key: edits that queue up while the dialog
 *   is open wait on the same promise instead of raising a dialog each.
 */

/**
 * @returns {{remembered: (key: string) => boolean, remember: (key: string) => void, forget: () => void, share: <T>(key: string, start: () => Promise<T>) => Promise<T>}}
 */
export function createChoices() {
  const kept = new Set();
  const asking = new Map();
  return {
    remembered: (key) => kept.has(key),
    remember: (key) => {
      kept.add(key);
    },
    forget: () => kept.clear(),
    share(key, start) {
      if (asking.has(key)) {
        return asking.get(key);
      }
      const question = start().finally(() => asking.delete(key));
      asking.set(key, question);
      return question;
    },
  };
}
