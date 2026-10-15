/**
 * Collections on the library page: the path, the cards of the open level, and the actions that
 * change them (create, rename, move, delete, and moving graphs into one).
 *
 * `createFolders({state, selection, onChange})` returns a `FolderBrowser`:
 *   - `pathEl`    the breadcrumb (mounted above the toolbar)
 *   - `el`        the cards and the "this collection is gone" notice (mounted under the toolbar)
 *   - `actionsEl` the buttons next to the page heading: "New collection" and, inside one, "New graph here"
 *   - `setIndex(items)` takes the list of collections (boot data or `GET /folders`) and redraws
 *   - `update()`  redraws after the state changed (search, tag)
 *   - `scope()`   what the result area needs to know (see view.js)
 *   - `moveGraphs(graphs)` asks where the graphs go and moves them
 * `state` is the page's live query state (`folder`, `q`, `tag`); `onChange()` reloads the list and
 * the index after every change the server accepted.
 *
 * A search or a tag looks at every collection, so while one is set the path, the cards and the two
 * buttons are hidden (the results then show where each graph lives). The index is never trusted
 * to be consistent (see folders-data.js); a collection in the address that the index does not know
 * shows a notice with a link back to the library instead of an empty list.
 *
 * Every change that the server refuses because the collection moved on (404, stale revision) says
 * so, reloads and closes the dialog; any other failure stays in the dialog under the field.
 *
 * Collection cards are draggable while writes are allowed (dnd.js moves them; dnd-moves.js runs the
 * request through `guard` and the same toasts as the dialog).
 *
 * Test ids: folder-new, folder-new-graph, library-folder-missing (the rest: breadcrumb.js,
 * folder-cards.js, folder-dialogs.js).
 */

import { reportError } from "../core/api.js";
import { canWrite, lockWriteControls } from "../core/boot.js";
import { h } from "../core/dom.js";
import { formatCount } from "../core/format.js";
import { icon } from "../core/icons.js";
import { emptyState } from "../core/states.js";
import { toast } from "../core/toast.js";
import { createBreadcrumb } from "./breadcrumb.js";
import { folderSection } from "./folder-cards.js";
import { askName, askTarget, confirmDeleteFolder } from "./folder-dialogs.js";
import { buildIndex, createFolder, DEPTH_MAX, deleteFolder, moveGraphs, updateFolder } from "./folders-data.js";
import { displayName, folderLabel } from "./names.js";
import { isFolderId, isScoped } from "./state.js";

const STALE = "That collection was changed elsewhere, so the list was reloaded. Try again.";
/** Also the toast of a drop onto a collection that is gone (dnd-moves.js). */
export const GONE = "That collection no longer exists, so the list was reloaded.";

class FolderBrowser {
  constructor({ state, selection, onChange }) {
    this.state = state;
    this.selection = selection;
    this.onChange = onChange;
    this.index = buildIndex([]);
    this.breadcrumb = createBreadcrumb();
    this.body = h("div", { class: "folder-body" });
    this.pathEl = this.breadcrumb.el;
    this.el = h("div", { class: "folders" }, this.body);
    this.newFolder = h("button", { type: "button", class: "btn", "data-writes": true, "data-testid": "folder-new", on: { click: (event) => this.create(event.currentTarget) } }, icon("folder-plus", { size: 14 }), "New collection");
    this.newGraph = h("a", { class: "btn", "data-writes": true, "data-testid": "folder-new-graph", hidden: true }, icon("plus", { size: 14 }), "New graph here");
    this.actionsEl = h("div", { class: "cluster", role: "group", "aria-label": "Collections" }, this.newGraph, this.newFolder);
    this.handlers = {
      onRename: (folder, button) => this.rename(folder, button),
      onMove: (folder, button) => this.moveFolder(folder, button),
      onDelete: (folder, button) => this.remove(folder, button),
    };
    lockWriteControls(this.actionsEl);
  }

  /** True when the address names a collection the index does not know. */
  get missing() {
    return Boolean(this.state.folder) && !this.index.has(this.state.folder);
  }

  setIndex(items) {
    this.index = buildIndex(items.filter((item) => isFolderId(item.id)));
    this.update();
  }

  update() {
    const browsing = isScoped(this.state) && !this.missing;
    const open = this.state.folder || null;
    this.breadcrumb.update(browsing ? this.index.pathOf(open) : []);
    this.body.replaceChildren(...this.bodyNodes(browsing, open));
    lockWriteControls(this.body);
    this.newFolder.hidden = !browsing || this.index.depthOf(open) >= DEPTH_MAX;
    this.newGraph.hidden = !browsing || open === null;
    if (open !== null && canWrite()) {
      this.newGraph.setAttribute("href", `/graphs/new?folder=${open}`);
    }
  }

  bodyNodes(browsing, open) {
    if (this.missing && isScoped(this.state)) {
      return [emptyState({
        title: "This collection no longer exists",
        message: "It may have been deleted, or the link is wrong. Its graphs, if any, are in the library.",
        icon: "folder",
        actions: [h("a", { class: "btn", href: "/" }, "Back to the library")],
        testid: "library-folder-missing",
      })];
    }
    const section = browsing ? folderSection({ folders: this.index.childrenOf(open), handlers: this.handlers, draggable: canWrite() }) : null;
    return section ? [section] : [];
  }

