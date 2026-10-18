#!/bin/bash -eu
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
#
# ClusterFuzzLite build script: the base image's `compile` runs it in the image built from
# .clusterfuzzlite/Dockerfile, with the project as the working directory and $OUT as the place the
# fuzz targets must end up. See docs/fuzzing.md.
#
# Each tests/fuzz/<name>_fuzzer.py becomes
#   $OUT/<name>_fuzzer.pkg   a PyInstaller one-file build: CPython 3.14, atheris, the project and
#                            its locked packages (the runner image has no Python 3.14),
#   $OUT/<name>_fuzzer       the launcher the runner starts,
# and tests/fuzz/corpus/<name> and tests/fuzz/dict/<name>_fuzzer.dict are shipped beside them.
#
# The base image's python3 (3.11) is left alone: its `compile` script runs it to find atheris'
# sanitizer libraries. Only ${FUZZ_VENV} (Python 3.14) runs the project. The targets are pure
# Python, so the launcher does NOT preload the sanitizer runtime (the ClusterFuzzLite Python guide
# says to leave LD_PRELOAD out then) and the "address" sanitizer only names the run.

set -eu

FUZZ_VENV=${FUZZ_VENV:-/opt/fuzz-venv}
FUZZ_JOBS=${FUZZ_JOBS:-$(nproc)}

if [ "${SANITIZER:-address}" = coverage ]; then
  echo "build.sh: the coverage sanitizer is not supported for these Python fuzz targets" >&2
  exit 1
fi

build_one() {
  local script=$1 name work
  name=$(basename "$script" .py)
  work="$WORK/pyinstaller/$name"
  mkdir -p "$work"
  "$FUZZ_VENV/bin/pyinstaller" --distpath "$OUT" --workpath "$work" --specpath "$work" \
    --onefile --log-level WARN --name "$name.pkg" \
    --paths "$PWD" --paths "$PWD/src" "$script"
  # The runner takes every executable file that mentions LLVMFuzzerTestOneInput for a fuzz
  # target. Only the launcher may be one, so the package loses its executable bit here and the
  # launcher gives it back when it starts.
  chmod -x "$OUT/$name.pkg"
  cat > "$OUT/$name" <<LAUNCHER
#!/bin/sh
# LLVMFuzzerTestOneInput for fuzzer detection.
this_dir=\$(dirname "\$0")
chmod +x "\$this_dir/$name.pkg"
exec "\$this_dir/$name.pkg" "\$@"
LAUNCHER
  chmod +x "$OUT/$name"
}
export -f build_one
export FUZZ_VENV WORK OUT

printf '%s\0' tests/fuzz/*_fuzzer.py | xargs -0 -n 1 -P "$FUZZ_JOBS" bash -eu -c 'build_one "$0"'

for dir in tests/fuzz/corpus/*/; do
  (cd "$dir" && zip -j -q "$OUT/$(basename "$dir")_fuzzer_seed_corpus.zip" ./*)
done
cp tests/fuzz/dict/*.dict "$OUT/"

test -n "$(find "$OUT" -maxdepth 1 -name '*_fuzzer' -perm -u+x)" || {
  echo "build.sh: no fuzz target was built" >&2
  exit 1
}
