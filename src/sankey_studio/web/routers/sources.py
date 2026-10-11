"""Managed source files and format detection (prefix ``/api/v1/sources``).

* ``GET /files`` -> ``[{"name", "size", "modified"}, ...]``: allowed regular files below the
  sources directory (``name`` is relative, POSIX, at most 3 levels deep).
* ``POST /files`` (the one multipart route; the file part is ``file``, the optional form field
  ``overwrite``) -> 201 with the stored file's info. The upload is streamed into a spooled
  temporary file by the multipart parser and from there into the sources directory by
  ``save_stream``; it is never read into ``bytes``. A taken name (casefolded) answers 409
  ``conflict`` unless ``overwrite=true``; a file above ``max_upload_mb`` answers 413
  ``payload_too_large``.
* ``DELETE /files/{name}`` -> 204; ``GET /files/{name}/preview`` -> ``{"name", "lines"}`` (the
  first 50 lines, each at most 500 characters, 64 KB in all, decoded leniently). ``name`` may
  contain ``/`` (files in sub-directories) and any character of a name ``GET /files`` lists,
  a newline included (see ``NewlinePathConvertor``). Every path goes through
  ``resolve_source_path``: traversal and symlinks answer 400 ``unsafe_source``, a missing file
  404 ``source_not_found``.
* ``POST /detect`` with ``{"sample": text}`` -> ``{"format": csv|tsv|sankeymatic|json}``. Only the
  first 4096 characters of the sample are looked at. A pure computation: available in remote
  read-only mode.

Upload and delete depend on ``require_writes`` (403 ``read_only_mode`` in remote mode without
``--allow-remote-writes``; the body-size middleware already refuses an upload there before it
reads a byte). The handlers are plain ``def``: file I/O runs in Starlette's worker thread pool.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, ConfigDict
from starlette.convertors import PathConvertor, register_url_convertor

from sankey_studio.sources.files import (
    SaveRequest,
    SourceFileInfo,
    delete_file,
    list_files,
    preview_file,
    save_stream,
)
from sankey_studio.sources.formats import ParsedFormat, detect_format
from sankey_studio.web.deps import ServicesDep, require_writes
from sankey_studio.web.schemas import UploadFormDep
from sankey_studio.web.security import MIB

__all__ = ["DetectIn", "DetectOut", "FilePreview", "router"]


class NewlinePathConvertor(PathConvertor):
    """``{name:path}`` that also matches a newline.

    Starlette's own ``path`` convertor is ``.*``, which stops at a newline, so a planted file
    called ``a<LF>b.csv`` was listed by ``GET /files`` but its preview and delete answered 404.
    ``(?s:.*)`` matches everything, empty included. It replaces the built-in ``path`` key for
    the whole process (route templates and the OpenAPI paths stay ``{name:path}``) and is
    registered BEFORE the routes below are compiled; nothing else in the app has a ``:path``
    parameter except the static mount, where a newline is a plain 404 anyway.
    """

    regex = "(?s:.*)"


register_url_convertor("path", NewlinePathConvertor())

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


class _Body(BaseModel):
    """Bodies of this module: no unknown fields, no echoed input (a sample is pasted text)."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FilePreview(_Body):
    name: str
    lines: list[str]


class DetectIn(_Body):
    sample: str


class DetectOut(_Body):
    format: ParsedFormat


@router.get("/files")
def list_source_files(services: ServicesDep) -> list[SourceFileInfo]:
    return list_files(services.sources_dir())


@router.post("/files", status_code=201, dependencies=[Depends(require_writes)])
def upload_source_file(
    file: UploadFile, form: UploadFormDep, services: ServicesDep
) -> SourceFileInfo:
    request = SaveRequest(
        sources_dir=services.sources_dir(),
        filename=file.filename or "",
        max_bytes=services.settings().max_upload_mb * MIB,
        overwrite=form.overwrite,
    )
    return save_stream(request, file.file)


@router.delete("/files/{name:path}", status_code=204, dependencies=[Depends(require_writes)])
def delete_source_file(name: str, services: ServicesDep) -> None:
    delete_file(services.sources_dir(), name)


@router.get("/files/{name:path}/preview")
def preview_source_file(name: str, services: ServicesDep) -> FilePreview:
    return FilePreview(name=name, lines=preview_file(services.sources_dir(), name))


@router.post("/detect")
def detect_source_format(body: DetectIn) -> DetectOut:
    return DetectOut(format=detect_format(body.sample))
