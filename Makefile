.PHONY: sync lint format typecheck caps test e2e e2e-serial e2e-mongo cov memray profile mutate mutate-gate \
        semgrep semgrep-test trivy qodana security gitnexus gitnexus-status hooks \
        check ci full serve mongo-up mongo-down clean

PY := uv run
SRC := src tests scripts

sync:
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

# pre-commit check 1.1: file 500 / function 50 / class 300 / params 4 / nesting 4, ratcheted
caps:
	uv run --no-project --python 3.14 python scripts/check_code_caps.py

# ---------------------------------------------------------------- tests
test:
	$(PY) pytest -m "not memory and not e2e"

# end-to-end: the real app on 127.0.0.1:<ephemeral port> (mongomock, no MongoDB) driven over HTTP and
# by real Chrome (Playwright); failure artefacts (screenshot, trace) go to .e2e-artifacts/
# The suite is split into E2E_SHARDS slices of whole modules (tests/e2e/support/shard.py) that run as
# parallel pytest processes: it is waiting-bound (Chrome, HTTP), so one slice takes about as long as
# the whole suite divided by the slices; one process needs about 5 minutes. A failing slice fails
# the target after the others have finished. `make e2e-serial` runs everything in one process
# (debugging); `make e2e E2E_SHARDS=1` is the same.
E2E_SHARDS ?= 5
E2E_PYTEST := $(PY) pytest tests/e2e -m "e2e and not mongo" -p no:cacheprovider

e2e:
	$(MAKE) --no-print-directory -O -j$(E2E_SHARDS) \
	  $(addprefix e2e-shard-,$(shell seq 1 $(E2E_SHARDS)))

e2e-shard-%:
	E2E_SHARD=$*/$(E2E_SHARDS) $(E2E_PYTEST)

e2e-serial:
	$(E2E_PYTEST)

# the same flows against a REAL MongoDB. Needs SANKEY_TEST_MONGO_URI, e.g. the project-local compose
# Mongo (`make mongo-up`): SANKEY_TEST_MONGO_URI=mongodb://127.0.0.1:27117 make e2e-mongo
# Not part of check / ci / full (they must pass without any database).
e2e-mongo:
	$(PY) pytest -m "e2e and mongo"

# 100% line + branch coverage of src/sankey_studio from the unit suite (slow tests included, e2e
# excluded: it must hold without a browser; `make e2e` runs the live-server tests)
cov:
	$(PY) pytest -m "not memory and not e2e" --cov --cov-report=term-missing:skip-covered \
	  --cov-report=xml --cov-report=html

# memory-budget tests (pytest-memray); fails when a test exceeds its limit_memory marker
memray:
	$(PY) pytest -m memory --memray --trace-python-allocators

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

# enable the versioned hooks (pre-commit: code caps, commit-msg: message format)
hooks:
	git config core.hooksPath .githooks

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

clean:
	rm -rf .ruff_cache .mypy_cache .pytest_cache .coverage htmlcov .memray reports mutants .trivy-cache
