# Settings

Part of the [UI reference](../ui.md).

`/settings` has five sections, `section.settings-section` with the ids `settings-appearance`,
`settings-storage`, `settings-connections`, `settings-limits` and `settings-server`, then the sticky
save bar. From 900 px each section is a title and help text on the left and a card on the right; below
900 px they stack. From 1280 px a sticky rail `nav.settings-toc` ("On this page", `aria-label` "Settings
sections") lists the section anchors and follows the reading position with `aria-current=location`;
below 1280 px it is `display: none`. It is added a moment after the page is assembled.

States:

| State | What is on screen |
|---|---|
| Loading | `state-loading` "Loading settings" |
| Error | `state-error` "The settings could not be loaded" with `state-retry` |
| Ready | the sections and the save bar (wait for `settings-save`) |
| Validation error | `settings-error` ("Settings were not saved", with links to the fields) and inline field messages, an error toast; focus moves to the summary |
| Saving | `.settings[aria-busy=true]`, fields disabled, `settings-save` has `aria-busy` and `aria-disabled` but stays focusable |
| Read-only | every field of the form is disabled, including Test connection, Delete, Add connection, Test storage and `settings-save`; both banners; the theme cards still work and keep the choice on this device |

Behaviour:

* **Appearance.** Three cards `settings-theme-option` (radio inputs in the order System, Light, Dark).
  A pick applies at once and saves through the [shared settings write queue](shell.md#the-shell). The result is a hint line under the cards,
  not a toast: "Theme saved." (on a read-only server "Kept on this device only: this server is
  read-only."; when the save fails "Applied, but not saved." plus one info toast). The System card
  reads "Follows your device (now light)." or "(now dark)" for what the device does now.
* **Storage.** `settings-storage-backend` (`file` "Files on this computer" or `mongo`).
  While the backend is `file`, `settings-storage-folder` (a `code` element, read-only) names the folder
  that holds the graph files, after "Graphs folder:"; it is hidden for `mongo` and follows the select
  before saving.
  `settings-storage-connection` and `settings-storage-database` show only for `mongo`, with the hint "The
  graphs go into the MongoDB collection sankey_studio_graphs of this database, and the library's own
  collections (groups of graphs) into sankey_studio_collections."; the connection needs write permission on
  both and "Test storage" probes both. A switch can copy the existing graphs and their collections
  (`settings-migrate`, "Copy my N existing graphs to the new location"). On a
  read-only server it is unticked and disabled ("Not available: this server is read-only, so nothing
  can be copied."). `settings-test-storage` writes its result into `settings-storage-status`
  ("Storage is reachable and writable."). After a copy `settings-copy-report` (`role=status`,
  `tabindex=-1`, `data-copied`, `data-skipped`, `data-unreadable`, `data-folders`, `data-folders-skipped`)
  shows Copied, "Already there, skipped" and "Could not be read", and, only when either is not zero,
  "Collections copied" and "Collections skipped"; `settings-copy-unreadable` lists up to 50 ids followed by "And N
  more that are not listed."; its button "Dismiss the copy report" moves focus to
  `settings-test-storage`. Switching to files while the old MongoDB is unreachable fails with the
  summary, a toast and the hint to untick "Copy my existing graphs" and save again.
* **Connections.** Rows (`settings-connection`, `role=group`) exist only after `connection-add` or
  when connections are stored (at most 20); with none, `state-empty` "No connections yet" is shown. Name (`^[A-Za-z0-9_.-]{1,64}$`), connection string
  (`connection-uri`, `type=password`, placeholder "(unchanged)" once stored, never prefilled, the
  value is nowhere in the page or in `GET /settings`), default database. `connection-test` calls
  `POST /settings/mongo/<name>/test` for a saved, unchanged row and `POST /settings/storage/test` for
  a new or edited one; the result is `connection-status` (and `connection-latency` after a success).
  After 1.5 s it reads "Still testing the connection... A MongoDB server that cannot be reached can
  take up to 15 seconds to answer." (the stored `mongo_timeout_ms`). Editing or deleting the row
  aborts the request (`net::ERR_ABORTED`, no toast, no stale line). `connection-delete` removes the
  card at once, with no confirmation, and shows `Connection "<name>" removed. It is deleted when you
  save.` with Undo; it needs Save. The badge "Holds your graphs" shows only on the card chosen as the
  MongoDB storage connection while the backend is `mongo`. The visible names of the test and delete
  buttons are "Test connection" and "Delete", but their `aria-label` includes the connection name.
  On a read-only server the hint reads "Stored: mongodb://***. Connection strings cannot be changed
  because this server is read-only." For a new row the hint gives the three shapes: one server
  (`mongodb://user:password@host:27017/`), a replica set (`...@h1:27017,h2:27017,h3:27017/?replicaSet=rs0`)
  and Atlas (`mongodb+srv://...`); the input placeholder stays `mongodb://user:password@host:27017`.
* **Limits.** `settings-max-links` (100 to 5,000,000, default 200,000), `settings-max-drawn-links` (50
  to 20,000, default 3,000), `settings-max-upload-mb` (1 to 100, default 25) and
  `settings-mongo-timeout` (500 to 300,000 ms, default 15,000). Values are validated in the browser
  first ("Enter a whole number from 100 to 5,000,000."), so an invalid value sends no request.
* **This server.** Read-only facts: `settings-sources-dir`, `settings-remote-mode` ("Local only: this
  computer" or "Remote: reachable from other machines") and `settings-writes-allowed` ("Allowed" or
  "Read-only").
* **Save bar.** `.savebar[data-state]` is `clean`, `dirty`, `saving` or `readonly`;
  `settings-save-status` reads "All changes saved.", "You have unsaved changes.", "Saving..." or
  "Read-only: settings cannot be changed on this server."; it says "All changes saved." only after
  the write queue is empty. `settings-discard` ("Discard changes") shows only while there are
  changes. Enter in a text, number or password field saves. `settings-save` ("Save settings") shows
  "Settings saved." on success.
* **Conflicts.** Saving re-reads the stored settings first. If they changed elsewhere, a dialog
  (`confirm-dialog`, "Settings were changed elsewhere") offers Cancel, `conflict-reload` ("Show their
  settings") and `settings-conflict-overwrite` ("Save mine anyway"); the last stores both the theme
  and the limits.
* **Leaving.** With unsaved changes an in-app link opens `confirm-dialog` "Discard unsaved changes?"
  and the native `beforeunload` prompt guards reload and close.
