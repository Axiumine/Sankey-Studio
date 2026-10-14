"""Domain errors. The web layer maps these to HTTP status codes (see ``web/app.py``).

Every error carries a stable ``code`` (API clients switch on it) and an HTTP ``status_code``.
Messages must never contain credentials, URIs or file contents: use connection *names*.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - used in a runtime signature


class SankeyError(Exception):
    """Base class for every error this package raises on purpose."""

    #: HTTP status the web layer answers with.
    status_code: int = 400
    #: Stable machine-readable code for API clients.
    code: str = "sankey_error"

    def __init__(self, message: str, *, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class SourceError(SankeyError):
    """A data source could not be read or parsed (bad file, bad row, bad mapping)."""

    status_code = 422
    code = "source_error"


class SourceNotFoundError(SourceError):
    """A referenced source file or Mongo connection/collection does not exist."""

    status_code = 404
    code = "source_not_found"


class UnsafeSourceError(SourceError):
    """A source tried something forbidden: path escape, write stage in a pipeline, ..."""

    status_code = 400
    code = "unsafe_source"


class GraphBuildError(SankeyError):
    """Links are valid individually but cannot form a drawable graph (e.g. a cycle)."""

    status_code = 422
    code = "graph_build_error"


class NoCategoriesError(GraphBuildError):
    """The donut chart was requested but no drawn entry has a category."""

    status_code = 422
    code = "no_categories"


class GraphTooLargeError(GraphBuildError):
    """More raw links than ``AppSettings.max_links`` allows, or category rules too costly.

    The second case is more than 20 million (distinct name x glob rule) matches.
    """

    status_code = 413
    code = "graph_too_large"


class NotFoundError(SankeyError):
    """A saved graph (or other stored entity) does not exist. Also raised for malformed ids."""

    status_code = 404
    code = "not_found"


class ConflictError(SankeyError):
    """Optimistic-concurrency failure: the stored revision moved on, or the id already exists.

    ``current_revision`` / ``current_updated_at`` let the UI offer "reload" or "save as copy".
    They are echoed in ``details`` as ``revision=N`` and ``updated_at=<iso>``.
    """

    status_code = 409
    code = "conflict"

    def __init__(
        self,
        message: str,
        *,
        current_revision: int | None = None,
        current_updated_at: datetime | None = None,
        details: list[str] | None = None,
    ) -> None:
        extra = list(details or [])
        if current_revision is not None:
            extra.append(f"revision={current_revision}")
        if current_updated_at is not None:
            extra.append(f"updated_at={current_updated_at.isoformat()}")
        super().__init__(message, details=extra)
        self.current_revision = current_revision
        self.current_updated_at = current_updated_at


class StorageError(SankeyError):
    """The storage backend failed (disk error, Mongo unreachable, ...)."""

    status_code = 503
    code = "storage_error"


class SettingsError(SankeyError):
    """Settings are invalid or cannot be saved."""

    status_code = 422
    code = "settings_error"


class BundleError(SankeyError):
    """A graph bundle as a whole is unusable (wrong format or version, too many graphs, bad mode).

    Also importable from ``sankey_studio.storage.bundle``, where it used to live.
    """

    status_code = 422
    code = "bundle_error"


class FolderRuleError(SankeyError):
    """A library-folder rule is broken: a cycle, too deep a tree or too many folders."""

    status_code = 422
    code = "folder_rule"


class FolderNameTakenError(SankeyError):
    """A folder with this name already exists in the same place.

    A direct ``SankeyError`` subclass on purpose: the browser reads ``409`` with code
    ``conflict`` as a stale revision, and a name clash must not look like one.
    """

    status_code = 409
    code = "folder_name_taken"


class BusyError(SankeyError):
    """A bounded resource (Mongo pool slot, export slot) is in use; try again shortly."""

    status_code = 503
    code = "busy"


# --------------------------------------------------------------------------- exports


class ExportUnavailableError(SankeyError):
    """An export format needs an optional dependency (kaleido + Chrome) that is not usable."""

    status_code = 501
    code = "export_unavailable"


class ExportBusyError(BusyError):
    """Another image export is running (one at a time); answered instead of queueing."""

    code = "export_busy"


class ExportTooLargeError(SankeyError):
    """The requested image is too big (pixel cap) or the graph has too many links to rasterise."""

    status_code = 422
    code = "export_too_large"


class ExportFailedError(SankeyError):
    """The renderer (kaleido/Chrome) crashed or returned garbage."""

    status_code = 502
    code = "export_failed"


class ExportTimeoutError(SankeyError):
    """The renderer did not finish in time; Chrome was killed."""

    status_code = 504
    code = "export_timeout"


# --------------------------------------------------------------------------- web guards


class ForbiddenError(SankeyError):
    """The request was refused by a guard (cross-site request, bad Origin, ...)."""

    status_code = 403
    code = "forbidden"


class ReadOnlyModeError(ForbiddenError):
    """Remote mode without ``--allow-remote-writes``: privileged writes are refused."""

    code = "read_only_mode"


class UnsupportedMediaTypeError(SankeyError):
    """Wrong ``Content-Type`` for the route."""

    status_code = 415
    code = "unsupported_media_type"


class PayloadTooLargeError(SankeyError):
    """The request body exceeded the per-route byte cap (counted while streaming)."""

    status_code = 413
    code = "payload_too_large"


# --------------------------------------------------------------------------- source write-back


class SourceEditRefused(SourceError):  # noqa: N818 - the name is part of the write-back contract
    """An edit cannot be written back to the data source (an expected answer, not a failure).

    ``reason`` is one of ``models.edits.Reason`` (typed ``str`` here: this module imports
    nothing). Mostly an internal signal; it reaches HTTP only as ``no_consent``.
    """

    status_code = 422
    code = "source_edit_refused"

    def __init__(self, reason: str) -> None:
        super().__init__(f"This edit cannot be written back to the source ({reason})")
        self.reason = reason


class SourceWriteError(SankeyError):
    """A write to a source failed in a way that leaves the result unknown (driver or OS error).

    The message names the connection (or the file) and the exception class only.
    """

    status_code = 502
    code = "source_write_failed"
