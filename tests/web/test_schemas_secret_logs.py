# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""SPEC section 4: response bodies AND log records never contain a Mongo password.

``test_schemas_settings_out.py`` and ``test_matrix_secrets.py`` cover the bodies. This module
covers the log records, with the root logger on DEBUG and the password ``hunter2``: for every
record the message, the arguments, the whole record dictionary and the formatted text (traceback
included) are searched. The paths are ``merge_settings`` (keeping, replacing, renaming, refusing),
``SettingsOut`` building (local and read-only remote) and the pipeline and cache path (miss, hit,
credential rotation, a driver that fails with the URI in its message).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from sankey_studio.config import BootstrapConfig
from sankey_studio.errors import SankeyError, SettingsError
from sankey_studio.models import AppSettings
from sankey_studio.pipeline import BundleOptions, build_graph_from_draft, cache_key, render_bundle
from sankey_studio.services import Services
from sankey_studio.storage import SettingsStore
from sankey_studio.util import mask_uri
from sankey_studio.web.app import create_app
from sankey_studio.web.schemas import SettingsIn, merge_settings, settings_out
from tests.conftest import TEST_URI, build_connection
from tests.test_pipeline_support import PipelineEnv, make_env, mongo_draft
from tests.web.conftest import SAME_ORIGIN, new_client

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

PASSWORD = "hunter2"
ALPHA = f"mongodb://tester:{PASSWORD}@alpha.invalid:27017/?appName=tests"
BETA = "mongodb://beta-user:s3cret@beta.invalid/?appName=beta"
ROTATED = ALPHA.replace(PASSWORD, "rotated-pw")
SECRETS = (PASSWORD, "s3cret", "rotated-pw")


def leaks(records: list[logging.LogRecord], secret: str = PASSWORD) -> list[str]:
    """Where ``secret`` shows up in ``records``: ``"<logger>: <place>"`` for each hit."""
    formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
    found: list[str] = []
    for record in records:
        places = {
            "message": record.getMessage(),
            "msg": str(record.msg),
            "args": repr(record.args),
            "exc_text": record.exc_text or "",
            "record": repr(vars(record)),
            "formatted": formatter.format(record),
        }
        found.extend(f"{record.name}: {place}" for place, text in places.items() if secret in text)
    return found