  /** What the result area needs: the size of the tree, where we are, and how to name a path. */
  scope() {
    const open = this.state.folder || null;
    return {
      folders: this.index.items.length,
      missing: this.missing && isScoped(this.state),
      inFolder: open !== null && !this.missing,
      children: this.index.childrenOf(open).length,
      onNewFolder: () => this.create(),
      pathOf: (id) => {
        const path = this.index.pathOf(id);
        return path.length > 0 ? path.map((folder) => folderLabel(folder.name)).join(" / ") : null;
      },
    };
  }

  /** Puts the focus on a card's link, or on the block of cards (or the page) when the card is gone. */
  focusCard(id) {
    const link = id ? this.el.querySelector(`[data-folder-id="${id}"] [data-testid="folder-open"]`) : null;
    (link ?? this.el.querySelector(".folder-section") ?? document.getElementById("main"))?.focus();
  }

  /** Runs a request; a collection that vanished or changed shows a toast, reloads and closes the dialog. */
  async guard(run) {
    try {
      return await run();
    } catch (error) {
      if (error?.status !== 404 && !error?.conflict) {
        throw error;
      }
      toast.info(error.conflict ? STALE : GONE);
      await this.onChange();
      return { stale: true };
    }
  }

  async create() {
    const parent = this.state.folder || null;
    const made = await askName({
      title: "New collection",
      parentLabel: parent ? folderLabel(this.index.get(parent)?.name) : "Library",
      confirmLabel: "Create",
      submit: (name) => this.guard(async () => {
        const created = await createFolder({ name, parent_id: parent });
        toast.success(`Created the collection “${folderLabel(created.name)}”.`);
        await this.onChange();
        return created;
      }),
    });
    if (made?.id) {
      this.focusCard(made.id);
    }
  }

  async rename(folder) {
    const done = await askName({
      title: `Rename “${folderLabel(folder.name)}”`,
      initial: folder.name,
      confirmLabel: "Rename",
      submit: (name) => this.guard(async () => {
        const updated = await updateFolder(folder, { name });
        toast.success(`Renamed to “${folderLabel(updated.name)}”.`);
        await this.onChange();
        return updated;
      }),
    });
    if (done) {
      this.focusCard(folder.id);
    }
  }

  async moveFolder(folder) {
    const done = await askTarget({
      title: `Move “${folderLabel(folder.name)}” to`,
      index: this.index,
      current: this.index.has(folder.parent_id) ? folder.parent_id : null,
      moving: folder,
      submit: (target) => this.guard(async () => {
        const updated = await updateFolder(folder, { parent_id: target });
        toast.success(`Moved “${folderLabel(updated.name)}” to ${this.placeName(target)}.`);
        await this.onChange();
        return updated;
      }),
    });
    if (done) {
      this.focusCard(folder.id);
    }
  }

  async remove(folder) {
    const parent = this.index.has(folder.parent_id) ? folder.parent_id : null;
    if (!(await confirmDeleteFolder(folder, this.placeName(parent)))) {
      return;
    }
    try {
      await deleteFolder(folder.id);
      toast.success(`Deleted the collection “${folderLabel(folder.name)}”. Its contents moved up.`);
    } catch (error) {
      if (error?.status === 404) {
        toast.info(GONE);
      } else {
        reportError(error, toast);
      }
    }
    await this.onChange();
    this.focusCard(null);
  }

  /** "Library" or a collection name in quotes, for a sentence. */
  placeName(id) {
    return id === null ? "the library" : `“${folderLabel(this.index.get(id)?.name)}”`;
  }

  /**
   * Asks where graphs go and moves them. Resolves to the server's report, or `undefined` when the
   * person cancelled.
   * @param {{id: string, name?: string, folder_id?: string | null}[]} graphs  `folder_id` (`null` = top level)
   *   tells where a single graph sits now, so that place is not offered; leave it out when unknown
   */
  async moveGraphs(graphs) {
    const single = graphs.length === 1 ? graphs[0] : null;
    const known = single !== null && single.folder_id !== undefined;
    const current = known ? (this.index.has(single.folder_id) ? single.folder_id : null) : undefined;
    const what = single ? `“${displayName(single.name)}”` : formatCount(graphs.length, "graph");
    return askTarget({
      title: `Move ${what} to`,
      index: this.index,
      current,
      submit: (target) => this.guard(async () => {
        const report = await moveGraphs(graphs.map((graph) => graph.id), target);
        this.selection.clear();
        this.tellMoved(report, { single, target });
        await this.onChange();
        return report;
      }),
    });
  }

  tellMoved(report, { single, target }) {
    const gone = report.missing.length > 0 ? ` ${formatCount(report.missing.length, "graph")} no longer existed.` : "";
    const moved = single && report.moved === 1 ? `“${displayName(single.name)}”` : formatCount(report.moved, "graph");
    const show = report.moved > 0 ? toast.success : toast.info;
    show(`Moved ${moved} to ${this.placeName(target)}.${gone}`);
  }
}

/**
 * @param {{state: object, selection: object, onChange: () => Promise<void> | void}} options
 * @returns {FolderBrowser}
 */
export function createFolders(options) {
  return new FolderBrowser(options);
}
