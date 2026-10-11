"""``Tape``: everything an ``httpx.Client`` received, to scan for strings that must never leak.

``attach(client)`` records every response of ``client`` from then on (status line, all headers and
the body). ``tape.assert_clean(secrets)`` fails with the first few offending entries, never with
the secret itself in the message. Used for the "no secret in any response" rule (E2E.md A.8): the
password of a Mongo URI, a stored URI, a file-system path of the server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

    import httpx

SHOWN_ENTRIES: Final = 3


@dataclass(slots=True)
class Tape:
    """The responses seen so far, as text (``METHOD url``, headers, body)."""

    entries: list[str] = field(default_factory=list)

    def record(self, response: httpx.Response) -> None:
        """Event hook: keep the response (the body is read here, the caller still gets it)."""
        response.read()
        head = "\n".join(f"{name}: {value}" for name, value in response.headers.items())
        request = response.request
        line = f"{request.method} {request.url.path} -> {response.status_code}"
        self.entries.append(f"{line}\n{head}\n{response.text}")

    def find(self, needles: Iterable[str]) -> list[str]:
        """The request line of each recorded response whose headers or body hold a needle (the
        request line itself is the caller's own text and is not searched)."""
        wanted = [needle for needle in needles if needle]
        hits = []
        for entry in self.entries:
            request_line, _, answer = entry.partition("\n")
            if any(needle in answer for needle in wanted):
                hits.append(request_line)
        return hits

    def assert_clean(self, needles: Iterable[str]) -> None:
        """Fail when any recorded response holds a needle; the message names requests only."""
        assert self.entries, "nothing was recorded: the scan would pass without looking"
        offending = self.find(needles)
        assert not offending, (
            f"{len(offending)} of {len(self.entries)} responses hold a forbidden string, "
            f"e.g. {offending[:SHOWN_ENTRIES]}"
        )

    def __len__(self) -> int:
        return len(self.entries)


def attach(client: httpx.Client) -> Tape:
    """Start recording the responses of ``client``; returns the tape."""
    tape = Tape()
    client.event_hooks["response"].append(tape.record)
    return tape