def no_secret_in(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


def stored() -> AppSettings:
    return AppSettings(
        mongo_connections=[
            build_connection("alpha", ALPHA, "flows"),
            build_connection("beta", BETA),
        ]
    )


def incoming(*connections: dict[str, Any]) -> SettingsIn:
    return SettingsIn.model_validate({"mongo_connections": list(connections)})


# --------------------------------------------------------------------------- the check itself


def fail() -> None:
    raise RuntimeError(ALPHA)


@pytest.mark.parametrize(
    ("how", "places"),
    [
        ("message", {"root: message", "root: msg", "root: record", "root: formatted"}),
        ("args", {"root: message", "root: args", "root: record", "root: formatted"}),
        ("exception", {"root: record", "root: exc_text", "root: formatted"}),
    ],
)
def test_the_check_sees_a_password_wherever_a_record_can_hold_one(
    caplog: pytest.LogCaptureFixture, how: str, places: set[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    log = logging.getLogger()
    if how == "message":
        message = "connect to " + ALPHA  # a message that was formatted before it was logged
        log.warning(message)
    elif how == "args":
        log.warning("connect to %s", ALPHA)
    else:
        try:
            fail()
        except RuntimeError:
            log.exception("failed")
    assert places <= set(leaks(caplog.records))


def test_the_check_is_quiet_for_a_record_without_the_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    logging.getLogger().warning("connect to %s", mask_uri(ALPHA))
    assert caplog.records
    assert leaks(caplog.records) == []


# --------------------------------------------------------------------------- merge_settings


def merged_and_refused() -> list[AppSettings | SankeyError]:
    """Every outcome of ``merge_settings`` that matters: kept, replaced, renamed, refused."""
    outcomes: list[AppSettings | SankeyError] = []
    requests = [
        [{"name": "alpha"}, {"name": "beta", "uri": ""}],
        [{"name": "alpha", "uri": mask_uri(ALPHA)}],
        [{"name": "alpha", "uri": ROTATED}, {"name": "beta"}],
        [{"name": "gamma", "previous_name": "alpha"}],
        [{"name": "gamma", "previous_name": "alpha", "uri": mask_uri(ALPHA)}],
        [{"name": "brand-new"}],
        [{"name": "alpha", "uri": f"mongodb://tester:{PASSWORD}@alpha.invalid/?tlsInsecure=true"}],
        [{"name": "alpha", "uri": f"http://tester:{PASSWORD}@alpha.invalid/"}],
    ]
    for connections in requests:
        try:
            outcomes.append(merge_settings(stored(), incoming(*connections)))
        except SettingsError as exc:
            outcomes.append(exc)
    return outcomes


def test_merge_settings_logs_no_password(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    outcomes = merged_and_refused()
    refused = [o for o in outcomes if isinstance(o, SankeyError)]
    assert len(outcomes) - len(refused) == 5  # the five good requests
    assert len(refused) == 3  # no secret, a refused option, a refused scheme
    for error in refused:
        no_secret_in(f"{error!s} {error!r} {error.message} {error.details}")
    assert leaks(caplog.records) == []
    assert leaks(caplog.records, "s3cret") == []
    assert PASSWORD not in caplog.text


def test_a_merged_settings_object_does_not_print_its_password() -> None:
    merged = merge_settings(stored(), incoming({"name": "alpha"}))
    no_secret_in(f"{merged!r} {merged!s} {merged.mongo_connections!r}")
    no_secret_in(merged.model_dump_json())


# --------------------------------------------------------------------------- SettingsOut


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_building_settings_out_logs_no_password(
    caplog: pytest.LogCaptureFixture, tmp_path: Path, mode: str
) -> None:
    caplog.set_level(logging.DEBUG)
    config = BootstrapConfig(data_dir=tmp_path / "data", remote_mode=mode == "remote")
    out = settings_out(stored(), config)
    assert [c.name for c in out.mongo_connections] == ["alpha", "beta"]
    no_secret_in(out.model_dump_json())
    no_secret_in(f"{out!r} {out!s} {out.model_dump()}")
    assert leaks(caplog.records) == []
    assert "s3cret" not in caplog.text


# --------------------------------------------------------------------------- pipeline and cache


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


def test_the_pipeline_and_the_cache_log_no_password(
    caplog: pytest.LogCaptureFixture, env: PipelineEnv
) -> None:
    env.mongo["flows"]["links"].insert_one({"source": "a", "target": "b", "value": 1})
    caplog.set_level(logging.DEBUG)
    draft = mongo_draft()
    first = build_graph_from_draft(env.services, draft)
    assert build_graph_from_draft(env.services, draft) is first  # a hit
    key = cache_key(draft, env.services.source_context())
    assert key is not None
    assert render_bundle(env.services, draft, BundleOptions(theme="light")).stats.links == 1
    rotated = [{"name": "test", "uri": TEST_URI.replace(PASSWORD, "rotated-pw")}]
    env.change_settings(mongo_connections=rotated)
    assert build_graph_from_draft(env.services, draft) is not first  # a miss after a rotation
    no_secret_in(key)
    assert leaks(caplog.records) == []
    assert leaks(caplog.records, "rotated-pw") == []
    assert PASSWORD not in caplog.text


# --------------------------------------------------------------------------- a driver that fails


def failing_factory(uri: str, _timeout_ms: int) -> Any:
    """A driver whose error text carries the whole URI, as some real drivers' messages do."""
    raise ServerSelectionTimeoutError(f"cannot reach {uri}")


@pytest.fixture
def broken(tmp_path: Path) -> Iterator[Services]:
    config = BootstrapConfig(data_dir=tmp_path / "data")
    SettingsStore(config).save(AppSettings(mongo_connections=[build_connection("test", TEST_URI)]))
    services = Services.create(config, mongo_factory=failing_factory)
    yield services
    services.close()


def test_a_driver_error_with_the_uri_in_its_text_reaches_no_message_and_no_log(
    caplog: pytest.LogCaptureFixture, broken: Services
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(SankeyError) as caught:
        build_graph_from_draft(broken, mongo_draft())
    no_secret_in(f"{caught.value!s} {caught.value!r} {caught.value.message} {caught.value.details}")
    assert leaks(caplog.records) == []


def test_the_route_that_serves_a_failing_driver_answers_and_logs_no_password(
    caplog: pytest.LogCaptureFixture, broken: Services
) -> None:
    caplog.set_level(logging.DEBUG)
    app = create_app(broken.config, services=broken)
    body = mongo_draft().model_dump(mode="json")
    with new_client(app, SAME_ORIGIN, raise_exc=False) as client:
        answer = client.post("/api/v1/preview", json=body)
    assert answer.status_code >= 400
    no_secret_in(answer.text)
    assert caplog.records
    assert leaks(caplog.records) == []
    assert PASSWORD not in caplog.text
