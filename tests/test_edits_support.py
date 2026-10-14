"""Helpers of ``tests/test_edits_*.py`` (no tests here).

``make_edit_env`` builds ``Services`` over an isolated data dir and an in-memory MongoDB (the
connection ``test``, default database ``flows``); ``Access`` picks the operator flags. The
draft builders return ``EditRequest`` objects, ``consenting`` adds the saved preference a
dialog would store.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sankey_studio.config import BootstrapConfig
from sankey_studio.edits.target import write_target
from sankey_studio.models import (
    AppSettings,
    EditRequest,
    GraphDraft,
    Link,
    ManualSource,
    MongoSource,
    StyleSpec,
    TextSource,
    TransformSpec,
)
from sankey_studio.services import Services
from sankey_studio.storage import SettingsStore
from tests.conftest import build_connection
from tests.test_pipeline_support import RecordingCache

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import SourceSpec

Access = Literal["local", "remote_ro", "remote_writes", "remote_all"]
CSV = (
    "source,target,value,category\n"
    "Salary,Budget,3000,Income\n"
    "Budget,Rent,1200,Housing\n"
    "Budget,Food,640,\n"
)
ADD = {"op": "add_entry", "source": "Budget", "target": "Gifts", "value": 50, "category": "Fun"}
CATEGORISE = {"op": "set_category", "source": "Budget", "target": "Food", "category": "Fun"}
REORDER = {"op": "reorder", "order": ["Salary", "Budget", "Food", "Rent"]}
FLAGS: dict[str, dict[str, bool]] = {
    "local": {},
    "remote_ro": {"remote_mode": True},
    "remote_writes": {"remote_mode": True, "remote_writes": True},
    "remote_all": {"remote_mode": True, "remote_writes": True, "source_writes": True},
}


@dataclass(slots=True)
class EditEnv:
    """Services, the in-memory MongoDB and a recording cache."""

    services: Services
    config: BootstrapConfig
    mongo: MongoClient[Any]
    cache: RecordingCache

    @property
    def sources_dir(self) -> Path:
        return self.services.sources_dir()

    def write_source(self, name: str, text: str) -> Path:
        path = self.sources_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


@contextmanager
def make_edit_env(
    tmp_path: Path,
    mongo_client: MongoClient[Any],
    access: Access = "local",
    database: str | None = "flows",
) -> Iterator[EditEnv]:
    config = BootstrapConfig.model_validate({"data_dir": tmp_path / "data", **FLAGS[access]})
    services = Services.create(config, mongo_factory=lambda _uri, _timeout: mongo_client)
    settings = AppSettings(mongo_connections=[build_connection(default_database=database)])
    SettingsStore(config).save(settings)  # a read-only server could not save them itself
    try:
        yield EditEnv(services, config, mongo_client, RecordingCache())
    finally:
        services.close()


def request(source: SourceSpec, edit: dict[str, Any], **transform: Any) -> EditRequest:
    """An ``EditRequest`` for ``source`` and the JSON of one edit (``style=`` sets the style)."""
    style = StyleSpec.model_validate(transform.pop("style", {}))
    draft = GraphDraft(
        source=source, transform=TransformSpec.model_validate(transform), style=style
    )
    return EditRequest.model_validate({"draft": draft.model_dump(), "edit": edit})


def inline(text: str = CSV, **fields: Any) -> TextSource:
    return TextSource(content=text, **fields)


def file_source(path: str = "flows.csv", **fields: Any) -> TextSource:
    return TextSource(origin="file", path=path, **fields)


def manual(*rows: tuple[str, str, float, str | None]) -> ManualSource:
    return ManualSource(
        links=[Link(source=s, target=t, value=v, category=c) for s, t, v, c in rows]
    )


def mongo_source(**fields: Any) -> MongoSource:
    """Find mode on ``flows.events`` of the connection ``test``, mapped like ``seed_events``."""
    spec = {
        "connection": "test",
        "database": "flows",
        "collection": "events",
        "category_field": "cat",
        **fields,
    }
    return MongoSource.model_validate(spec)


def consenting(
    source: SourceSpec, env: EditEnv, mode: Literal["source", "graph"] = "source"
) -> SourceSpec:
    """``source`` with the preference the consent dialog would have saved for its target."""
    key = write_target(source, env.services.settings())
    fields = {**source.model_dump(), "write_back": {"mode": mode, "target": key}}
    return type(source).model_validate(fields)


def seed_events(env: EditEnv, count: int = 3) -> None:
    """``flows.events``: ``a -> b`` documents with a value, plus one ``b -> c``."""
    docs = [{"source": "a", "target": "b", "value": 10 + i} for i in range(count)]
    docs.append({"source": "b", "target": "c", "value": 5, "cat": "Old"})
    env.mongo["flows"]["events"].insert_many(docs)
