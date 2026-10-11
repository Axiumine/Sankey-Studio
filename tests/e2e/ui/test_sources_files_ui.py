"""B5, part 1: the five source tabs, the Text file tab and the Upload tab (UI.md flow F8).

Switching tabs, choosing a file that lives in the sources folder, uploading a CSV and a SankeyMATIC
file, the replace dialog, an unsupported file, and the promise that a saved graph keeps its file.
Uploads change the sources folder of the server, so every test has its own server (``live_server``
comes before ``page`` in the signatures: the server must outlive the browser context).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from tests.e2e.support.builders import csv_text, unique_name
from tests.e2e.support.clients import json_of, upload_source
from tests.e2e.support.ui_a_charts import ChartDom
from tests.e2e.support.ui_a_editor import EditGraphPage, EditorPage
from tests.e2e.support.ui_a_sources import SourcePanel

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

FLOWS = csv_text(
    [
        ("Salary", "Account", 3000, "Income"),
        ("Account", "Rent", 1200, "Housing"),
        ("Account", "Food", 640, "Food"),
    ],
    header=("from", "to", "amount", "kind"),
)
FLOWS_SIZE = f"{len(FLOWS.encode())} B"
SANKEYMATIC = "Salary [3000] Account\nAccount [1200] Rent | Housing\nAccount [640] Food | Food\n"
FLOWS_STATS = {"nodes": 4, "links": 3, "total_in": 3000, "total_out": 1840, "columns": 3}


def editor_on(page: WatchedPage, server: LiveServer) -> tuple[EditorPage, SourcePanel]:
    editor = EditorPage(page, server)
    editor.goto()
    return editor, SourcePanel(page)


# ------------------------------------------------------------------------------ tabs, text file


def test_each_tab_shows_its_own_input_and_a_file_of_the_sources_folder_is_chosen_and_kept(
    live_server: LiveServer, page: WatchedPage, api: httpx.Client
) -> None:
    editor, source = editor_on(page, live_server)
    source.expect_only_tab("paste")
    for tab in ("text", "upload", "manual", "mongo", "paste"):
        source.open_tab(tab)
        source.expect_only_tab(tab)
    source.open_tab("text")
    expect(source.tid("source-file-select")).to_contain_text("No files yet")
    expect(page.get_by_text("The sources folder is empty. Upload a file to start.")).to_be_visible()
    source.open_tab("mongo")
    no_connections = source.tid("mongo-no-connections")
    expect(no_connections).to_contain_text("No MongoDB connections yet")
    expect(no_connections.get_by_role("link", name="Open Settings")).to_have_attribute(
        "href", "/settings"
    )
    expect(no_connections.get_by_role("button", name="Check again")).to_be_visible()

    upload_source(api, "flows.csv", FLOWS)
    page.reload()
    editor.expect_ready()
    editor.name_field.fill(unique_name("From a file"))
    source.open_tab("text")
    select = source.tid("source-file-select")
    expect(select).to_contain_text(f"flows.csv ({FLOWS_SIZE})")
    select.select_option(label=f"flows.csv ({FLOWS_SIZE})")
    editor.wait_preview()

    editor.expect_stats(**FLOWS_STATS)
    expect(page.get_by_text("Detected: CSV")).to_be_visible()
    graph_id = editor.save()
    stored = json_of(api.get(f"/api/v1/graphs/{graph_id}"))
    assert (stored["source"]["origin"], stored["source"]["path"]) == ("file", "flows.csv")

    page.reload()
    reopened = EditGraphPage(page, live_server)
    reopened.expect_ready()
    expect(source.tid("source-tab-text")).to_have_attribute("aria-selected", "true")
    expect(select).to_have_value("flows.csv")
    reopened.wait_preview()
    reopened.expect_stats(**FLOWS_STATS)


# ------------------------------------------------------------------------------ upload


def test_uploading_a_csv_makes_it_the_source_and_an_existing_name_asks_before_replacing(
    live_server: LiveServer, page: WatchedPage, tmp_path: Path
) -> None:
    editor, source = editor_on(page, live_server)
    flows = tmp_path / "flows.csv"
    flows.write_text(FLOWS)

    source.open_tab("upload")
    source.upload(flows)

    source.expect_uploaded("flows.csv")
    editor.wait_preview()
    expect(source.file_row("flows.csv")).to_contain_text(FLOWS_SIZE)
    expect(source.file_row("flows.csv")).to_contain_text("In use")
    editor.expect_stats(**FLOWS_STATS)
    ChartDom(page).expect_counts(4, 3)
    source.expect_columns(source="from", target="to", value="amount", category="")
    matched = "Matched by name: from as source, to as target, amount as value."
    expect(page.get_by_text(matched)).to_be_visible()
    expect(editor.tid("chart-tab-donut")).to_have_count(0)

    source.pick_column("category", "kind")

    expect(editor.tid("chart-tab-donut")).to_be_visible()
    editor.wait_preview()
    editor.expect_stats(**FLOWS_STATS, categories=3)

    # The same name again: Cancel keeps the file, Replace swaps it for every graph that reads it.
    newer = tmp_path / "newer" / "flows.csv"
    newer.parent.mkdir()
    newer.write_text(csv_text([("A", "B", 5), ("B", "C", 5)]))
    source.upload(newer)
    dialog = editor.tid("confirm-dialog")
    expect(dialog).to_contain_text("Replace the existing file?")
    editor.tid("confirm-dialog-cancel").click()
    expect(dialog).to_be_hidden()
    expect(source.file_row("flows.csv")).to_contain_text(FLOWS_SIZE)
    editor.expect_stats(**FLOWS_STATS, categories=3)

    source.upload(newer)
    editor.tid("confirm-dialog-confirm").click()

    source.expect_uploaded("flows.csv")
    editor.wait_preview()
    editor.expect_stats(nodes=3, links=2, total_in=5, total_out=5, columns=3)


def test_an_unsupported_file_is_refused_and_a_sankeymatic_file_is_detected_with_categories(
    live_server: LiveServer, page: WatchedPage, tmp_path: Path, api: httpx.Client
) -> None:
    editor, source = editor_on(page, live_server)
    source.open_tab("upload")
    program = tmp_path / "x.exe"
    program.write_text("MZ")

    source.upload(program)

    expect(source.upload_status).to_have_text(
        "x.exe is not a supported file. Use .csv, .tsv, .txt, .json, .ndjson, .sankey."
    )
    assert json_of(api.get("/api/v1/sources/files")) == []

    flows = tmp_path / "flows.sankey"
    flows.write_text(SANKEYMATIC)
    source.upload(flows)

    source.expect_uploaded("flows.sankey")
    editor.wait_preview()
    expect(page.get_by_text("Detected: SankeyMATIC text")).to_be_visible()
    expect(source.tid("source-column-source")).to_be_hidden()
    editor.expect_stats(**FLOWS_STATS, categories=2)
    expect(editor.tid("chart-tab-donut")).to_be_visible()
