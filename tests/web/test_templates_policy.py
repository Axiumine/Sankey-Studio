"""SPEC section 5: no banned construct in ``templates/`` and ``static/`` (a grep over every file).

The wave-3 frontend replaces both directories and this test keeps passing or fails the build.
The rules are the section-5 list (``innerHTML``, ``outerHTML``, ``insertAdjacentHTML``,
``document.write``, ``eval``, ``new Function``, ``|safe``) plus the three Semgrep template rules
(inline script, inline handler) and the "local assets only" rule: an asset URL that leaves the
origin (``<script src="https://...">``, ``url(//cdn...)``, ``@import``) is a violation too.
``static/vendor/`` is skipped, as in ``.semgrepignore``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, NamedTuple

import pytest

from sankey_studio.web.app import STATIC_DIR
from sankey_studio.web.routers.pages import TEMPLATES_DIR

if TYPE_CHECKING:
    from pathlib import Path

TEXT_SUFFIXES: Final = frozenset({".html", ".htm", ".js", ".mjs", ".css", ".svg", ".jinja", ".j2"})
SKIPPED_DIRS: Final = frozenset({"vendor"})
_URL: Final = r"""["']?\s*(?:https?:)?//"""


class Rule(NamedTuple):
    name: str
    pattern: re.Pattern[str]


def rule(name: str, pattern: str) -> Rule:
    return Rule(name, re.compile(pattern, re.IGNORECASE))


RULES: Final = [
    rule("innerHTML", r"\binnerHTML\b"),
    rule("outerHTML", r"\bouterHTML\b"),
    rule("insertAdjacentHTML", r"\binsertAdjacentHTML\b"),
    rule("document.write", r"\bdocument\s*\.\s*write(?:ln)?\b"),
    rule("eval", r"\beval\b"),
    rule("new Function", r"\bnew\s+Function\b"),
    rule("Function()", r"(?<![\w.])Function\s*\("),
    rule("|safe", r"\|\s*safe\b"),
    rule("autoescape off", r"\{%-?\s*autoescape\s+(?:false|off)\b"),
    rule(
        "inline script",
        r"""<script(?![^>]*\bsrc=)(?![^>]*type=["']application/json["'])[^>]*>""",
    ),
    rule("inline handler", r"""\son[a-z]{3,20}\s*=\s*["']"""),
    rule(
        "external asset",
        r"<(?:script|link|img|iframe|source|audio|video|embed|object)\b[^>]*"
        rf"\b(?:src|href|data)\s*=\s*{_URL}"
        rf"|url\(\s*{_URL}|@import\s+(?:url\(\s*)?{_URL}"
        rf"|\bimport\s*\(\s*{_URL}|\bfrom\s+{_URL}|\bfetch\(\s*{_URL}",
    ),
]


def violations(text: str) -> list[str]:
    """The names of the rules ``text`` breaks, in rule order."""
    return [r.name for r in RULES if r.pattern.search(text)]


def scanned_files(root: Path) -> list[Path]:
    """The text files below ``root`` the policy covers (``vendor`` directories are skipped)."""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and not SKIPPED_DIRS.intersection(path.relative_to(root).parts[:-1])
    )


def scan(root: Path) -> dict[str, list[str]]:
    """``{relative path: rule names}`` for every covered file that breaks a rule."""
    found = {
        path.relative_to(root).as_posix(): violations(path.read_text(encoding="utf-8"))
        for path in scanned_files(root)
    }
    return {name: broken for name, broken in found.items() if broken}


@pytest.mark.parametrize("root", [TEMPLATES_DIR, STATIC_DIR], ids=["templates", "static"])
def test_the_shipped_files_break_no_rule(root: Path) -> None:
    assert root.is_dir()
    assert scan(root) == {}


def test_the_policy_covers_the_templates() -> None:
    names = [path.name for path in scanned_files(TEMPLATES_DIR)]
    assert "base.html" in names
    assert all(name.endswith((".html", ".htm", ".jinja", ".j2")) for name in names)


class Snippet(NamedTuple):
    rule: str
    bad: list[str]
    good: list[str]


