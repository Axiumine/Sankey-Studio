# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""scripts/mongo_wait.py: wait until the project MongoDB answers a ping (no real server here)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

import pytest
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from scripts import mongo_wait

URI = "mongodb://user:secret@127.0.0.1:27117/?appName=x"


class FakeClient:
    """A stand-in for ``MongoClient`` that records how it was built, used and closed."""

    instances: list[FakeClient] = []  # noqa: RUF012 - test double, reset by the fixture
    error: Exception | None = None

    def __init__(self, uri: str, **options: Any) -> None:
        self.uri = uri
        self.options = options
        self.commands: list[str] = []
        self.closed = False
        self.admin = self
        FakeClient.instances.append(self)

    def command(self, name: str) -> dict[str, int]:
        self.commands.append(name)
        if FakeClient.error is not None:
            raise FakeClient.error
        return {"ok": 1}

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.instances = []
    FakeClient.error = None
    monkeypatch.setattr(mongo_wait, "MongoClient", FakeClient)
    return FakeClient


# --------------------------------------------------------------------------- ping_once


def test_a_ping_that_answers_is_true_and_asks_for_a_short_wait(
    fake_client: type[FakeClient],
) -> None:
    assert mongo_wait.ping_once(URI) is True
    (client,) = fake_client.instances
    assert client.uri == URI
    assert client.options == {"serverSelectionTimeoutMS": 1000, "connectTimeoutMS": 1000}
    assert client.commands == ["ping"]
    assert client.closed


@pytest.mark.parametrize(
    "error",
    [PyMongoError("x"), ServerSelectionTimeoutError("no server")],
    ids=["driver error", "no server"],
)
def test_any_driver_error_means_no_answer_and_the_client_is_closed(
    fake_client: type[FakeClient], error: Exception
) -> None:
    fake_client.error = error
    assert mongo_wait.ping_once(URI) is False
    assert fake_client.instances[0].closed


def test_an_error_that_is_not_a_driver_error_is_not_swallowed(
    fake_client: type[FakeClient],
) -> None:
    fake_client.error = RuntimeError("bug")
    with pytest.raises(RuntimeError, match="bug"):
        mongo_wait.ping_once(URI)
    assert fake_client.instances[0].closed


# --------------------------------------------------------------------------- wait_for


class Script:
    """Pings that answer from a list, a clock that moves one second per reading."""

    def __init__(self, answers: list[bool]) -> None:
        self.answers = answers
        self.pings = 0
        self.slept: list[float] = []
        self.now = 100.0

    def ping(self) -> bool:
        self.pings += 1
        return self.answers.pop(0) if self.answers else False

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def wait(script: Script, timeout: float) -> bool:
    return mongo_wait.wait_for(script.ping, timeout, script.sleep, script.clock)


def test_a_server_that_answers_at_once_is_pinged_once() -> None:
    script = Script([True])
    assert wait(script, 60) is True
    assert (script.pings, script.slept) == (1, [])


def test_the_wait_polls_every_second_until_the_server_answers() -> None:
    script = Script([False, False, True])
    assert wait(script, 60) is True
    assert (script.pings, script.slept) == (3, [1.0, 1.0])


def test_a_timeout_of_zero_is_exactly_one_attempt() -> None:
    script = Script([False])
    assert wait(script, 0) is False
    assert (script.pings, script.slept) == (1, [])
    assert wait(Script([True]), 0) is True


def test_the_wait_gives_up_when_the_time_is_over() -> None:
    script = Script([])
    assert wait(script, 3) is False
    assert script.pings == 4
    assert script.slept == [1.0, 1.0, 1.0]


def test_the_real_sleep_and_clock_are_the_defaults() -> None:
    assert mongo_wait.wait_for.__defaults__ == (time.sleep, time.monotonic)


# --------------------------------------------------------------------------- main


def test_main_exits_zero_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert mongo_wait.main(["--uri", URI, "--timeout", "0"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "mongo_wait: the server answers\n"
    assert captured.err == ""


def test_main_exits_one_and_never_prints_the_uri(
    fake_client: type[FakeClient], capsys: pytest.CaptureFixture[str]
) -> None:
    fake_client.error = PyMongoError("down")
    assert mongo_wait.main(["--uri", URI, "--timeout", "0"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "mongo_wait: no answer within 0 s\n"
    assert "secret" not in captured.out + captured.err


def test_main_waits_for_the_given_number_of_seconds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[float] = []

    def fake_wait(_ping: object, timeout: float) -> bool:
        seen.append(timeout)
        return False

    monkeypatch.setattr(mongo_wait, "wait_for", fake_wait)
    assert mongo_wait.main(["--uri", URI, "--timeout", "2.5"]) == 1
    assert mongo_wait.main(["--uri", URI]) == 1
    assert seen == [2.5, 60.0]
    assert capsys.readouterr().err == (
        "mongo_wait: no answer within 2.5 s\nmongo_wait: no answer within 60 s\n"
    )


def test_main_pings_the_uri_it_was_given(fake_client: type[FakeClient]) -> None:
    mongo_wait.main(["--uri", "mongodb://127.0.0.1:1", "--timeout", "0"])
    assert [c.uri for c in fake_client.instances] == ["mongodb://127.0.0.1:1"]


@pytest.mark.parametrize(
    "argv", [[], ["--timeout", "5"], ["--uri"], ["--uri", URI, "--timeout", "x"]]
)
def test_main_refuses_bad_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        mongo_wait.main(argv)
    assert caught.value.code == 2


def test_the_script_runs_as_a_program_and_exits_with_the_status_of_main() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SANKEY_")}
    done = subprocess.run(  # noqa: S603 - fixed argv; the missing --uri stops it before any connection
        [sys.executable, mongo_wait.__file__],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == 2
    assert "--uri" in done.stderr
