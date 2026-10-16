# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
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
        "mongodb://127.0.0.1:27017,127.0.0.1:27018/?replicaSet=rs",
        "mongodb://u:pw@10.0.0.5:27017,localhost:27019/db?replicaSet=rs",
        "mongodb://[::1]:27018,10.0.0.5:27017",
        "MongoDB://localhost:27017",
        "mongodb://127.0.0.2:27017",
        "mongodb://127.1:27018",
        "mongodb://0.0.0.0:27019",
        "mongodb://localhost.:27017",
        "mongodb://LOCALHOST",
        "mongodb://[0:0:0:0:0:0:0:1]:27017",
        "mongodb://[::ffff:127.0.0.1]:27018",
        "mongodb://2130706433:27017",
    ],
)
def test_the_ports_of_other_projects_are_refused(uri: str) -> None:
    assert targets_foreign_mongo(uri)
    with pytest.raises(pytest.fail.Exception, match="27017-27019"):
        real_world(uri)


def test_the_refusal_names_the_variable_the_uri_came_from() -> None:
    with pytest.raises(pytest.fail.Exception, match="SANKEY_TEST_MONGO_RS_URI points at"):
        real_world("mongodb://127.0.0.1:27017", env="SANKEY_TEST_MONGO_RS_URI")


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://127.0.0.1:27117",
        "mongodb://localhost:27117/?directConnection=true",
        "mongodb://mongo.example.test:27017",
        "mongodb+srv://cluster.example.test",
        "mongodb://a:27017,b:27017/?replicaSet=rs",
        "mongodb://u:pw@10.0.0.5:27017,10.0.0.6,10.0.0.7:27018/db?replicaSet=rs",
        "mongodb://127.0.0.1:27117,127.0.0.1:27118/?replicaSet=rs",
        "mongodb://[::1]:27117",
        "mongodb://127.0.0.2:27117",
        "mongodb://10.0.0.5:27017",
        "mongodb://[2001:db8::1]:27017",
        "mongodb://example.test.:27017",
        "mongodb://host:notaport",
        "mongodb://",
        "not a uri",
    ],
)
def test_the_project_mongo_and_other_hosts_are_not_refused(uri: str) -> None:
    assert not targets_foreign_mongo(uri)


def test_only_credentials_that_cannot_occur_by_chance_are_scanned_for() -> None:
    assert secrets_of("mongodb://127.0.0.1:27117") == ()
    assert secrets_of("mongodb://u:s3cr3t-pass@h:27117") == ("s3cr3t-pass", "u:s3cr3t-pass@")
    assert secrets_of("mongodb://u:pw@h:27117") == ("u:pw@",)  # "pw" alone would match any text
    assert secrets_of("mongodb://u:p%40ss%3Aword@h") == ("p@ss:word", "u:p@ss:word@")
