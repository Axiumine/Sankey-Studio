#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
# Semgrep: project rules (.semgrep/rules) + registry packs, scanning product code only.
#
#   SEMGREP_OFFLINE=1  project rules only (registry packs need network)
#   SEMGREP_IMAGE=...  override the pinned image
#   scripts/semgrep.sh --test   run the rule tests (.semgrep/rules/*.py|js|html)
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${SEMGREP_IMAGE:-semgrep/semgrep:1.178.0}"
mkdir -p reports

semgrep() {
  docker run --rm --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e SEMGREP_SEND_METRICS=off \
    -v "$PWD:/src" -w /src \
    "$IMAGE" semgrep "$@"
}

if [ "${1:-}" = "--test" ]; then
  exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e SEMGREP_SEND_METRICS=off \
    -v "$PWD:/src" -w /src "$IMAGE" \
    semgrep --test --config .semgrep/rules .semgrep/rules --metrics=off --disable-version-check
fi

configs=(--config .semgrep/rules)
if [ "${SEMGREP_OFFLINE:-0}" != 1 ]; then
  configs+=(
    --config p/python --config p/security-audit --config p/owasp-top-ten
    --config p/javascript --config p/secrets --config p/xss
  )
fi

# Two generic registry rules cannot tell safe template output from unsafe, and inline waivers are
# forbidden in templates (tests/test_policy.py), so they are excluded here, by id, with the reason:
#  - var-in-href: every href in templates/ comes from a server-side constant table (/, /graphs/new,
#    /settings, ...), never from request data, and the CSP blocks javascript: navigation anyway.
#  - var-in-script-tag: the only template variable inside a <script> is the page boot block,
#    <script type="application/json">{{ boot|tojson }}</script>: tojson escapes < > & and ' so the
#    JSON cannot close the tag, and the type makes the browser treat it as data, never as code.
# The project rules (.semgrep/rules) still scan the templates, and tests/web/test_*policy*.py
# pin the boot block shape and ban |safe, innerHTML and inline handlers.
excluded=(
  --exclude-rule generic.html-templates.security.var-in-href.var-in-href
  --exclude-rule generic.html-templates.security.var-in-script-tag.var-in-script-tag
)

# Targets are product code; tests/, .semgrep/ and vendored assets are in .semgrepignore.
semgrep scan "${configs[@]}" "${excluded[@]}" \
  --metrics=off --disable-version-check --error --quiet \
  --sarif --output reports/semgrep.sarif \
  src scripts || status=$?

# Same scan, human readable (the SARIF run above is the machine report).
semgrep scan "${configs[@]}" "${excluded[@]}" --metrics=off --disable-version-check --error \
  src scripts
exit "${status:-0}"
