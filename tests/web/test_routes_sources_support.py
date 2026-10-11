"""Helpers of ``tests/web/test_routes_sources*.py`` (no tests here)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

    from sankey_studio.config import BootstrapConfig
    from tests.web.conftest import WebApp

BASE = "/api/v1/sources"
FILES = f"{BASE}/files"
DETECT = f"{BASE}/detect"
MIB = 2**20
#: What the file that blocks the sources directory contains.
BLOCKER_TEXT = b"not a directory"


def upload(
    client: TestClient, name: str = "a.csv", content: bytes = b"a,b,1\n", **form: str
) -> Any:
    """``POST /sources/files`` as the browser does it: a ``file`` part plus form fields."""
    return client.post(FILES, files={"file": (name, content)}, data=form or None)


def raw_upload(client: TestClient, filename: str, content: bytes = b"x") -> Any:
    """A hand-built multipart body: ``filename`` reaches the server byte for byte.

    The test client percent-escapes control characters in a file name, which would hide them.
    """
    head = f'--b\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n\r\n'
    body = head.encode() + content + b"\r\n--b--\r\n"
    headers = {"Content-Type": "multipart/form-data; boundary=b"}
    return client.post(FILES, content=body, headers=headers)


def put_file(web: WebApp, rel: str, content: bytes = b"a,b,1\n") -> Path:
    """Plant ``rel`` in the sources directory (the operator's way of adding files)."""
    path = web.services.sources_dir() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def disk_names(web: WebApp) -> list[str]:
    """Everything directly in the sources directory (hidden upload temp files included)."""
    return sorted(entry.name for entry in web.services.sources_dir().iterdir())


def listed(client: TestClient) -> list[str]:
    response = client.get(FILES)
    assert response.status_code == 200
    return [item["name"] for item in response.json()]


def error_of(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}
    error: dict[str, Any] = body["error"]
    assert set(error) == {"code", "message", "details"}
    return error


def block_sources_dir(config: BootstrapConfig) -> Path:
    """Make the sources directory unusable: a regular FILE sits where the directory should be.

    ``Services.sources_dir`` then answers ``StorageError`` (503) instead of creating it.
    """
    blocker = config.effective_sources_dir
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_bytes(BLOCKER_TEXT)
    return blocker
