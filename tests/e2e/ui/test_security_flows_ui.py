# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.12, hostile text typed into the editor and carried into files.

The page tests seed the graph through the API; here the person types it, saves it, reloads it and
downloads it, and the downloads must be inert too.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import pytest
from playwright.sync_api import expect

from tests.e2e.support import ui_b_hostile as hostile
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.ui_a_viewer import open_export_menu
from tests.e2e.support.ui_b_common import download_text
from tests.e2e.support.ui_b_editor import EditorPage
from tests.e2e.support.ui_b_viewer import ViewerPage
from tests.e2e.support.uiwait import wait_preview

if TYPE_CHECKING:
    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

UNSAFE_IN_FILE_NAMES = '<>"/\\:|?*\r\n'
SVG_NS = "{http://www.w3.org/2000/svg}"


def type_hostile_graph(editor: EditorPage) -> None:
    editor.set_details(name=hostile.NAME, description=hostile.DESCRIPTION, tags=(hostile.TAG,))
    editor.source.fill(hostile.hostile_csv())
    wait_preview(editor.page)
    editor.open_section("style")
    editor.tid("style-title").fill(hostile.TITLE)
    wait_preview(editor.page)


def test_hostile_text_typed_into_the_editor_stays_text_through_save_reload_and_storage(
    page: WatchedPage, live_server: LiveServer
) -> None:
    inert = hostile.Inert.watch(page)
    editor = EditorPage(page, live_server, None)
    editor.goto()
    type_hostile_graph(editor)
    shown = hostile.literal_text(editor.tid("sankey-chart"))
    for label in hostile.LITERAL_NODES:
        assert label in shown
    expect(editor.heading).to_have_text(re.compile(r"^New graph"))
    inert.check()
    editor.save()
    page.wait_for_url("**/graphs/*/edit")
    expect(editor.status).to_contain_text("All changes saved")
    page.reload()
    editor.page.locator("#page-root[data-ready=true]").wait_for()
    editor.expect_name(hostile.NAME)
    expect(editor.heading).to_have_text(f"Edit {hostile.NAME}")
    description = editor.description_value()
    assert len(description) == len(hostile.DESCRIPTION)  # nothing was cut or escaped
    expect(editor.source).to_have_value(hostile.hostile_csv())
    inert.check()
    editor.expect_settled()
    with make_client(live_server) as api:  # and the server holds exactly what was typed
        stored = json_of(api.get("/api/v1/graphs", params={"limit": 5}))["items"]
        assert [item["name"] for item in stored] == [hostile.NAME]
        full = json_of(api.get(f"/api/v1/graphs/{stored[0]['id']}"))
    assert full["tags"] == [hostile.TAG]
    assert full["description"] == hostile.DESCRIPTION
    assert full["style"]["title"] == hostile.TITLE
    assert full["source"]["content"] == hostile.hostile_csv()


# ------------------------------------------------------------------------------ downloads


@pytest.mark.slow
def test_the_downloads_have_safe_names_and_the_svg_has_no_live_markup(
    page: WatchedPage, live_server: LiveServer
) -> None:
    with make_client(live_server) as api:
        created = json_of(api.post("/api/v1/graphs", json=hostile.hostile_body()), 201)
    viewer = ViewerPage(page, live_server, created["id"])
    viewer.goto()
    open_export_menu(viewer)
    name, text = download_text(page, viewer.tid("export-csv").click)
    assert name.endswith(".csv")
    assert not set(name) & set(UNSAFE_IN_FILE_NAMES), f"unsafe file name {name!r}"
    lines = text.splitlines()
    assert lines[0] == "source,target,value,category"
    assert any(line.startswith((f'"{hostile.IMG}"', hostile.IMG)) for line in lines)
    # (a data export keeps the stored characters; only the drawn text drops direction overrides)
    name, text = download_text(page, viewer.tid("export-sankey-svg").click)
    assert name.endswith(".svg")
    assert not set(name) & set(UNSAFE_IN_FILE_NAMES), f"unsafe file name {name!r}"
    assert text.lstrip().startswith("<svg")
    root = ET.fromstring(text)  # noqa: S314 - our own server's output in a test
    tags = {element.tag.removeprefix(SVG_NS).lower() for element in root.iter()}
    assert not tags & {"script", "img", "iframe", "foreignobject", "b"}, tags
    for element in root.iter():
        assert not [key for key in element.attrib if key.lower().startswith("on")], element.tag
    drawn = "\n".join(element.text or "" for element in root.iter() if element.text)
    assert hostile.IMG in drawn  # the label is there, as characters
    assert hostile.RLO not in text
    assert "<img" not in text.lower()  # the label is escaped (&lt;img ...), never live markup
    assert "<script" not in text.lower()
