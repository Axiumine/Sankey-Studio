# Semgrep rule tests: `semgrep --test --config .semgrep/rules .semgrep/rules`
import os
import pickle
import re
import subprocess
import tempfile

import httpx
import requests
import yaml
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from markupsafe import Markup


def shell(cmd, argv):
    # ruleid: sankey-no-shell-true
    subprocess.run(cmd, shell=True, check=False)
    # ok: sankey-no-shell-true
    subprocess.run(argv, check=False)


def dynamic(blob, text):
    # ruleid: sankey-no-dynamic-code
    eval(text)
    # ruleid: sankey-no-dynamic-code
    pickle.loads(blob)
    # ruleid: sankey-no-dynamic-code
    yaml.load(text)
    # ok: sankey-no-dynamic-code
    yaml.safe_load(text)


def oscmd(cmd):
    # ruleid: sankey-no-os-command
    os.system(cmd)
    # ruleid: sankey-no-os-command
    tempfile.mktemp()
    # ok: sankey-no-os-command
    tempfile.mkstemp()


def mongo(coll, docs, query):
    # ruleid: sankey-no-mongo-writes
    coll.insert_one({"a": 1})
    # ruleid: sankey-no-mongo-writes
    coll.delete_many(query)
    # ruleid: sankey-no-mongo-writes
    coll.database.drop_collection("x")
    # ok: sankey-no-mongo-writes
    coll.find(query)
    # ok: sankey-no-mongo-writes
    coll.aggregate(docs)
    # ok: sankey-no-mongo-writes
    coll.count_documents(query)


def js_in_mongo():
    # ruleid: sankey-no-js-in-mongo
    bad = {"$where": "this.a > 1"}
    # ruleid: sankey-no-js-in-mongo
    stage = "$out"
    # ok: sankey-no-js-in-mongo
    fine = {"$match": {"a": 1}}  # variables stay unused: semgrep propagates constants into uses


def logs(log, conn, uri):
    # ruleid: sankey-no-secret-in-logs
    log.info("connect %s", conn.uri.get_secret_value())
    # ruleid: sankey-no-secret-in-logs
    log.error(f"bad {conn.uri.get_secret_value()}")
    # ok: sankey-no-secret-in-logs
    log.info("connect %s", conn.name)
    # ok: sankey-no-secret-in-logs
    uri.get_secret_value()


def exceptions(conn):
    # ruleid: sankey-no-secret-in-exceptions
    raise ValueError(f"cannot reach {conn.uri.get_secret_value()}")


def exceptions_ok(conn):
    # ok: sankey-no-secret-in-exceptions
    raise ValueError(f"cannot reach {conn.name}")


def http(url):
    # ruleid: sankey-no-outbound-http
    requests.get(url, timeout=3)
    # ruleid: sankey-no-outbound-http
    httpx.get(url, timeout=3)


def html(name, tpl):
    # ruleid: sankey-no-unsafe-html
    Markup(name)
    # ruleid: sankey-no-unsafe-html
    HTMLResponse(f"<h1>{name}</h1>")
    # ok: sankey-no-unsafe-html
    HTMLResponse("<h1>static</h1>")
    return tpl


def cors(app):
    # ruleid: sankey-no-cors
    app.add_middleware(CORSMiddleware, allow_origins=["*"])


def binds(uvicorn, app, trusted):
    # ruleid: sankey-no-wildcard-bind-or-hosts
    uvicorn.run(app, host="0.0.0.0")
    # ruleid: sankey-no-wildcard-bind-or-hosts
    trusted(app, allowed_hosts=["*"])
    # ok: sankey-no-wildcard-bind-or-hosts
    uvicorn.run(app, host="127.0.0.1")


_FIXED = re.compile(r"^[a-z]+$")
FIXED_CONST = r"^x$"


def regexes(user_text, pattern):
    # ruleid: sankey-regex-from-variable
    re.compile(pattern)
    # ruleid: sankey-regex-from-variable
    re.search(user_text, "abc")
    # ok: sankey-regex-from-variable
    re.compile(re.escape(user_text))
    # ok: sankey-regex-from-variable
    re.compile(r"^[a-z]+$")
    # ok: sankey-regex-from-variable
    re.compile(FIXED_CONST)
    # ok: sankey-regex-from-variable
    re.compile(FIXED_CONST.removeprefix("^"))
    return _FIXED
