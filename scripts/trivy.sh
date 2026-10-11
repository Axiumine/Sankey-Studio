#!/usr/bin/env bash
# Trivy filesystem scan: vulnerable dependencies (uv.lock), secrets, IaC misconfigurations,
# forbidden licences. Config: trivy.yaml; accepted findings: .trivyignore.
#
#   TRIVY_OFFLINE=1  reuse the cached vulnerability DB (no network)
#   TRIVY_IMAGE=...  override the pinned image
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${TRIVY_IMAGE:-aquasec/trivy:0.75.0}"
mkdir -p reports .trivy-cache

trivy() {
  docker run --rm --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e TRIVY_CACHE_DIR=/cache \
    -v "$PWD/.trivy-cache:/cache" -v "$PWD:/src" -w /src \
    "$IMAGE" "$@"
}

extra=()
if [ "${TRIVY_OFFLINE:-0}" = 1 ]; then
  extra+=(--skip-db-update --skip-java-db-update --offline-scan)
fi

# 1. SARIF report for dashboards / Qodana; never fails the run.
trivy fs --config trivy.yaml --format sarif --output reports/trivy.sarif --exit-code 0 \
  "${extra[@]+"${extra[@]}"}" .

# 2. Human readable table; exits non-zero on unfixed-ignored HIGH/CRITICAL findings.
trivy fs --config trivy.yaml "${extra[@]+"${extra[@]}"}" .
