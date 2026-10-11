"""Bidirectional controls, the theme bootstrap and the scrollbar rules of the shared frontend.

``static/js/core/text.js`` removes bidirectional embeddings, overrides and isolates from every
string that ``h()`` turns into a text node or an attribute (and from the few ``textContent`` sinks
of the core modules). The server renders the stored theme, so ``theme-init.js`` only lets a cached
device choice win on a read-only server. The page scrolls in a permanent scrollbar track, and an
open dialog locks it on ``<html>``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Final

import pytest

from sankey_studio.web.app import STATIC_DIR

if TYPE_CHECKING:
    from pathlib import Path

CORE: Final = STATIC_DIR / "js" / "core"
CSS: Final = STATIC_DIR / "css"
#: The characters that change how the text around them is drawn, and two that are harmless.
STRIPPED: Final = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
#: Control characters have no glyph (tofu boxes): NUL, bell, backspace, VT, FF, escape, US, DEL and
#: the C1 block ends. Tab, line feed and carriage return are white space and stay.
CONTROLS: Final = "\u0000\u0007\u0008\u000b\u000c\u000e\u001b\u001f\u007f\u0080\u0085\u009f"
KEPT: Final = "\u200e\u200f\u200b\u00ad\t\n\r\u00a0~"
SAMPLE: Final = f"live {STRIPPED}gpj.exe{CONTROLS}{KEPT} שלום سلام \U0001f600"
CLEAN: Final = f"live gpj.exe{KEPT} שלום سلام \U0001f600"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_strip_bidi_removes_the_controls_and_keeps_every_other_character(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = tmp_path / "text.mjs"
    module.write_text(read(CORE / "text.js"), encoding="utf-8")
    script = tmp_path / "run.mjs"
    script.write_text(
        f"import {{ stripBidi }} from {str(module)!r};\n"
        "const input = JSON.parse(process.argv[2]);\n"
        "const out = [stripBidi(input), stripBidi(42), stripBidi(null)];\n"
        "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603 - fixed argv: node on two temp files
        [node, str(script), json.dumps(SAMPLE)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert json.loads(result.stdout) == [CLEAN, "42", "null"]


@pytest.mark.parametrize("name", ["dom", "boot", "a11y", "form"])
def test_the_modules_that_write_user_text_use_strip_bidi(name: str) -> None:
    source = read(CORE / f"{name}.js")
    assert 'import { stripBidi } from "./text.js";' in source
    assert source.count("stripBidi(") >= 2


def test_h_strips_text_nodes_and_every_attribute_but_not_input_values() -> None:
    source = read(CORE / "dom.js")
    assert "document.createTextNode(stripBidi(child))" in source
    assert "document.createTextNode(String(child))" not in source
    attribute_writes = re.findall(r"el\.setAttribute\((.*)\);", source)
    assert attribute_writes, "dom.js sets attributes"
    assert all("stripBidi(" in write for write in attribute_writes if "key" in write)
    assert "el[key] = value;" in source  # the value of an input is what the user is editing


def test_the_theme_bootstrap_lets_the_device_win_only_on_a_read_only_server() -> None:
    source = read(CORE / "theme-init.js")
    assert 'root.dataset.themeSource !== "device"' in source
    assert source.index("themeSource") < source.index("localStorage.getItem")
    assert "sankey-studio.theme" in source


def test_the_theme_module_no_longer_asks_the_server_on_the_first_visit() -> None:
    for path in CORE.glob("*.js"):
        assert "syncThemeFromServer" not in read(path), path.name


def test_the_page_always_has_a_scrollbar_track_and_a_dialog_locks_it_on_html() -> None:
    css = re.sub(r"/\*.*?\*/", "", read(CSS / "base.css"), flags=re.DOTALL)
    html_rule = re.search(r"^html \{(.*?)^\}", css, re.DOTALL | re.MULTILINE)
    assert html_rule is not None
    assert "overflow-y: scroll;" in html_rule.group(1)
    assert "scrollbar-gutter" not in html_rule.group(1)
    modal = re.search(r"^html\.is-modal \{(.*?)^\}", css, re.DOTALL | re.MULTILINE)
    assert modal is not None
    assert "overflow: hidden;" in modal.group(1)
    assert "scrollbar-gutter: stable;" in modal.group(1)
    assert "body.is-modal" not in css
    assert 'document.documentElement.classList.toggle("is-modal", on)' in read(CORE / "dialog.js")
