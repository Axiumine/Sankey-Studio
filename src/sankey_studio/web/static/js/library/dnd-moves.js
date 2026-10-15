/**
 * What a drop does: the same two moves as the Move dialog, without the dialog.
 *
 * `createMoves({folders, view})` is the `host` of dnd.js:
 *   - `allowed()`            writes are allowed, the list follows an open (or the top) level, and the
 *                            open collection exists; otherwise nothing is draggable
 *   - `busy`                 true while a move request runs (a second drop is ignored, no drag starts)
 *   - `reason(drag, target)` why `target` (`null` = the library) cannot take the drag: the sentences of
 *                            folder-rules.js, or "that collection no longer exists"; `null` = it can
 *   - `drop(drag, target)`   re-checks the rules against the live index (it may have changed since
 *                            the drag started), then moves
 *
 * A drag is `{kind: "graph" | "folder", items: [{id, name}], picked, local}`. Graphs: `POST /graphs/move`
 * for every carried graph, then the selection is cleared when the carried set was the selection (an
 * unpicked card leaves the other picks alone), the same toast as the dialog (`tellMoved`) and a
 * reload. Collection: `PUT /folders/{id}` with the new `parent_id` and the revision of the live
 * index, the toast `Moved "X" to <place>.` and a reload. Both run through `FolderBrowser.guard`: a
 * collection that is gone or changed (404, stale revision) says so in an info toast and reloads.
 * Any other failure (a taken name, a rule of the server, the network) is an error toast with the
 * sentence the dialog would show (`describe`), then a reload, so no stale card stays. Afterwards the
 * focus goes where the Move button flow leaves it: the results summary for graphs, the moved
 * collection's card (or the block of cards) for a collection.
 */

import { canWrite } from "../core/boot.js";
import { toast } from "../core/toast.js";
import { describe } from "./folder-dialogs.js";
import { createRules, parentOf } from "./folder-rules.js";
import { GONE } from "./folders.js";
import { moveGraphs, updateFolder } from "./folders-data.js";
import { folderLabel } from "./names.js";
import { isScoped } from "./state.js";

/** Why a place is refused when the collection (the target, or the one being moved) is not in the index any more. */
export const REASON_GONE = "that collection no longer exists";

class Moves {
  /** @param {{folders: object, view: {restoreFocus: Function}}} options */
  constructor({ folders, view }) {
    this.folders = folders;
    this.view = view;
    this.busy = false;
  }

  allowed() {
    return canWrite() && isScoped(this.folders.state) && !this.folders.missing;
  }

  reason(drag, target) {
    const { index, state } = this.folders;
    const moving = drag.kind === "folder" ? (index.get(drag.items[0].id) ?? null) : null;
    if ((drag.kind === "folder" && moving === null) || (target !== null && !index.has(target))) {
      return REASON_GONE;
    }
    // graphs: all on the page means all directly in the open collection; a pick from a search can be anywhere
    const current = moving ? parentOf(index, moving.id) : (drag.local ? (state.folder || null) : undefined);
    return createRules({ index, current, moving })(target);
  }

  async drop(drag, target) {
    if (this.busy || !this.allowed()) {
      return;
    }
    this.busy = true;
    try {
      if (!(await this.apply(drag, target))) {
        return; // the live rules refuse it: nothing was sent
      }
    } catch (failure) {
      toast.error(describe(failure));
      await this.folders.onChange(); // the cards must show what the server has
    } finally {
      this.busy = false;
    }
    if (drag.kind === "graph") {
      this.view.restoreFocus(null);
    } else {
      this.folders.focusCard(drag.items[0].id);
    }
  }

  /** Resolves to false when the live rules refuse the move. */
  async apply(drag, target) {
    const reason = this.reason(drag, target);
    if (reason === REASON_GONE) {
      toast.info(GONE);
      await this.folders.onChange();
      return true;
    }
    if (reason !== null) {
      return false;
    }
    await (drag.kind === "graph" ? this.dropGraphs(drag, target) : this.dropFolder(drag, target));
    return true;
  }

  dropGraphs(drag, target) {
    const { folders } = this;
    const ids = drag.items.map((item) => item.id);
    const single = ids.length === 1 ? drag.items[0] : null;
    return folders.guard(async () => {
      const report = await moveGraphs(ids, target);
      if (drag.picked) {
        folders.selection.clear();
      }
      folders.tellMoved(report, { single, target });
      await folders.onChange();
      return report;
    });
  }

  dropFolder(drag, target) {
    const { folders } = this;
    const folder = folders.index.get(drag.items[0].id); // the live record: its revision is the one the server wants
    return folders.guard(async () => {
      const updated = await updateFolder(folder, { parent_id: target });
      toast.success(`Moved “${folderLabel(updated.name)}” to ${folders.placeName(target)}.`);
      await folders.onChange();
      return updated;
    });
  }
}

/**
 * @param {{folders: object, view: {restoreFocus: (memo: null) => void}}} options
 * @returns {Moves}
 */
export function createMoves(options) {
  return new Moves(options);
}
