#!/usr/bin/env bash
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

# Targets are product code; tests/, .semgrep/ and vendored assets are in .semgrepignore.
semgrep scan "${configs[@]}" \
  --metrics=off --disable-version-check --error --quiet \
  --sarif --output reports/semgrep.sarif \
  src scripts || status=$?

# Same scan, human readable (the SARIF run above is the machine report).
semgrep scan "${configs[@]}" --metrics=off --disable-version-check --error src scripts
exit "${status:-0}"
