.PHONY: sync lint format typecheck caps test e2e e2e-serial e2e-mongo e2e-mongo-rs cov memray profile mutate mutate-gate \
        semgrep semgrep-test trivy qodana security gitnexus gitnexus-status hooks hooks-check \
        gate-commit gate-push gate-main gate-release check ci full serve mongo-up mongo-down mongo-absent clean

PY := uv run
SRC := src tests scripts

# The git hooks run every check through scripts/githook_gate.py, which calls the targets below.
# It appends JUNIT=<report path> to the pytest-based ones (test cov memray e2e e2e-mongo e2e-mongo-rs): the
# targets then also write a JUnit report, and the gate fails on any skipped test.
JUNIT ?=
junit = $(if $(JUNIT),--junitxml="$(JUNIT:.xml=$(1).xml)")

sync: hooks
	uv sync --all-extras

# ---------------------------------------------------------------- static checks
lint:
	$(PY) ruff check $(SRC)
	$(PY) ruff format --check $(SRC)

format:
	$(PY) ruff check --fix $(SRC)
	$(PY) ruff format $(SRC)

typecheck:
	$(PY) mypy

# code caps: file 500 / function 50 / class 300 / params 4 / nesting 4, ratcheted
# (the `fast` check of the pre-commit hook: lint + typecheck + caps)
caps:
	uv run --no-project --python 3.14 python scripts/check_code_caps.py

# ---------------------------------------------------------------- tests
test:
	$(PY) pytest -m "not memory and not e2e" $(call junit,)

# end-to-end: the real app on 127.0.0.1:<ephemeral port> (mongomock, no MongoDB) driven over HTTP and
# by real Chrome (Playwright); failure artefacts (screenshot, trace) go to .e2e-artifacts/
# The suite is split into E2E_SHARDS slices of whole modules (tests/e2e/support/shard.py) that run as
# parallel pytest processes: it is waiting-bound (Chrome, HTTP), so one slice takes about as long as
# the whole suite divided by the slices; one process needs about 5 minutes. A failing slice fails
# the target after the others have finished. `make e2e-serial` runs everything in one process
# (debugging); `make e2e E2E_SHARDS=1` is the same.
E2E_SHARDS ?= 5
E2E_PYTEST := $(PY) pytest tests/e2e -m "e2e and not mongo and not mongo_rs" -p no:cacheprovider

e2e:
	$(MAKE) --no-print-directory -O -j$(E2E_SHARDS) \
	  $(addprefix e2e-shard-,$(shell seq 1 $(E2E_SHARDS)))

e2e-shard-%:
	E2E_SHARD=$*/$(E2E_SHARDS) $(E2E_PYTEST) $(call junit,-$*)

e2e-serial:
	$(E2E_PYTEST)

# the same flows against a REAL MongoDB, then the mongo-marked unit tests (they skip in `make cov`).
# Needs SANKEY_TEST_MONGO_URI, e.g. the project-local compose Mongo (`make mongo-up`):
#   SANKEY_TEST_MONGO_URI=mongodb://127.0.0.1:27117 make e2e-mongo
# Not part of check / ci / full (they must pass without any database). The release gate runs it
# (pre-push of main or a tag): `scripts/githook_gate.py` starts and stops the Mongo itself.
# Two selections, two processes: the e2e ones keep a Playwright loop alive for the whole session.
e2e-mongo:
	$(PY) pytest -m "e2e and mongo" $(call junit,-1)
	$(PY) pytest -m "mongo and not e2e" $(call junit,-2)

# the same real-MongoDB flows against a REPLICA SET you run yourself (the compose Mongo is one
# standalone node). Needs SANKEY_TEST_MONGO_RS_URI in the environment or in the repo-root dotenv file
# (only that key is used from it), e.g.
#   mongodb://user:pw@h1,h2,h3/sankey_test_rs?replicaSet=rs0&authSource=sankey_test_rs
# The release gate runs it too (the e2e-mongo-rs check, pre-push of main or a tag): without the URI the
# tests skip and a skip fails the check, so that push needs the cluster reachable. Not in check / ci /
# full (they must pass without any database). Everything happens in the database named in the URI
# path, which must be empty: its collections are dropped at teardown, the database stays (see
# docs/e2e.md, "Replica set").
e2e-mongo-rs:
	$(PY) pytest tests/e2e/mongo_rs -m "e2e and mongo_rs" -p no:cacheprovider $(call junit,)

