"""E2E.md section C, safety net: the real-Mongo suite refuses the MongoDBs of other projects.

These tests need no MongoDB (they judge a string) and always run. The project-local compose Mongo
(``make mongo-up``) listens on 127.0.0.1:27117; 27017-27019 on this machine belong to other
projects, and a URI without a port means 27017.
"""

from __future__ import annotations

import pytest

from tests.e2e.support.http_b_world import real_world, secrets_of, targets_foreign_mongo


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://127.0.0.1:27017",
        "mongodb://127.0.0.1:27018/?replicaSet=rs",
        "mongodb://user:pw@localhost:27019/db",
        "mongodb://localhost",
        "mongodb://127.0.0.1",
    ],
)
def test_the_ports_of_other_projects_are_refused(uri: str) -> None:
    assert targets_foreign_mongo(uri)
    with pytest.raises(pytest.fail.Exception, match="27017-27019"):
        real_world(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://127.0.0.1:27117",
        "mongodb://localhost:27117/?directConnection=true",
        "mongodb://mongo.example.test:27017",
        "mongodb+srv://cluster.example.test",
        "mongodb://a:27017,b:27017/?replicaSet=rs",
    ],
)
def test_the_project_mongo_and_other_hosts_are_not_refused(uri: str) -> None:
    assert not targets_foreign_mongo(uri)


def test_only_credentials_that_cannot_occur_by_chance_are_scanned_for() -> None:
    assert secrets_of("mongodb://127.0.0.1:27117") == ()
    assert secrets_of("mongodb://u:s3cr3t-pass@h:27117") == ("s3cr3t-pass", "u:s3cr3t-pass@")
    assert secrets_of("mongodb://u:pw@h:27117") == ("u:pw@",)  # "pw" alone would match any text
    assert secrets_of("mongodb://u:p%40ss%3Aword@h") == ("p@ss:word", "u:p@ss:word@")
