#!/usr/bin/env bash
# Run Qodana (Ultimate Plus) on this project.
#
# The licence token QODANA_TOKEN is read from .env (see .env.example) into THIS process only.
# It is never printed, never written to a file and never put on a command line; the qodana CLI
# picks it up from the environment. Results upload to Qodana Cloud when the token is valid.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  . ./.env
  set +a
fi
if [ -z "${QODANA_TOKEN:-}" ]; then
  echo "QODANA_TOKEN is not set: put it in .env (see .env.example)." >&2
  exit 2
fi
export QODANA_TOKEN

RESULTS=reports/qodana
SCRATCH=.qodana
# A fresh, empty venv directory every run: uv must never have to delete a mount point. The mount
# targets must exist before docker starts, or docker would create them owned by root.
rm -rf "$SCRATCH/venv"
mkdir -p "$RESULTS" "$SCRATCH/venv" "$SCRATCH/empty" .venv

args=(
  scan
  --linter qodana-python
  --image "${QODANA_IMAGE:-jetbrains/qodana-python:2026.2}"
  --project-dir .
  --results-dir "$RESULTS/results"
  --report-dir "$RESULTS/report"
  --print-problems
  --skip-pull
)
# Python environment. The container user has no writable HOME and the host .venv points at host
# paths (its interpreter is a symlink into ~/.local/share/uv), so Qodana cannot use it. The
# `bootstrap` in qodana.yaml builds a fresh Python 3.14 venv with `uv sync` inside the container;
# it lands in .qodana/venv on the host, mounted over /data/project/.venv (the host .venv is shadowed,
# never modified) and QODANA_PYTHON_PATH tells the IDE which interpreter it is. uv's cache and
# managed interpreter live in Qodana's own cache dir (/data/cache), so later runs are fast.
args+=(
  --volume "$PWD/$SCRATCH/venv:/data/project/.venv"
  --env QODANA_PYTHON_PATH=/data/project/.venv/bin/python
)

# mutmut's copy of the sources (mutants/src/sankey_studio/...) ends in the same paths as src/, so the
# coverage importer matches the measured files to the copy, which the analysis excludes, and then
# reports that no coverage was computed. An empty directory hides the copy from the container.
if [ -d mutants ]; then
  args+=(--volume "$PWD/$SCRATCH/empty:/data/project/mutants")
fi

# Import the coverage that `make cov` measured. Only the Cobertura XML is handed over: the binary
# .coverage file needs a Python interpreter to be converted, and the html report is noise. coverage.py
# records the host checkout as <source>, which does not exist in the container (the project is
# mounted at /data/project), so that one element is rewritten in a throw-away copy.
COVERAGE_DIR="$SCRATCH/code-coverage"
rm -rf "$COVERAGE_DIR"
if [ -f reports/coverage/coverage.xml ]; then
  mkdir -p "$COVERAGE_DIR"
  sed 's#<source>[^<]*</source>#<source>/data/project</source>#' \
    reports/coverage/coverage.xml >"$COVERAGE_DIR/coverage.xml"
  args+=(--coverage-dir "$COVERAGE_DIR")
else
  echo "reports/coverage/coverage.xml is missing: run 'make cov' first, or the coverage gate fails." >&2
fi

exec qodana --disable-update-checks "${args[@]}" "$@"
