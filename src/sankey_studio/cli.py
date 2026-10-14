"""Command line: ``sankey-studio serve [--host] [--port] [--data-dir] [--sources-dir] ...``.

argparse fills ``ServeArgs``; ``build_config`` turns it into a ``BootstrapConfig`` (whose
validators refuse a non-loopback host without ``--allow-remote``); ``main`` builds the app and
hands it to ``_run_server``, the ONE place that starts uvicorn (tests replace it, so nothing
here needs a real server). One worker only: file locks and the export slot are per process.

A configuration error prints the location and message of each problem and exits with status 2:
a failed field validation, an environment value that cannot be parsed (a list such as
``SANKEY_ALLOWED_HOSTS`` must be a JSON array), a ``log_level`` uvicorn does not know and an
``allowed_hosts`` entry that cannot work, and a ``SANKEY_MONGO_URI`` the settings would refuse
(only where and why are printed: ``str(ValidationError)`` and tracebacks are never shown, because
a URI carries credentials). Nothing is bound before every check has passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import uvicorn
from pydantic import ValidationError
from pydantic_settings import SettingsError as EnvSettingsError
from uvicorn.config import LOG_LEVELS

from sankey_studio.config import BootstrapConfig, is_wildcard
from sankey_studio.models import MongoConnection
from sankey_studio.storage.settings_store import SEED_CONNECTION
from sankey_studio.web.app import InvalidConfigError, create_app

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from fastapi import FastAPI

PROG: Final = "sankey-studio"
EXIT_CONFIG: Final = 2
#: uvicorn answers 503 beyond this many open connections (keep-alive ones included).
LIMIT_CONCURRENCY: Final = 100
HOSTS_ENV: Final = "SANKEY_ALLOWED_HOSTS"
#: A host the example of the banner adds to the accepted ones.
EXAMPLE_HOST: Final = "192.168.1.5"
VALUE_ERROR_PREFIX: Final = "Value error, "
#: Printed for a ``SettingsError`` (its own text can quote the value); the usual cause is a list.
MSG_ENV_UNPARSABLE: Final = (
    "a SANKEY_* environment value could not be parsed; list values such as "
    f"{HOSTS_ENV} must be a JSON array, for example {HOSTS_ENV}='[\"192.168.1.5\"]'"
)


@dataclass(frozen=True, slots=True)
class ServeArgs:
    """The options of ``serve``; ``None`` means "not given" (environment and defaults apply)."""

    host: str | None = None
    port: int | None = None
    data_dir: Path | None = None
    sources_dir: Path | None = None
    allow_remote: bool = False
    allow_remote_writes: bool = False
    allow_source_writes: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Draw and manage Sankey graphs.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="start the web server")
    serve.add_argument("--host", help="address to bind (default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port to listen on (default 8765)")
    serve.add_argument("--data-dir", type=Path, help="where settings and graphs are stored")
    serve.add_argument("--sources-dir", type=Path, help="folder of managed source files")
    serve.add_argument(
        "--allow-remote",
        action="store_true",
        help="accept a non-loopback bind: there is NO authentication, writes stay disabled",
    )
    serve.add_argument(
        "--allow-remote-writes",
        action="store_true",
        help="with --allow-remote: also allow changes to settings, files and graphs",
    )
    serve.add_argument(
        "--allow-source-writes",
        action="store_true",
        help="with --allow-remote-writes: also allow writing edits back to MongoDB sources",
    )
    return parser


def parse_serve_args(argv: Sequence[str] | None = None) -> ServeArgs:
    """``ServeArgs`` from ``argv`` (``sys.argv[1:]`` by default); argparse exits on bad usage."""
    ns = _parser().parse_args(argv)
    return ServeArgs(
        host=ns.host,
        port=ns.port,
        data_dir=ns.data_dir,
        sources_dir=ns.sources_dir,
        allow_remote=ns.allow_remote,
        allow_remote_writes=ns.allow_remote_writes,
        allow_source_writes=ns.allow_source_writes,
    )


def build_config(args: ServeArgs) -> BootstrapConfig:
    """The configuration: environment and defaults, overridden by the options that were given.

    Raises ``pydantic.ValidationError``, ``pydantic_settings.SettingsError`` (an environment
    value that cannot be parsed) or ``InvalidConfigError`` (a ``log_level`` uvicorn does not
    know, a ``SANKEY_MONGO_URI`` the settings would refuse); ``main`` shows them without echoing
    any value.
    """
    given: dict[str, Any] = {
        "host": args.host,
        "port": args.port,
        "data_dir": args.data_dir,
        "sources_dir": args.sources_dir,
    }
    overrides = {name: value for name, value in given.items() if value is not None}
    if args.allow_remote:
        overrides["remote_mode"] = True
    if args.allow_remote_writes:
        overrides["remote_writes"] = True
    if args.allow_source_writes:
        overrides["source_writes"] = True
    config = BootstrapConfig(**overrides)
    if config.log_level.lower() not in LOG_LEVELS:  # uvicorn would fail with a KeyError later
        raise InvalidConfigError("log_level", f"must be one of {', '.join(LOG_LEVELS)}")
    _check_seed(config)
    return config


def _check_seed(config: BootstrapConfig) -> None:
    """``InvalidConfigError`` when the seed URI fails the check the settings run on it later.

    The first read of the settings builds the ``default`` connection from ``SANKEY_MONGO_URI``
    and answers every request with 422 ``settings_error`` when that fails, so the same model is
    built here, once. The message comes from ``mongo_safety.check_mongo_uri`` and names an option
    key at most: never the URI.
    """
    seed = config.mongo_uri
    if seed is None:
        return
    try:
        MongoConnection(name=SEED_CONNECTION, uri=seed)
    except ValidationError as exc:
        reason = exc.errors(include_input=False, include_url=False)[0]["msg"]
        raise InvalidConfigError("mongo_uri", reason.removeprefix(VALUE_ERROR_PREFIX)) from None


def _report(problems: Iterable[tuple[str, str]]) -> None:
    """Print where each problem is and what it is; never the input, never a traceback."""
    print(f"{PROG}: invalid configuration", file=sys.stderr)
    for where, message in problems:
        print(f"  {where}: {message}", file=sys.stderr)


def _field_problems(exc: ValidationError) -> list[tuple[str, str]]:
    return [
        (".".join(str(part) for part in error["loc"]) or "config", error["msg"])
        for error in exc.errors(include_input=False, include_url=False)
    ]


def _address(config: BootstrapConfig) -> str:
    """The URL the app answers on; a wildcard bind has none (``0.0.0.0`` is not a valid Host)."""
    if is_wildcard(config.host):
        return f"all interfaces, port {config.port}"
    host = f"[{config.host}]" if ":" in config.host and "[" not in config.host else config.host
    return f"http://{host}:{config.port}"


def _announce_hosts(config: BootstrapConfig) -> None:
    """Which ``Host`` headers are answered, and how to add one (anything else gets a 400)."""
    if "*" in config.allowed_hosts:
        print("Accepted Host headers: any (allowed_hosts contains '*')")
        return
    extra = [] if EXAMPLE_HOST in config.allowed_hosts else [EXAMPLE_HOST]
    example = json.dumps([*config.allowed_hosts, *extra])
    print(f"Accepted Host headers: {', '.join(config.allowed_hosts)}")
    print('Any other host in the URL gets "400 Invalid host header". To accept more, set')
    print(f"{HOSTS_ENV} to the JSON list of ALL accepted hosts, for example:")
    print(f"  {HOSTS_ENV}='{example}'")


def _announce(config: BootstrapConfig) -> None:
    print(f"Data directory: {config.data_dir}")
    print(f"Listening on {_address(config)}")
    if not config.remote_mode:
        return
    writes = "ENABLED" if config.remote_writes else "DISABLED (read-only)"
    print("*" * 72)
    print("* REMOTE MODE: NO AUTHENTICATION. Anyone who can reach this address can")
    print(f"* use the app. Bound to {_address(config)}; changes are {writes}.")
    print("*" * 72)
    print(f"source writes: {'ENABLED' if config.source_writes else 'DISABLED'}")
    _announce_hosts(config)


def _run_server(app: FastAPI, config: BootstrapConfig) -> None:
    """Run uvicorn in this process (the one seam tests replace)."""
    uvicorn.run(
        app,
        host=config.host.removeprefix("[").removesuffix("]"),
        port=config.port,
        workers=1,
        log_level=config.log_level.lower(),
        limit_concurrency=LIMIT_CONCURRENCY,
        proxy_headers=False,
        server_header=False,
        ws="none",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of ``sankey-studio``; returns the process exit status."""
    args = parse_serve_args(argv)
    try:
        config = build_config(args)
        app = create_app(config)
    except ValidationError as exc:
        _report(_field_problems(exc))
        return EXIT_CONFIG
    except EnvSettingsError:
        _report([("environment", MSG_ENV_UNPARSABLE)])
        return EXIT_CONFIG
    except InvalidConfigError as exc:
        _report([(exc.where, exc.message)])
        return EXIT_CONFIG
    _announce(config)
    _run_server(app, config)
    return 0
