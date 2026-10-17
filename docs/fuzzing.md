# Fuzzing

This page says what is fuzzed, how, and how to reproduce a finding. Related:
[quality.md](quality.md) (the other checks), [dependencies.md](dependencies.md) (the pins),
[decisions.md](decisions.md#adr-47-fuzzing-runs-in-clusterfuzzlite-from-testsfuzz) (the reasons).

## What is fuzzed

The code that reads text an outsider controls. Each target is `tests/fuzz/<name>_fuzzer.py` (the
Atheris entry point) over a function in `tests/fuzz/text_targets.py` or `guard_targets.py`.

| Target | Code | A finding is |
|---|---|---|
| `text_source` | format sniffing, the csv, tsv, SankeyMATIC and JSON parsers | an exception other than `SourceError`, a hang, or a link that breaks the `DataSource` promises (finite value above 0, stripped non-empty names, normalised category) |
| `json_stream` | the streaming JSON reader, run with 1 to 64 character chunks | a result that depends on the chunk size |
| `rewrite` | the text rewriter behind the source write-back | an exception other than `SourceError` |
| `mongo_guard` | `check_filter` and `check_pipeline` | an accepted document that holds a forbidden operator or a stage outside the allow-list |
| `mongo_uri` | `check_mongo_uri`, `mask_uri` | an accepted URI whose options the driver reads but the guard forbids, or a masked URI that shows the password |
| `names` | database, collection, upload file and category validators | an accepted name that breaks a rule of its validator |
| `numfmt` | `format_value` | an exception, or an output over 1000 characters |

Expected errors (`SourceError` and its subclasses, `UnsafeSourceError`, `ValueError` from a
validator) are the code's answer to bad input and are not findings.

## How it runs

* `tests/fuzz/test_targets.py` runs in the normal unit tests (`make test`, `make cov`): every seed,
  400 mutated seeds and 400 random inputs per target, and a check that every target has its entry
  point. No fuzzing engine is needed for it.
* `.github/workflows/cflite_pr.yml` fuzzes a pull request that touches `src/`, `tests/fuzz/` or
  the build for 7 minutes (ClusterFuzzLite, `code-change`). `cflite_batch.yml` fuzzes `main` for an
  hour every night (`batch`) and then prunes the corpus. The corpus is kept as a workflow artifact.
* The image `.clusterfuzzlite/Dockerfile` installs Python 3.14 with uv, because the base image's
  Python 3.11 cannot parse the project. `build.sh` turns each entry point into a PyInstaller
  one-file binary, so the runner image needs no Python of its own.

## Reproduce a finding

Download the `crash-...` file from the failed job's artifacts, then from a checkout:

```
uv run --with atheris==3.1.0 python -m tests.fuzz.text_source_fuzzer path/to/crash-file
```

(`--with` adds atheris to a throw-away environment only; the project does not depend on it.)
To fuzz locally, give a corpus directory and a time: `... -max_total_time=60 tests/fuzz/corpus/<name>`.

## Seeds and options

Seeds are plain text. `text_source`, `json_stream` and `rewrite` read their options from the LAST
bytes of the input, each XOR 0x0a, so a seed that ends with newlines means "all defaults" (see
`tests/fuzz/inputs.py`). Add a seed by adding a file under `tests/fuzz/corpus/<name>/`.

## Limits

Nothing here proves the absence of bugs. The `coverage` sanitizer of ClusterFuzzLite is not
supported. The targets are pure Python, so no sanitizer runtime is preloaded and `address` is only
the name of the run.
