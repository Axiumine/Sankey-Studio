"""The small pydantic models of the settings, sources and mongo routers refuse unknown fields.

Their ``model_config`` is only reachable by building a model directly: a response is never
validated against input, so no route test can tell ``extra="forbid"`` from ``"ignore"``, and the
global 422 handler already drops the submitted input, so only a direct validation shows that
``hide_input_in_errors`` is on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from pydantic import BaseModel, ValidationError

from sankey_studio.sources.mongo_inspect import FieldSuggestion
from sankey_studio.web.routers.mongo import SampleOut
from sankey_studio.web.routers.settings import MongoProbeOk, ProbeOk
from sankey_studio.web.routers.sources import DetectIn, DetectOut, FilePreview

if TYPE_CHECKING:
    from collections.abc import Mapping

SUGGESTED = {"source": "a", "target": "b", "value": "v", "category": None}


class Model(NamedTuple):
    """A model, a valid payload and a payload with one field of the wrong type."""

    cls: type[BaseModel]
    valid: Mapping[str, Any]
    wrong_type: Mapping[str, Any]


MODELS = [
    Model(ProbeOk, {"ok": True}, {"ok": [987654]}),
    Model(MongoProbeOk, {"ok": True, "latency_ms": 1.5}, {"latency_ms": [987654]}),
    Model(SampleOut, {"documents": [], "suggested": SUGGESTED}, {"documents": 987654}),
    Model(DetectIn, {"sample": "a,b"}, {"sample": 987654}),
    Model(DetectOut, {"format": "csv"}, {"format": 987654}),
    Model(FilePreview, {"name": "a.csv", "lines": []}, {"name": 987654, "lines": []}),
]
IDS = [m.cls.__name__ for m in MODELS]


@pytest.mark.parametrize("model", MODELS, ids=IDS)
def test_a_valid_payload_builds_and_an_unknown_field_is_refused(model: Model) -> None:
    built = model.cls.model_validate(model.valid)
    assert built.model_dump(mode="json") == model.valid
    with pytest.raises(ValidationError) as info:
        model.cls.model_validate({**model.valid, "surprise": 1})
    assert [(e["type"], e["loc"]) for e in info.value.errors()] == [
        ("extra_forbidden", ("surprise",))
    ]


def test_the_defaults_of_the_probe_answers() -> None:
    assert ProbeOk().ok is True
    assert ProbeOk().model_dump() == {"ok": True}
    assert MongoProbeOk(latency_ms=2.5).model_dump() == {"ok": True, "latency_ms": 2.5}


def test_a_suggestion_is_carried_through_the_sample_answer() -> None:
    suggested = FieldSuggestion(source="a", target="b", value="v", category=None)
    built = SampleOut(documents=[{"a": 1}], suggested=suggested)
    assert built.model_dump(mode="json") == {"documents": [{"a": 1}], "suggested": SUGGESTED}


@pytest.mark.parametrize("model", MODELS[3:], ids=IDS[3:])
def test_the_source_bodies_never_echo_the_input_of_a_validation_error(model: Model) -> None:
    payload = {**model.valid, **model.wrong_type}
    with pytest.raises(ValidationError) as info:
        model.cls.model_validate(payload)
    text = str(info.value)
    assert "987654" not in text
    assert "input_value" not in text
