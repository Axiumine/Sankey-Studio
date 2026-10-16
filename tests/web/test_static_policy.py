# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The frontend files as a whole: policy beyond ``test_templates_policy.py`` (which stays the home
of the SPEC section 5 banned-construct grep; the rules here are added on top, not repeated).

Covers ``templates/`` and ``static/`` (``vendor/`` skipped): extra banned constructs, no colour
literal outside ``tokens.css``, the tokens equal ``render/palette.py``, JavaScript files of at most
300 lines that ``node --check`` accepts, every reference from a template, script or style sheet
resolves to a file the app serves, no external URL, no inline script, and every ``data-testid`` is
in API.md section 5 or in ``static/testids-extra.txt``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Final, NamedTuple

import pytest

from sankey_studio.render.palette import TOKENS
from sankey_studio.web.app import STATIC_DIR
from sankey_studio.web.routers.pages import TEMPLATES_DIR
from tests.web.test_pages_support import parse, parse_text, unversioned
from tests.web.test_routes_graphs_support import PLAIN, save
from tests.web.test_static_policy_support import (
    API_TESTIDS,
    TESTID_NAME,
    extra_testids,
    own_files,
    rel,
    used_testids,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.web.conftest import AppFactory, WebApp

MAX_JS_LINES: Final = 300
ROOTS: Final = [TEMPLATES_DIR, STATIC_DIR]
ROOT_IDS: Final = ["templates", "static"]
#: The only URLs allowed in the files: XML namespaces (never fetched).
XML_NAMESPACES: Final = frozenset(
    {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink", "http://www.w3.org/1999/xhtml"}
)
VENDOR_PATH: Final = "/static/vendor/plotly.min.js"
PAGE_MODULES: Final = {
    "/": "library",
    "/graphs/new": "editor",
    "/settings": "settings",
    "/graphs/{id}": "viewer",
    "/graphs/{id}/edit": "editor",
    "/compare?ids={id}": "compare",
}


class Rule(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    suffixes: frozenset[str]


def rule(name: str, pattern: str, *suffixes: str) -> Rule:
    return Rule(name, re.compile(pattern, re.IGNORECASE), frozenset(suffixes))


EVERYWHERE = (".html", ".js", ".css", ".svg")
EXTRA_RULES: Final = [
    rule("javascript: url", r"\bjavascript\s*:", *EVERYWHERE),
    rule("string timer", r"""\bset(?:Timeout|Interval)\s*\(\s*["'`]""", ".js"),
    rule("document.cookie", r"\bdocument\s*\.\s*cookie\b", ".js"),
    rule("srcdoc", r"\bsrcdoc\b", ".js", ".html"),
    rule("window.open", r"\bwindow\s*\.\s*open\s*\(", ".js"),
    rule("iframe", r"<iframe\b", ".html", ".js"),
    rule("debugger", r"\bdebugger\b", ".js"),
    rule("console.log", r"\bconsole\s*\.\s*(?:log|debug|info)\s*\(", ".js"),
    rule("inline style attribute", r"""<[a-z][^>]*\sstyle\s*=\s*["']""", ".html"),
    rule("html import", r"""<link\b[^>]*\brel\s*=\s*["']import["']""", ".html"),
    rule("css expression", r"\bexpression\s*\(|(?<![\w-])behavior\s*:", ".css"),
]
COLOUR: Final = re.compile(
    r"(?<![\w&])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3})\b|\b(?:rgba?|hsla?)\(", re.IGNORECASE
)
URL: Final = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
IMPORT: Final = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(\s*|\bimport\s+)["']([^"']+)["']""")
STATIC_STRING: Final = re.compile(r"""["'`](/static/[^"'`\s]+)["'`]""")
#: A file a script names relative to itself (it keeps the ``/static/v-<digest>/`` prefix).
MODULE_URL: Final = re.compile(r"""new URL\(\s*["']([^"']+)["']\s*,\s*import\.meta\.url\s*\)""")
CSS_REF: Final = re.compile(r"""url\(\s*["']?([^"')\s]+)["']?\s*\)|@import\s+["']([^"']+)["']""")


def extra_violations(text: str, suffix: str) -> list[str]:
    """The names of the extra rules ``text`` (a file with ``suffix``) breaks."""
    return [r.name for r in EXTRA_RULES if suffix in r.suffixes and r.pattern.search(text)]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("root", ROOTS, ids=ROOT_IDS)
def test_the_shipped_files_break_no_extra_rule(root: Path) -> None:
    broken = {
        rel(path): found
        for path in own_files(root)
        if (found := extra_violations(read(path), path.suffix))
    }
    assert broken == {}


class Snippet(NamedTuple):
    rule: str
    suffix: str
    bad: list[str]
    good: list[str]


SNIPPETS = [
    Snippet(
        "javascript: url",
        ".html",
        ['<a href="javascript:alert(1)">', "JavaScript :x"],
        ["javascripts"],
    ),
    Snippet(
        "string timer",
        ".js",
        ['setTimeout("x()", 5)', "setInterval('x', 5)"],
        ["setTimeout(run, 5)"],
    ),
    Snippet("document.cookie", ".js", ["document.cookie = 'a=b'"], ["document.cookies"]),
    Snippet("srcdoc", ".js", ["frame.srcdoc = x"], ["source"]),
    Snippet("window.open", ".js", ["window.open('/x')"], ["window.opener"]),
    Snippet("iframe", ".html", ["<iframe src='/x'></iframe>"], ["<p>iframes</p>"]),
    Snippet("debugger", ".js", ["debugger;"], ["debuggerless"]),
    Snippet("console.log", ".js", ["console.log(x)", "console . debug (x)"], ["console.error(x)"]),
    Snippet("inline style attribute", ".html", ['<p style="color: red">'], ["<p class='style'>"]),
    Snippet("css expression", ".css", ["a { width: expression(1) }"], ["a { width: 1px }"]),
]


@pytest.mark.parametrize("snippet", SNIPPETS, ids=[s.rule for s in SNIPPETS])
def test_each_extra_rule_flags_its_bad_snippets_and_only_those(snippet: Snippet) -> None:
    for text in snippet.bad:
        assert snippet.rule in extra_violations(text, snippet.suffix), text
    for text in snippet.good:
        assert snippet.rule not in extra_violations(text, snippet.suffix), text


def test_a_rule_only_applies_to_its_file_types() -> None:
    assert extra_violations("debugger;", ".css") == []
    assert extra_violations("debugger;", ".js") == ["debugger"]
    assert "javascript: url" in extra_violations("javascript:x", ".svg")


def test_every_extra_rule_has_a_snippet_table() -> None:
    covered = {s.rule for s in SNIPPETS} | {"html import"}
    assert covered == {r.name for r in EXTRA_RULES}


def test_there_are_javascript_files_to_check() -> None:
    names = {rel(path) for path in own_files(STATIC_DIR, ".js")}
    assert {"js/core/api.js", "js/core/dom.js", "js/editor/store.js"} <= names
    assert {f"js/pages/{page}.js" for page in set(PAGE_MODULES.values())} <= names


def test_every_javascript_file_has_at_most_300_lines() -> None:
    long = {
        rel(path): len(read(path).splitlines())
        for path in own_files(STATIC_DIR, ".js")
        if len(read(path).splitlines()) > MAX_JS_LINES
    }
    assert long == {}


def test_node_accepts_every_module(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for path in own_files(STATIC_DIR, ".js"):
        copy = tmp_path / rel(path).replace("/", "__").replace(".js", ".mjs")
        copy.write_text(read(path), encoding="utf-8")
        result = subprocess.run(  # noqa: S603 - fixed argv: node --check on a temp copy
            [node, "--check", str(copy)], capture_output=True, text=True, check=False, timeout=60
        )
        assert (result.returncode, result.stderr) == (0, ""), rel(path)


def colour_lines(path: Path) -> list[str]:
    """Lines of ``path`` with a colour literal (the theme-color metas are the one exception)."""
    lines = read(path).splitlines()
    return [line for line in lines if COLOUR.search(line) and 'name="theme-color"' not in line]


def test_no_colour_literal_outside_the_token_file() -> None:
    files = [
        path
        for path in [*own_files(TEMPLATES_DIR, ".html"), *own_files(STATIC_DIR, ".css", ".js")]
        if path.name != "tokens.css"
    ]
    assert {rel(path): colour_lines(path) for path in files if colour_lines(path)} == {}
    assert colour_lines(STATIC_DIR / "css" / "tokens.css") != []


def test_the_colour_rule_sees_literals_and_ignores_anchors() -> None:
    for text in ("color: #fff;", "c: #0b0b0b", "c: rgba(0, 0, 0, .1)", "x: hsl(1 2% 3%)"):
        assert COLOUR.search(text), text
    for text in ('href="#main"', "id=a11y-polite", "&#34;", "#state-empty", "var(--ink)"):
        assert not COLOUR.search(text), text


def declarations(css: str, opener: str) -> dict[str, str]:
    """The ``--name: value`` declarations of the first block that follows ``opener``."""
    start = css.index(opener) + len(opener)
    depth, end = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[end], 0)
        end += 1
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", css[start : end - 1]))


DARK_OPENERS: Final = [
    '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {',
    ':root[data-theme="dark"] {',
]


@pytest.mark.parametrize(("theme", "opener"), [("light", ":root {"), ("dark", DARK_OPENERS[1])])
def test_the_ink_and_surface_tokens_equal_the_chart_palette(theme: str, opener: str) -> None:
    css = read(STATIC_DIR / "css" / "tokens.css")
    found = declarations(css, opener)
    palette = TOKENS["light" if theme == "light" else "dark"]
    for name in ("surface", "ink", "muted", "gridline", "baseline"):
        assert found[f"--{name}"] == getattr(palette, name), name
    assert found["--ink-secondary"] == palette.ink_secondary


def test_the_two_dark_blocks_are_identical() -> None:
    css = read(STATIC_DIR / "css" / "tokens.css")
    media, attribute = (declarations(css, opener) for opener in DARK_OPENERS)
    assert media == attribute
    assert len(media) > 20


def test_the_theme_color_metas_are_the_surface_tokens() -> None:
    html = read(TEMPLATES_DIR / "base.html")
    metas = {
        scheme: content
        for content, scheme in re.findall(
            r'name="theme-color" content="(#\w+)" media="\(prefers-color-scheme: (\w+)\)"', html
        )
    }
    assert metas == {"light": TOKENS["light"].surface, "dark": TOKENS["dark"].surface}


def test_no_url_leaves_the_origin_except_xml_namespaces() -> None:
    found = {
        rel(path): sorted(set(URL.findall(read(path))) - XML_NAMESPACES)
        for root in ROOTS
        for path in own_files(root)
    }
    assert {name: urls for name, urls in found.items() if urls} == {}


def test_the_url_rule_flags_hosts_and_allows_namespaces() -> None:
    assert URL.findall("a http://x.example/a b") == ["http://x.example/a"]
    assert set(URL.findall('xmlns="http://www.w3.org/2000/svg"')) <= XML_NAMESPACES


def resolve(base: Path, ref: str) -> Path | None:
    """The file a ``ref`` written in ``base`` points at (``None`` for a served route/URL)."""
    if ref.startswith(("data:", "#")) or ref == VENDOR_PATH:
        return None
    if ref.startswith("/static/"):
        return STATIC_DIR / ref.removeprefix("/static/").split("?")[0]
    return (base.parent / ref.split("?", maxsplit=1)[0]).resolve()


def test_every_import_and_static_url_in_a_script_resolves() -> None:
    missing: list[str] = []
    for path in own_files(STATIC_DIR, ".js"):
        text = read(path)
        for ref in [*IMPORT.findall(text), *STATIC_STRING.findall(text), *MODULE_URL.findall(text)]:
            target = resolve(path, ref)
            if target is not None and not target.is_file():
                missing.append(f"{rel(path)} -> {ref}")
    assert missing == []


def test_every_url_and_import_in_a_style_sheet_resolves() -> None:
    missing = []
    for path in own_files(STATIC_DIR, ".css"):
        for url, imported in CSS_REF.findall(read(path)):
            target = resolve(path, url or imported)
            if target is not None and not target.is_file():
                missing.append(f"{rel(path)} -> {url or imported}")
    assert missing == []


def test_the_import_rule_reads_the_forms_of_import() -> None:
    text = (
        'import { a } from "./a.js"; import "./b.js"; const m = import("./c.js");'
        ' export { d } from "../d.js"'
    )
    assert IMPORT.findall(text) == ["./a.js", "./b.js", "./c.js", "../d.js"]
    assert STATIC_STRING.findall('const U = "/static/vendor/plotly.min.js";') == [VENDOR_PATH]
    sheet = 'ensure(new URL("../../css/a.css", import.meta.url).href); new URL("x", base)'
    assert MODULE_URL.findall(sheet) == ["../../css/a.css"]


def test_scripts_name_static_files_relative_to_themselves() -> None:
    """An absolute ``/static/...`` path would skip the version prefix (a stale browser copy)."""
    absolute = {
        rel(path): refs
        for path in own_files(STATIC_DIR, ".js")
        if (refs := sorted(set(STATIC_STRING.findall(read(path))) - {VENDOR_PATH}))
    }
    assert absolute == {}


class Rendered(NamedTuple):
    path: str
    html: str


@pytest.fixture
def rendered(web: WebApp) -> list[Rendered]:
    """Every page, as HTML, for a saved graph."""
    graph_id = save(web, "Budget", *PLAIN).id
    paths = [template.format(id=graph_id) for template in PAGE_MODULES]
    return [Rendered(path, web.client.get(path).text) for path in paths]


def static_refs(html: str) -> list[str]:
    """The ``/static/`` URLs of the ``href`` and ``src`` attributes of a page."""
    return re.findall(r"""\b(?:href|src)="(/static/[^"]*)\"""", html)


def test_every_static_file_a_page_links_is_served(web: WebApp, rendered: list[Rendered]) -> None:
    kinds = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
    for page in rendered:
        refs = static_refs(page.html)
        assert len(refs) >= 8, page.path
        for ref in refs:
            response = web.client.get(ref)
            kind = kinds["." + unversioned(ref).rsplit(".", 1)[-1]]
            assert response.status_code == 200, (page.path, ref)
            assert response.headers["content-type"].startswith(kind), ref


def test_every_script_of_a_page_is_a_module_file_or_the_json_block(
    rendered: list[Rendered],
) -> None:
    for page in rendered:
        scripts = parse_text(page.html).scripts
        assert len(scripts) == 4, page.path
        for script in scripts:
            is_json = script.attrs.get("type") == "application/json"
            assert is_json or (script.attrs.get("src") and script.text.strip() == ""), page.path


@pytest.mark.parametrize("template", list(PAGE_MODULES))
def test_a_page_loads_its_own_module_and_style_sheet(web: WebApp, template: str) -> None:
    graph_id = save(web, "Budget", *PLAIN).id
    html = web.client.get(template.format(id=graph_id)).text
    module = PAGE_MODULES[template]
    refs = [unversioned(ref) for ref in static_refs(html)]
    assert f"/static/js/pages/{module}.js" in refs
    assert f"/static/css/pages/{module}.css" in refs
    assert refs.index("/static/js/core/theme-init.js") < refs.index(f"/static/js/pages/{module}.js")


def test_every_test_id_in_the_files_is_in_the_api_list_or_the_extra_list() -> None:
    known = API_TESTIDS | extra_testids()
    unknown = {
        rel(path): sorted(used_testids(read(path)) - known)
        for root in ROOTS
        for path in own_files(root, ".html", ".js")
    }
    assert {name: ids for name, ids in unknown.items() if ids} == {}


def test_every_test_id_of_a_rendered_page_is_known(make_app: AppFactory, tmp_path: Path) -> None:
    known = API_TESTIDS | extra_testids()
    for mode in ("local", "remote_read_only"):
        web = make_app(mode=mode)
        graph_id = save(web, "Budget", *PLAIN).id
        for template in PAGE_MODULES:
            page = parse(web.client.get(template.format(id=graph_id)))
            ids = {value for name, value in page.attrs if name == "data-testid" and value}
            assert ids <= known, (mode, template, ids - known)
            assert {"app-root", "nav-library", "nav-new", "nav-settings", "theme-switch"} <= ids
    assert tmp_path.is_dir()


def test_the_extra_list_is_well_formed() -> None:
    lines = [
        line.strip()
        for line in (STATIC_DIR / "testids-extra.txt").read_text(encoding="utf-8").splitlines()
    ]
    names = [line for line in lines if line and not line.startswith("#")]
    assert names
    assert len(names) == len(set(names))
    assert all(TESTID_NAME.fullmatch(name) for name in names)
    assert not set(names) & API_TESTIDS


def test_the_api_list_has_the_names_of_the_contract() -> None:
    assert len(API_TESTIDS) == 127
    assert {
        "app-root",
        "toast",
        "loading",
        "theme-switch",
        "remote-banner",
        "delete-confirm",
    } <= API_TESTIDS
    assert all(TESTID_NAME.fullmatch(name) for name in API_TESTIDS)


class UseCase(NamedTuple):
    text: str
    ids: set[str]


USES = [
    UseCase('<a data-testid="nav-new">', {"nav-new"}),
    UseCase('<a data-testid="{{ x }}">', set()),
    UseCase("h('div', {'data-testid': 'graph-card'})", {"graph-card"}),
    UseCase('h("div", { "data-testid": "legend-item" })', {"legend-item"}),
    UseCase('h("div", { "data-testid": ids.row ?? null })', set()),
    UseCase(
        'openDialog({ testid: "confirm-dialog", confirmTestid: "delete-confirm" })',
        {"confirm-dialog", "delete-confirm"},
    ),
    UseCase('el.dataset.testid = "stats"', {"stats"}),
    UseCase("el.setAttribute('data-testid', 'warnings')", {"warnings"}),
    UseCase(
        'createTable({ testids: { table: "entries-table", row: "entries-row" } })',
        {"entries-table", "entries-row"},
    ),
    UseCase("h('p', { testid: `row-${i}` })", set()),
]


@pytest.mark.parametrize("use", USES, ids=[str(i) for i in range(len(USES))])
def test_the_test_id_finder_reads_every_form_and_skips_dynamic_names(use: UseCase) -> None:
    assert used_testids(use.text) == use.ids
