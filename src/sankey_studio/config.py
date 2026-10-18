# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Bootstrap configuration: what the process needs *before* it can read ``settings.json``.

Everything user-editable at runtime lives in ``models.AppSettings`` instead. Anything that
widens the attack surface (where files live, who may connect, remote mode) is bootstrap-only:
it can be set by the operator through the environment or the CLI, never through the web UI.
Environment variables use the ``SANKEY_`` prefix (e.g. ``SANKEY_PORT=9000``).
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
#: Bind addresses that mean "every interface": never a valid ``Host`` header value.
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})  # noqa: S104 - the wildcard binds we refuse


def default_data_dir() -> Path:
    """``$XDG_DATA_HOME/sankey-studio`` (``~/.local/share/sankey-studio``): absolute, not cwd."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "sankey-studio"


def _bare(host: str) -> str:
    """``host`` without the brackets of an IPv6 literal."""
    return host.removeprefix("[").removesuffix("]")


def is_wildcard(host: str) -> bool:
    """A bind address that means "every interface": ``0.0.0.0``, ``::``, ``[::]``, ``0::0``, ...

    Brackets are ignored. Such an address is never auto-allowed as a ``Host`` value.
    """
    bare = _bare(host)
    if bare in WILDCARD_HOSTS:
        return True
    try:
        return ipaddress.ip_address(bare).is_unspecified
    except ValueError:
        return False


def _host_entries(host: str) -> list[str]:
    """The ``allowed_hosts`` entries that let a request to the bound ``host`` through.

    A name is listed as given. An IP address is listed as typed and in canonical form (a browser
    sends ``[::1]`` for ``0:0:0:0:0:0:0:1``); an IPv6 address is bracketed, the form a ``Host``
    header and ``web.security.host_pattern_problem`` expect.
    """
    bare = _bare(host)
    try:
        address = ipaddress.ip_address(bare)
    except ValueError:
        return [host]
    spellings = dict.fromkeys([bare.lower(), address.compressed])
    if isinstance(address, ipaddress.IPv6Address):
        return [f"[{text}]" for text in spellings]
    return list(spellings)


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host.removeprefix("[").removesuffix("]")).is_loopback
    except ValueError:
        return False


class BootstrapConfig(BaseSettings):
    #: ``hide_input_in_errors``: ``SANKEY_MONGO_URI`` (credentials) must never reach the console
    #: through ``str(ValidationError)``, whichever field fails (see ``cli.py``).
    model_config = SettingsConfigDict(
        env_prefix="SANKEY_", extra="ignore", hide_input_in_errors=True
    )

    #: There is no login. Bind to loopback unless you know what you are doing.
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    #: Resolved to an absolute path at construction. Holds ``settings.json``, ``credentials.json``
    #: (the Mongo URIs, in clear text), ``graphs/`` and the default ``sources/``.
    data_dir: Path = Field(default_factory=default_data_dir)
    #: Root for ``TextSource(origin="file")`` and the upload API. Bootstrap-only (never editable
    #: through the web: a web-writable root would be arbitrary file read/write). ``None`` ->
    #: ``<data_dir>/sources``. May not equal or contain ``data_dir``, ``graphs/`` or the settings.
    sources_dir: Path | None = None
    log_level: str = "info"
    #: Accepted ``Host`` header values (DNS-rebinding guard). ``"*"`` is refused unless remote_mode.
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "[::1]"])
    #: Seeds a connection named "default" when no settings file exists yet.
    mongo_uri: SecretStr | None = None
    #: ``--allow-remote``: the operator accepts a non-loopback bind. Privileged writes (Mongo
    #: connections, storage backend, uploads/deletes, graph writes that change connections) are
    #: refused unless ``remote_writes`` is also set. Without remote_mode a non-loopback host is
    #: refused here, so ``uvicorn ... --factory`` cannot bypass the CLI check.
    remote_mode: bool = False
    #: ``--allow-remote-writes``: lift the read-only restriction in remote mode.
    remote_writes: bool = False
    #: ``--allow-source-writes``: with ``remote_writes``, also allow writing edits back to
    #: MongoDB sources. Files follow ``privileged_writes_allowed``. Loopback: always allowed.
    source_writes: bool = False

    @field_validator("data_dir", "sources_dir")
    @classmethod
    def _absolute(cls, v: Path | None) -> Path | None:
        return None if v is None else v.expanduser().resolve()

    @model_validator(mode="after")
    def _guards(self) -> BootstrapConfig:
        if not _is_loopback(self.host) and not self.remote_mode:
            raise ValueError("a non-loopback host needs remote_mode (--allow-remote)")
        if self.remote_writes and not self.remote_mode:
            raise ValueError("remote_writes needs remote_mode (--allow-remote)")
        if self.source_writes and not self.remote_writes:
            raise ValueError("source_writes needs remote_writes (--allow-remote-writes)")
        if "*" in self.allowed_hosts and not self.remote_mode:
            raise ValueError("allowed_hosts may only contain '*' in remote_mode")
        self._check_sources_dir()
        self._allow_bound_host()
        return self

    def _allow_bound_host(self) -> None:
        """The address the app is bound to is always an accepted ``Host`` (a wildcard has none).

        Loopback binds count too: ``--host 127.0.0.2`` prints ``http://127.0.0.2:8765``, which
        must not answer ``400 Invalid host header``.
        """
        if is_wildcard(self.host):
            return
        listed = {entry.lower() for entry in self.allowed_hosts}
        missing = [entry for entry in _host_entries(self.host) if entry.lower() not in listed]
        if missing:
            self.allowed_hosts = [*self.allowed_hosts, *missing]

    def _check_sources_dir(self) -> None:
        root = self.effective_sources_dir
        protected = (self.data_dir, self.graphs_dir, self.settings_file, self.credentials_file)
        if any(root == p or p.is_relative_to(root) for p in protected):
            raise ValueError(
                "sources_dir must not equal or contain data_dir, graphs/, settings.json "
                "or credentials.json"
            )
        if root.is_relative_to(self.graphs_dir):
            raise ValueError("sources_dir must not be inside graphs/")

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def credentials_file(self) -> Path:
        """The connection strings, apart from ``settings.json`` (``storage.settings_store``)."""
        return self.data_dir / "credentials.json"

    @property
    def graphs_dir(self) -> Path:
        return self.data_dir / "graphs"

    @property
    def default_sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def effective_sources_dir(self) -> Path:
        """The managed sources directory: ``sources_dir`` or ``<data_dir>/sources``."""
        return self.sources_dir or self.default_sources_dir

    @property
    def is_loopback(self) -> bool:
        return _is_loopback(self.host)

    @property
    def privileged_writes_allowed(self) -> bool:
        """False in remote mode unless ``remote_writes``: settings/upload/delete are refused."""
        return not self.remote_mode or self.remote_writes

    @property
    def source_writes_allowed(self) -> bool:
        """MongoDB write-back: always on loopback; in remote mode only with ``source_writes``.

        Files use ``privileged_writes_allowed`` instead.
        """
        return not self.remote_mode or self.source_writes