# 100% line + branch coverage of src/sankey_studio from the unit suite (slow tests included, e2e
# excluded; `make e2e` runs the live-server tests). The threshold is reachable without a browser, but
# the hook gate fails on any skipped test: it needs Chrome, node, bash and Linux /proc
cov:
	$(PY) pytest -m "not memory and not e2e" --cov --cov-report=term-missing:skip-covered \
	  --cov-report=xml --cov-report=html $(call junit,)

# memory-budget tests (pytest-memray); fails when a test exceeds its limit_memory marker
memray:
	$(PY) pytest -m memory --memray --trace-python-allocators $(call junit,)

# whole-pipeline profile: writes .memray/bench.bin, prints stats, renders a flamegraph
profile:
	mkdir -p .memray
	$(PY) memray run --force -o .memray/bench.bin scripts/profile_memory.py
	$(PY) memray stats .memray/bench.bin
	$(PY) memray flamegraph --force -o .memray/bench-flamegraph.html .memray/bench.bin

# mutation testing: mutmut 3.x (config in pyproject [tool.mutmut]); gate = score >= 90%
# mutmut copies non-Python files (templates, static) only once, so a stale mutants/ judges old
# markup: always start from a clean copy.
# workers: mutmut defaults to one per CPU, which exhausts memory on big machines
MUTATE_CHILDREN ?= 8
mutate:
	rm -rf mutants
	$(PY) mutmut run --max-children $(MUTATE_CHILDREN)

mutate-gate:
	$(PY) python scripts/mutation_gate.py --min-score 90

# ---------------------------------------------------------------- security / quality scanners
semgrep:
	scripts/semgrep.sh

semgrep-test:
	scripts/semgrep.sh --test

trivy:
	scripts/trivy.sh

# Qodana Ultimate Plus: needs QODANA_TOKEN in .env (see .env.example); uploads to Qodana Cloud
qodana:
	scripts/qodana.sh

security: semgrep-test semgrep trivy

# ---------------------------------------------------------------- code intelligence + hooks
gitnexus:
	gitnexus analyze --pdg

gitnexus-status:
	gitnexus status

# enable the versioned hooks: pre-commit and pre-merge-commit (fast: lint typecheck caps), commit-msg
# (message format), pre-push (new commit messages, then cov memray e2e; main and tags also security
# and the release checks). Logic: scripts/githook_gate.py, docs/quality.md.
hooks:
	git config core.hooksPath .githooks

# verify core.hooksPath and the hook file modes (git ls-files -s); not a pytest test: mutmut copies
# have no index
GATE := uv run --no-project --python 3.14 python -m scripts.githook_gate
hooks-check:
	$(GATE) hooks-check

# The same checks as the hooks, for a human at a terminal: each one writes a stamp for the tree of
# HEAD (needs a clean working tree), and the next commit or push finds it. Cumulative tiers:
# commit (fast), push (+ cov memray e2e), main (+ security), release (+ e2e-mongo e2e-mongo-rs qodana mutation)
gate-commit:
	$(GATE) run commit

gate-push:
	$(GATE) run push

gate-main:
	$(GATE) run main

gate-release:
	$(GATE) run release

# ---------------------------------------------------------------- aggregates
check: lint typecheck caps cov memray

ci: check security e2e

full: ci mutate mutate-gate qodana

# ---------------------------------------------------------------- run
serve:
	$(PY) sankey-studio serve

# project-local MongoDB on 127.0.0.1:27117 (never touches other local Mongo instances)
mongo-up:
	docker compose up -d mongo

mongo-down:
	docker compose down

# exit 0 only when docker answers and no project Mongo container is running: the hooks start (and
# later stop) the Mongo themselves only then; they never stop one that was already there
mongo-absent:
	@ids="$$(docker compose ps -q mongo)" && test -z "$$ids"

clean:
	rm -rf .ruff_cache .mypy_cache .pytest_cache .coverage htmlcov .memray reports mutants .trivy-cache
