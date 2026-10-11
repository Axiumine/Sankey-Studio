"""Helpers of the security suites (E2E.md A.8): routes, header expectations, internals scan.

* ``WRITE_ROUTES`` - every route that persists something (a read-only remote server refuses all of
  them with 403 ``read_only_mode``); ``SAFE_POST_ROUTES`` - POST routes that only compute (they
  are still behind the CSRF guard). ``send(client, route, graph_id)`` makes the request of a route.
* ``Snapshot`` / ``snapshot(client, server)`` - what an attacker must not be able to change: the
  graph list, the settings answer and the files of the sources directory.
* ``assert_security_headers`` - the headers every answer carries (CSP, nosniff, Referrer-Policy,
  CORP; ``no-store`` for the API and the HTML pages; ``sandbox`` CSP for downloads).
* ``assert_no_internals`` - no stack trace, source file name or server path in a body.
* ``boot_data`` - the JSON block every HTML page carries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from tests.e2e.support.builders import graph_create, graph_draft
from tests.e2e.support.clients import json_of

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from tests.e2e.support.server import LiveServer

Kind = Literal["json", "none", "multipart"]
API: Final = "/api/v1"
CSP_DIRECTIVES: Final = {
    "default-src": "'self'",
    "script-src": "'self'",
    "object-src": "'none'",
    "frame-ancestors": "'none'",
    "base-uri": "'none'",
    "form-action": "'self'",
}
#: Text that gives away the server: a trace, a source file, a path to a user or temp directory.
INTERNALS: Final = (
    "Traceback",
    'File "',
    "site-packages",
    ".py",
    "/home/",
    "/tmp/",  # noqa: S108 - text scanned for, not a path used
    "/media/",
)
PAGE_DATA: Final = re.compile(
    r'<script type="application/json" id="page-data">(.*?)</script>', re.DOTALL
)
SCRIPT_TAG: Final = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
INLINE_HANDLER: Final = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
BUNDLE: Final = {"format": "sankey-studio/graphs", "version": 1, "graphs": []}


@dataclass(frozen=True, slots=True)
class Route:
    """An unsafe route: ``path`` may hold ``{gid}``; ``kind`` is how the body is sent."""

    label: str
    method: str
    path: str
    kind: Kind
    body: Any = None


WRITE_ROUTES: Final = (
    Route("create", "POST", f"{API}/graphs", "json", graph_create("attack")),
    Route(
        "update", "PUT", f"{API}/graphs/{{gid}}", "json", {**graph_create("attack"), "revision": 1}
    ),
    Route("delete", "DELETE", f"{API}/graphs/{{gid}}", "none"),
    Route("duplicate", "POST", f"{API}/graphs/{{gid}}/duplicate", "none"),
    Route("import", "POST", f"{API}/graphs/import", "json", BUNDLE),
    Route("settings", "PUT", f"{API}/settings", "json", {"max_links": 150}),
    Route("storage-test", "POST", f"{API}/settings/storage/test", "json", {}),
    Route("mongo-test", "POST", f"{API}/settings/mongo/main/test", "none"),
    Route("upload", "POST", f"{API}/sources/files", "multipart", ("attack.csv", b"a,b,1\n")),
    Route("delete-source", "DELETE", f"{API}/sources/files/keep.csv", "none"),
)
SAFE_POST_ROUTES: Final = (
    Route("preview", "POST", f"{API}/preview", "json", graph_draft()),
    Route("entries", "POST", f"{API}/entries", "json", graph_draft()),
    Route("export", "POST", f"{API}/export?format=csv", "json", graph_draft()),
    Route("detect", "POST", f"{API}/sources/detect", "json", {"sample": "a,b,1"}),
)


def send(client: httpx.Client, route: Route, graph_id: str) -> httpx.Response:
    """The request of ``route`` (``{gid}`` filled in) over ``client``."""
    path = route.path.format(gid=graph_id)
    if route.kind == "json":
        return client.request(route.method, path, json=route.body)
    if route.kind == "multipart":
        name, content = route.body
        return client.request(route.method, path, files={"file": (name, content, "text/csv")})
    return client.request(route.method, path)


# ------------------------------------------------------------------------------ snapshots


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What must survive an attack unchanged."""

    graphs: Any
    settings: Any
    sources: list[str]
    graph_files: list[str]
    settings_file: bytes | None


def snapshot(client: httpx.Client, server: LiveServer) -> Snapshot:
    """Graph list with revisions, the settings answer and file, and the files on disk."""
    return Snapshot(
        graphs=json_of(client.get(f"{API}/graphs")),
        settings=json_of(client.get(f"{API}/settings")),
        sources=_names(server.sources_dir),
        graph_files=_names(server.graphs_dir),
        settings_file=server.settings_file.read_bytes() if server.settings_file.exists() else None,
    )


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*")) if directory.exists() else []


# ------------------------------------------------------------------------------ assertions


def csp_directives(policy: str) -> dict[str, str]:
    """``{"default-src": "'self'", ...}`` of a Content-Security-Policy value."""
    parsed = {}
    for part in policy.split(";"):
        name, _, value = part.strip().partition(" ")
        if name:
            parsed[name] = value
    return parsed


def assert_security_headers(
    response: httpx.Response, *, no_store: bool | None, download: bool = False
) -> None:
    """The headers of E2E.md A.8 on ``response`` (``download``: a sandboxed attachment).

    ``no_store`` says whether ``Cache-Control: no-store`` is expected; ``None`` leaves it open."""
    headers, where = response.headers, f"{response.request.method} {response.request.url.path}"
    policy = headers.get("content-security-policy", "")
    if download:
        assert policy == "sandbox", where
    else:
        directives = csp_directives(policy)
        assert directives == CSP_DIRECTIVES | {
            "style-src": "'self' 'unsafe-inline'",
            "img-src": "'self' data: blob:",
        }, where
    assert headers.get("x-content-type-options") == "nosniff", where
    assert headers.get("referrer-policy") == "same-origin", where
    assert headers.get("cross-origin-resource-policy") == "same-origin", where
    if no_store is not None:
        assert ("no-store" in headers.get("cache-control", "")) is no_store, where
    assert "access-control-allow-origin" not in headers, where  # no CORS, ever


def assert_no_internals(text: str, server: LiveServer) -> None:
    """No stack trace, source file name or server-side path in an error body."""
    found = [needle for needle in INTERNALS if needle in text]
    assert not found, f"internals {found} in: {text[:300]}"
    for directory in (server.data_dir, server.sources_dir, server.graphs_dir):
        assert str(directory) not in text


def boot_data(html: str) -> dict[str, Any]:
    """The parsed ``<script id="page-data">`` block of an HTML page."""
    match = PAGE_DATA.search(html)
    assert match is not None, "the page has no page-data block"
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def inline_code(html: str) -> list[str]:
    """Inline scripts and event-handler attributes of a page (there must be none)."""
    scripts = [
        tag
        for tag in SCRIPT_TAG.findall(html)
        if "src=" not in tag and 'type="application/json"' not in tag
    ]
    return [*scripts, *INLINE_HANDLER.findall(html)]
