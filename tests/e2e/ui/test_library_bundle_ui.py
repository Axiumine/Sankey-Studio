"""E2E.md B.6, bundles: export the library to a file and import a file back, through the browser.

Export is a real download (``sankey-studio-graphs.json``). Import goes through the real file
chooser, a confirmation dialog and a report. A second server stands for "another machine".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from playwright.sync_api import expect

from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import json_of, make_client, seed_graph
from tests.e2e.support.ui_b_common import DESKTOP, download_text
from tests.e2e.support.ui_b_folders import FolderLibrary, seed_filed_graph, seed_folder
from tests.e2e.support.ui_b_library import LibraryPage

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.session import PageOpener
    from tests.e2e.support.watch import WatchedPage

BUNDLE_FORMAT: Final = "sankey-studio/graphs"
EXPORT_NAME: Final = "sankey-studio-graphs.json"


def export_bundle(library: LibraryPage) -> dict[str, Any]:
    """Click the export button and return the parsed file."""
    name, text = download_text(library.page, library.tid("library-export").click)
    assert name == EXPORT_NAME
    return dict(json.loads(text))


def choose_bundle(library: LibraryPage, path: Path) -> None:
    """Pick ``path`` in the real file chooser that the Import label opens."""
    with library.page.expect_file_chooser() as chooser:
        library.tid("library-import").click()
    chooser.value.set_files(path)


def write_bundle(
    directory: Path, graphs: list[Any], name: str = "bundle.json", folders: list[Any] | None = None
) -> Path:
    path = directory / name
    bundle: dict[str, Any] = {"format": BUNDLE_FORMAT, "version": 2, "graphs": graphs}
    if folders is not None:
        bundle["folders"] = folders
    path.write_text(json.dumps(bundle))
    return path


def seed_three(api: httpx.Client, prefix: str) -> list[dict[str, Any]]:
    draft = graph_draft(BUDGET_CATEGORISED.csv)
    return [seed_graph(api, f"{prefix} {n}", draft, tags=["bundle"]) for n in (1, 2, 3)]


def import_and_report(library: LibraryPage, path: Path) -> Any:
    """Choose ``path``, confirm and return the report dialog (shown on screen)."""
    choose_bundle(library, path)
    library.tid("import-confirm").click()
    report = library.tid("import-report")
    expect(report).to_be_visible()
    return report


def close_report(library: LibraryPage, expected_cards: int) -> None:
    """Close the report and wait for the list that was reloaded behind it."""
    library.tid("import-report").get_by_role("button", name="Done").click()
    expect(library.tid("import-report")).to_be_hidden()
    expect(library.cards).to_have_count(expected_cards)


def expect_refused_files(library: LibraryPage, directory: Path) -> None:
    """Files that are not bundles get a sentence in a toast and never open the import dialog."""
    cases = {
        "notes.json": ("this is not json", "This file is not valid JSON."),
        "other.json": ('{"hello": 1}', "This is not a Sankey Studio bundle."),
        "empty.json": (
            json.dumps({"format": BUNDLE_FORMAT, "version": 2, "graphs": []}),
            "This bundle holds no graphs",
        ),
    }
    for filename, (content, message) in cases.items():
        path = directory / filename
        path.write_text(content)
        choose_bundle(library, path)
        library.expect_toast(message, "error")
        expect(library.tid("import-dialog")).to_have_count(0)
        library.toasts().filter(has_text=message).get_by_role("button").first.click()


# ------------------------------------------------------------------------------ export


def test_export_all_selected_and_results_download_exactly_what_the_button_says(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    prefix = unique_name("Exp")
    graphs = seed_three(api, prefix)
    seed_graph(api, unique_name("Other"))
    library = LibraryPage(page, live_server)
    library.goto()
    total = json_of(api.get("/api/v1/graphs"))["total"]
    expect(library.tid("library-export")).to_have_text(f"Export all ({total})")
    bundle = export_bundle(library)
    assert bundle["format"] == BUNDLE_FORMAT
    assert bundle["version"] == 2
    assert len(bundle["graphs"]) == total
    exported = next(g for g in bundle["graphs"] if g["name"] == f"{prefix} 1")
    assert exported["id"] == graphs[0]["id"]
    assert exported["tags"] == ["bundle"]
    assert exported["source"]["content"] == BUDGET_CATEGORISED.csv  # the data travels with it
    library.goto(f"?q={prefix}")
    expect(library.tid("library-export")).to_have_text("Export results (3)")
    library.tick(f"{prefix} 1").check()
    library.tick(f"{prefix} 3").check()
    expect(library.tid("library-export")).to_have_text("Export selected (2)")
    selected = export_bundle(library)
    assert [g["name"] for g in selected["graphs"]] == [f"{prefix} 1", f"{prefix} 3"]
    library.tid("selection-clear").click()
    assert len(export_bundle(library)["graphs"]) == 3


# ------------------------------------------------------------------------------ import


def test_a_bundle_exported_on_one_server_imports_into_an_empty_one_with_new_ids(
    make_server: ServerFactory, open_page: PageOpener, tmp_path: Path
) -> None:
    source, target = make_server(), make_server()
    with make_client(source) as source_api:
        originals = seed_three(source_api, "Travel")
    exporter = LibraryPage(open_page(source, color_scheme="light", viewport=DESKTOP), source)
    exporter.goto()
    path = write_bundle(tmp_path, export_bundle(exporter)["graphs"])
    importer = LibraryPage(open_page(target, color_scheme="light", viewport=DESKTOP), target)
    importer.goto()
    expect(importer.tid("library-empty")).to_be_visible()
    expect(importer.tid("library-export")).to_be_disabled()  # nothing to export yet
    choose_bundle(importer, path)
    dialog = importer.tid("import-dialog")
    expect(dialog).to_contain_text("bundle.json")
    expect(dialog).to_contain_text("This bundle holds 3 graphs.")
    expect(dialog).to_contain_text("Imported graphs always get new ids")
    importer.tid("import-confirm").click()
    report = importer.tid("import-report")
    expect(report).to_contain_text("Imported 3 graphs.")
    expect(report).not_to_contain_text("could not be imported")
    close_report(importer, 3)
    with make_client(target) as target_api:
        copies = json_of(target_api.get("/api/v1/graphs"))["items"]
    assert {g["name"] for g in copies} == {g["name"] for g in originals}
    assert not {g["id"] for g in copies} & {g["id"] for g in originals}
    assert all(g["tags"] == ["bundle"] and g["revision"] == 1 for g in copies)


def test_cancel_imports_nothing_broken_graphs_are_reported_and_non_bundles_are_refused(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client, tmp_path: Path
) -> None:
    good = seed_graph(api, unique_name("Good"))
    exported = json_of(api.get("/api/v1/graphs/export", params={"ids": good["id"]}))["graphs"]
    library = LibraryPage(page, live_server)
    library.goto()
    choose_bundle(library, write_bundle(tmp_path, exported, "good.json"))  # cancel: nothing happens
    expect(library.tid("import-dialog")).to_contain_text("This bundle holds 1 graph.")
    library.tid("import-dialog").get_by_role("button", name="Cancel").click()
    expect(library.tid("import-dialog")).to_be_hidden()
    expect(library.tid("import-report")).to_have_count(0)
    assert json_of(api.get("/api/v1/graphs"))["total"] == 1
    mixed = write_bundle(tmp_path, [*exported, {"name": "Broken"}], "mixed.json")
    report = import_and_report(library, mixed)  # one good, one unreadable
    expect(report).to_contain_text("Imported 1 graph.")
    expect(report).to_contain_text("1 graph could not be imported.")
    problems = report.get_by_role("list", name="Import problems")
    expect(problems.get_by_role("listitem")).to_have_count(1)
    expect(problems).to_contain_text("graph 2")
    close_report(library, 2)
    assert json_of(api.get("/api/v1/graphs"))["total"] == 2
    broken = write_bundle(tmp_path, [{"name": "Broken"}], "broken.json")
    report = import_and_report(library, broken)  # nothing usable at all
    expect(report).to_contain_text("Nothing was imported")
    expect(report).to_contain_text("Imported 0 graphs.")
    expect(report).to_contain_text("1 graph could not be imported.")
    close_report(library, 2)
    assert json_of(api.get("/api/v1/graphs"))["total"] == 2
    expect_refused_files(library, tmp_path)  # and files that are no bundles at all


# ------------------------------------------------------------------------------ collections


def test_a_collection_exports_with_its_path_and_imports_as_the_same_tree(
    make_server: ServerFactory, open_page: PageOpener, tmp_path: Path
) -> None:
    source, target = make_server(), make_server()
    with make_client(source) as source_api:
        top = seed_folder(source_api, "Finance")
        inner = seed_folder(source_api, "Q3 reports", top["id"])
        seed_filed_graph(source_api, "Inside", inner["id"])
        seed_graph(source_api, "Outside")
    exporter = FolderLibrary(open_page(source, color_scheme="light", viewport=DESKTOP), source)
    exporter.goto(f"?folder={inner['id']}")
    expect(exporter.tid("library-export")).to_have_text("Export this collection (1)")
    bundle = export_bundle(exporter)
    assert [graph["name"] for graph in bundle["graphs"]] == ["Inside"]  # not the one outside
    assert [folder["name"] for folder in bundle["folders"]] == ["Finance", "Q3 reports"]
    path = write_bundle(tmp_path, bundle["graphs"], folders=bundle["folders"])
    importer = FolderLibrary(open_page(target, color_scheme="light", viewport=DESKTOP), target)
    importer.goto()
    choose_bundle(importer, path)
    dialog = importer.tid("import-dialog")
    expect(dialog).to_contain_text("This bundle holds 1 graph and 2 collections.")
    expect(dialog).to_contain_text("a collection that already exists in the same place is reused")
    importer.tid("import-confirm").click()
    report = importer.tid("import-report")
    expect(report).to_contain_text("Imported 1 graph and 2 collections.")
    report.get_by_role("button", name="Done").click()
    expect(importer.folder_card("Finance")).to_be_visible()  # the list and the tree were reloaded
    importer.open_folder("Finance")
    importer.open_folder("Q3 reports")
    importer.expect_names(["Inside"])
    expect(importer.crumbs).to_have_text(["Library", "Finance", "Q3 reports"])
