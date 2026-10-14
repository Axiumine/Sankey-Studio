/**
 * Where an edit of the data would go, judged from the source alone (no network).
 *
 * `classify(source)` -> `{where: "draft" | "file" | "mongo" | "blocked", message?}`
 *   draft    manual links and pasted text: the edit changes the draft itself, never asks
 *   file     a text file of the sources folder: the server may write it, with consent
 *   mongo    a MongoDB collection: the server may write it, with consent
 *   blocked  the source names nothing to edit yet (no file or no collection chosen)
 * The consent KEY is not computed here: the server builds it from resolved values (the browser
 * cannot know the default database of a connection), see `plan.target_key`.
 */

/**
 * @param {{type?: string, origin?: string, path?: string | null, connection?: string, collection?: string} | null | undefined} source
 * @returns {{where: "draft" | "file" | "mongo" | "blocked", message?: string}}
 */
export function classify(source) {
  if (source?.type === "mongo") {
    return source.connection && source.collection ? { where: "mongo" } : { where: "blocked", message: "Choose a collection first." };
  }
  if (source?.type === "text" && source.origin === "file") {
    return source.path ? { where: "file" } : { where: "blocked", message: "Choose a file first." };
  }
  return { where: "draft" };
}
