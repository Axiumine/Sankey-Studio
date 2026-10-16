# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Wait until a MongoDB answers a ``ping`` (the compose file has no healthcheck).

    uv run python scripts/mongo_wait.py --uri mongodb://127.0.0.1:27117 --timeout 60

``--timeout 0`` makes exactly one attempt, which is how the gate asks "is it already running?".
Exit status: 0 the server answered, 1 it did not answer in time. The URI is never printed.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import TYPE_CHECKING

from pymongo import MongoClient
from pymongo.errors import PyMongoError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

ATTEMPT_MS = 1000
POLL_SECONDS = 1.0


def ping_once(uri: str) -> bool:
    """One ``ping`` with a short server-selection timeout; any driver error means no answer."""
    client: MongoClient[dict[str, object]] = MongoClient(
        uri, serverSelectionTimeoutMS=ATTEMPT_MS, connectTimeoutMS=ATTEMPT_MS
    )
    try:
        client.admin.command("ping")
    except PyMongoError:
        return False
    finally:
        client.close()
    return True


def wait_for(
    ping: Callable[[], bool],
    timeout: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Call ``ping`` until it succeeds or ``timeout`` seconds have passed (always at least once)."""
    deadline = clock() + timeout
    while True:
        if ping():
            return True
        if clock() >= deadline:
            return False
        sleep(POLL_SECONDS)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    if wait_for(lambda: ping_once(args.uri), args.timeout):
        print("mongo_wait: the server answers")
        return 0
    print(f"mongo_wait: no answer within {args.timeout:g} s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
