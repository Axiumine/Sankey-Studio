/**
 * The two list editors of the transform section: merge nodes (alias -> canonical name) and
 * category rules (glob -> category, first match wins). Both are row tables (meta/row-table.js)
 * that commit complete rows to the store and re-read the store when it changes from elsewhere.
 *
 * Field names and limits follow `TransformSpec` (models/transform.py): merge_nodes up to 5000
 * pairs, names 1-200 characters; category_rules up to 200 rules, pattern 1-200, category 1-100,
 * never the reserved names Uncategorized and Other.
 */

import { createRowTable } from "../meta/row-table.js";
import { isReservedCategory, knownCategories, knownNodeNames, sameJson } from "../meta/util.js";

const TRANSFORM = ["draft", "transform"];
export const MAX_MERGES = 5000;
export const MAX_RULES = 200;

const MATCHES = [
  { value: "either", label: "Either end" },
  { value: "source", label: "Source" },
  { value: "target", label: "Target" },
];

const nodeNames = (store) => () => knownNodeNames(store.get().bundle);

/**
 * The merge editor. `sync(dict)` shows a merge map from the store.
 * @param {object} store
 * @returns {{el: HTMLElement, table: object, sync: (merge: Record<string, string>) => void, resolve: (path: (string|number)[]) => object | null}}
 */
export function createMergeEditor(store) {
  const table = createRowTable({
    caption: "Merged nodes",
    addLabel: "Add a merge",
    emptyMessage: "No merges yet. Merge nodes that are the same thing under different names.",
    maxRows: MAX_MERGES,
    testids: { table: "transform-merge-nodes" },
    columns: [
      { key: "alias", label: "Merge this node", suggest: nodeNames(store), maxlength: 200, placeholder: "Name to replace" },
      { key: "canonical", label: "Into this node", suggest: nodeNames(store), maxlength: 200, placeholder: "Name to keep" },
    ],
    toValues: (item) => ({ alias: item.alias, canonical: item.canonical }),
    toItem: (values) => (values.alias.trim() && values.canonical.trim() ? { alias: values.alias.trim(), canonical: values.canonical.trim() } : null),
    validate: (values, { index, all }) => {
      const alias = values.alias.trim();
      const problems = {};
      if (alias && alias === values.canonical.trim()) {
        problems.canonical = "Choose a different node to merge into.";
      }
      if (alias && all.findIndex((other) => other.alias.trim() === alias) < index) {
        problems.alias = "This node is already merged in a row above.";
      }
      return problems;
    },
    onCommit: (items) => store.patch([...TRANSFORM, "merge_nodes"], Object.fromEntries(items.map((item) => [item.alias, item.canonical]))),
  });
  const asDict = (items) => Object.fromEntries(items.map((item) => [item.alias, item.canonical]));
  return {
    el: table.el,
    table,
    sync(merge) {
      if (!sameJson(merge ?? {}, asDict(table.committed()))) {
        table.setItems(Object.entries(merge ?? {}).map(([alias, canonical]) => ({ alias, canonical })));
      }
    },
    resolve: () => null,
  };
}

function ruleProblems(values) {
  const problems = {};
  if (isReservedCategory(values.category)) {
    problems.category = "Uncategorized and Other are reserved names. Pick another category.";
  }
  return problems;
}

/**
 * The category rules editor. `sync(rules)` shows the rules from the store.
 * @param {object} store
 * @returns {{el: HTMLElement, table: object, sync: (rules: object[]) => void, resolve: (path: (string|number)[]) => object | null}}
 */
export function createRulesEditor(store) {
  const table = createRowTable({
    caption: "Category rules",
    addLabel: "Add a rule",
    emptyMessage: "No rules yet. A rule gives a category to every entry whose node name matches a pattern.",
    maxRows: MAX_RULES,
    reorder: true,
    testids: { table: "transform-rules" },
    footnote: "Rules are tried from top to bottom and the first match wins. Patterns ignore case and match the whole name: * is any text, ? is one character, [abc] is one of a set.",
    columns: [
      { key: "match", label: "Match", kind: "select", options: MATCHES, className: "ed-col-select" },
      { key: "pattern", label: "Name pattern", maxlength: 200, placeholder: "e.g. rent*", suggest: nodeNames(store) },
      { key: "category", label: "Category", maxlength: 100, placeholder: "e.g. Housing", suggest: () => knownCategories(store.get().bundle, table.committed().map((rule) => rule.category)) },
    ],
    toValues: (rule) => ({ match: rule.match ?? "either", pattern: rule.pattern, category: rule.category }),
    toItem: (values) => (values.pattern.trim() && values.category.trim() ? { match: values.match, pattern: values.pattern.trim(), category: values.category.trim() } : null),
    validate: ruleProblems,
    onCommit: (items) => store.patch([...TRANSFORM, "category_rules"], items),
  });
  return {
    el: table.el,
    table,
    sync(rules) {
      if (!sameJson(rules ?? [], table.committed())) {
        table.setItems(rules ?? []);
      }
    },
    /** `path` is what follows "category_rules": [index, key]. */
    resolve(path) {
      const [index, key] = path;
      if (typeof index !== "number" || !["pattern", "category", "match"].includes(key)) {
        return null;
      }
      return { setError: (message) => table.setCellError(index, key, message) };
    },
  };
}