SNIPPETS = [
    Snippet(
        "innerHTML",
        ["el.innerHTML = x", "a.innerHTML+=y", "el['innerHTML']"],
        ["el.textContent = x", "myinnerHTMLish", "inner HTML"],
    ),
    Snippet("outerHTML", ["el.outerHTML = x"], ["el.outerText = x"]),
    Snippet(
        "insertAdjacentHTML",
        ["el.insertAdjacentHTML('beforeend', x)"],
        ["el.insertAdjacentElement('beforeend', x)"],
    ),
    Snippet(
        "document.write",
        ["document.write(x)", "document.writeln(x)", "document . write (x)"],
        ["document.writeable", "document.createElement('p')"],
    ),
    Snippet(
        "eval",
        ["eval(x)", "window.eval('1')", "x = eval"],
        ["retrieval", "evaluate(x)", "medieval()"],
    ),
    Snippet("new Function", ["new Function('a', 'return a')", "new  Function()"], ["new Map()"]),
    Snippet("Function()", ["Function('return 1')()", "x = Function ('a')"], ["fn.Function(x)"]),
    Snippet(
        "|safe",
        ["{{ title | safe }}", "{{ title|safe }}", "{{ a|tojson|safe }}"],
        ["{{ title }}", "{{ boot|tojson }}", "{{ x|safeguard }}"],
    ),
    Snippet(
        "autoescape off",
        ["{% autoescape false %}", "{%- autoescape off -%}"],
        ["{% autoescape true %}", "autoescape is on"],
    ),
    Snippet(
        "inline script",
        ["<script>window.x = 1;</script>", "<script defer>x()</script>", "<SCRIPT>x</SCRIPT>"],
        [
            '<script src="/static/app.js" type="module"></script>',
            '<script type="application/json" id="boot">{{ data|tojson }}</script>',
            "<script type='application/json'>{}</script>",
        ],
    ),
    Snippet(
        "inline handler",
        ['<button onclick="save()">', "<img onerror='x()'>", '<a  onmouseover = "x">'],
        ['<button data-action="save">', "<p>prone = x</p>", '<a href="/online">'],
    ),
]
EXTERNAL = [
    '<script src="https://cdn.example/x.js"></script>',
    "<script src='//cdn.example/x.js'></script>",
    '<link rel="stylesheet" href="http://fonts.example/css">',
    '<img src="https://x.example/a.png">',
    "a { background: url(https://x.example/a.png) }",
    "a { background: url( '//x.example/a.png' ) }",
    '@import "https://fonts.example/f.css";',
    "@import url(//fonts.example/f.css);",
    "import('https://cdn.example/m.js')",
    "import { x } from 'https://cdn.example/m.js'",
    "fetch('https://api.example/x')",
]
LOCAL = [
    '<script src="/static/vendor/plotly.min.js"></script>',
    '<link rel="stylesheet" href="/static/app.css">',
    '<a href="https://docs.example/help">help</a>',
    'xmlns="http://www.w3.org/2000/svg"',
    "a { background: url(/static/a.png) }",
    "a { background: url(data:image/png;base64,AAAA) }",
    "@import './base.css';",
    "import { x } from './m.js'",
    "fetch('/api/v1/graphs')",
]


@pytest.mark.parametrize("snippet", SNIPPETS, ids=[s.rule for s in SNIPPETS])
def test_each_rule_flags_its_bad_snippets_and_only_those(snippet: Snippet) -> None:
    for text in snippet.bad:
        assert snippet.rule in violations(text), text
    for text in snippet.good:
        assert snippet.rule not in violations(text), text


@pytest.mark.parametrize("text", EXTERNAL)
def test_an_asset_that_leaves_the_origin_is_flagged(text: str) -> None:
    assert violations(text) == ["external asset"]


@pytest.mark.parametrize("text", LOCAL)
def test_local_assets_and_plain_links_are_fine(text: str) -> None:
    assert violations(text) == []


def test_every_rule_has_a_snippet_table() -> None:
    named = {s.rule for s in SNIPPETS} | {"external asset"}
    assert named == {r.name for r in RULES}
    assert len(RULES) == 12


def test_the_semgrep_template_examples_agree() -> None:
    assert violations("<p>{{ title | safe }}</p>") == ["|safe"]
    assert violations("<script>window.x = 1;</script>") == ["inline script"]
    assert violations('<button onclick="save()">Save</button>') == ["inline handler"]
    assert violations('<script src="/static/app.js" type="module"></script>') == []


def write(root: Path, name: str, text: str) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_the_scan_reports_each_broken_file_by_relative_path(tmp_path: Path) -> None:
    write(tmp_path, "a.html", "<p>{{ x|safe }}</p>")
    write(tmp_path, "js/app.js", "el.innerHTML = eval(x)")
    write(tmp_path, "js/deep/more.MJS", "document.write(1)")
    write(tmp_path, "ok.html", "<p>{{ x }}</p>")
    assert scan(tmp_path) == {
        "a.html": ["|safe"],
        "js/app.js": ["innerHTML", "eval"],
        "js/deep/more.MJS": ["document.write"],
    }


def test_the_scan_skips_vendor_directories_other_suffixes_and_markers(tmp_path: Path) -> None:
    write(tmp_path, "vendor/lib.js", "eval(1)")
    write(tmp_path, "js/vendor/lib.js", "eval(1)")
    write(tmp_path, "notes.txt", "eval(1)")
    write(tmp_path, ".gitkeep", "")
    write(tmp_path, "img.png", "eval(1)")
    write(tmp_path, "vendorish/app.js", "eval(1)")
    assert [p.relative_to(tmp_path).as_posix() for p in scanned_files(tmp_path)] == [
        "vendorish/app.js"
    ]
    assert scan(tmp_path) == {"vendorish/app.js": ["eval"]}
