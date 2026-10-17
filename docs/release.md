# Releasing

A release is a version tag (`vX.Y.Z`) on `main`. Pushing the tag starts the release workflow,
`.github/workflows/release.yml`, which builds the package and uploads it to TestPyPI
and then to PyPI with trusted publishing (OIDC): there is no PyPI token in the repository or in the
GitHub settings ([ADR-39](decisions.md#adr-39-releases-are-published-to-pypi-from-a-tag)). The
workflow runs no tests: the git hooks ran them before the tag was pushed.

Package name: `sankey-studio` (<https://pypi.org/project/sankey-studio/>).

## One-time setup

1. On <https://pypi.org/manage/account/publishing/> add a **pending publisher**: project
   `sankey-studio`, owner `Axiumine`, repository `Sankey-Studio`, workflow `release.yml`,
   environment `pypi`. Do the same on <https://test.pypi.org/manage/account/publishing/> with
   environment `testpypi`. A pending publisher creates the project on the first upload and
   becomes a normal trusted publisher afterwards.
2. In the repository settings, Environments, create `testpypi` and `pypi`. Both deploy only from
   tags that match `v*` (deployment tag rule). On `pypi` set a required reviewer (the lead maintainer;
   add the co-owner as a second reviewer once they have a PyPI account): the workflow then stops after
   the TestPyPI upload and waits for an approval, which is the moment to install the TestPyPI files and
   try them.
3. After the first upload, add the co-owner as an Owner of the PyPI project (project page,
   Collaborators).
4. Optional: turn on tag protection for `v*` so only the maintainers can create release tags.

## Making a release

1. Pick the version (SemVer; `0.x` while the API and the stored formats may still change). Set it in
   `pyproject.toml` and move the `[Unreleased]` entries of [CHANGELOG.md](../CHANGELOG.md) under
   `## [X.Y.Z] - YYYY-MM-DD`, with a fresh empty `[Unreleased]` above it.
2. Commit (`chore(release): X.Y.Z`) and push `main`. The push gate runs the full release tier
   (`make gate-release` runs it by hand, it needs your replica set).
3. Tag the same commit and push the tag. A signed tag is preferred:
   `git tag -s vX.Y.Z -m "Sankey Studio X.Y.Z"` then `git push origin vX.Y.Z`.
4. Watch the run in the Actions tab. `build` checks that the tag equals the version in
   `pyproject.toml`, builds the sdist and the wheel, runs `twine check --strict` and starts the
   installed wheel; `testpypi` uploads; `pypi` waits for your approval, then uploads.
5. Between `testpypi` and `pypi`, try the TestPyPI files in a clean environment:

   ```bash
   uv tool run --default-index https://pypi.org/simple --index https://test.pypi.org/simple \
     --index-strategy unsafe-best-match sankey-studio==X.Y.Z serve --port 8765
   ```

6. After the approval, check <https://pypi.org/project/sankey-studio/>: the description renders, the
   links work, and `uv tool install sankey-studio` installs the new version.
7. Create the GitHub release for the tag (notes from the CHANGELOG section) and attach the release
   assets ([Release assets](#release-assets)).

## Verifying a release

The files on PyPI carry a signed PEP 740 attestation (Sigstore) made by the release workflow, which
ties each file to this repository, `release.yml` and the `pypi` environment. Anyone can check that
the file they have was built there and was not changed:

```bash
uvx pypi-attestations verify pypi --repository https://github.com/Axiumine/Sankey-Studio \
  pypi:sankey_studio-0.1.0-py3-none-any.whl
```

`OK: <file>` means the attestation is valid for that exact file and was made by that repository. The
command fails when the file was altered (`subject does not match distribution digest`) or when
`--repository` names another repository. Use `pypi:sankey_studio-X.Y.Z.tar.gz` for the source
distribution. The release tag is signed too (`git tag -v vX.Y.Z`). Do not pass `--staging` for
files from TestPyPI: they are signed with the normal Sigstore root, so verify them with
`--provenance-file` and no `--staging`.

## Rebuilding a release

The files on PyPI can be rebuilt from the tag and compared byte for byte. This was checked for 0.1.0 on
2026-10-17 on another machine than the one that built the release (uv 0.12.17, hatchling 1.32.4):

```bash
mkdir /tmp/rebuild && git archive vX.Y.Z | tar -x -C /tmp/rebuild
cd /tmp/rebuild && env -u SOURCE_DATE_EPOCH uv build --out-dir ../rebuild-out
sha256sum ../rebuild-out/*   # compare with the digests on https://pypi.org/pypi/sankey-studio/X.Y.Z/json
```

The wheel and the sdist were identical to the PyPI files, and two builds in a row were identical to each
other. Leave `SOURCE_DATE_EPOCH` unset, as the release workflow does: another value changes the
timestamps in the archives but not their contents. The build tool `hatchling>=1.27` is resolved when the
package is built and is not locked, so a future hatchling that writes the archives differently can change
the hashes without any change to the source; if the hashes differ, compare the member lists and the
contents of the two archives first.

## Release assets

The release page carries the files that are on PyPI, so they can be fetched and checked without PyPI.
Use PyPI's files, not a local build: a rebuild is not claimed to be byte-identical.

1. Download the wheel and the sdist from the PyPI JSON (`https://pypi.org/pypi/sankey-studio/X.Y.Z/json`,
   the `urls` list) and compare each sha256 with the `digests` entry there.
2. Download the provenance of each file from
   `https://pypi.org/integrity/sankey-studio/X.Y.Z/<file>/provenance` (header
   `Accept: application/vnd.pypi.integrity.v1+json`) and turn it into a Sigstore bundle with
   `pypi_attestations` (run it with `uv run --no-project --with pypi-attestations python -I script.py`):

   ```python
   from pypi_attestations import Provenance
   prov = Provenance.model_validate_json(open(f"{name}.provenance.json", "rb").read())
   bundle = prov.attestation_bundles[0].attestations[0].to_bundle()
   open(f"{name}.sigstore.json", "w").write(bundle.to_json())
   ```

3. Verify each bundle before uploading: `Attestation.from_bundle(Bundle.from_json(...)).verify(
   GitHubPublisher(repository="Axiumine/Sankey-Studio", workflow="release.yml", environment="pypi"),
   Distribution.from_file(path))` must pass, and the same call with another repository must fail.
4. `gh release upload vX.Y.Z <wheel> <sdist> <wheel>.sigstore.json <sdist>.sigstore.json`.

## Things that cannot be undone

* A version number on PyPI (and on TestPyPI) is used for good: a file with the same name can never be
  uploaded again, even after a delete. A bad release is **yanked** on the project page and fixed by
  the next patch version.
* The upload carries the metadata of `pyproject.toml`, including the author's e-mail address, and
  the README as the project page.
* The sdist holds `src/`, the Markdown docs, `README.md`, `CHANGELOG.md`, `SECURITY.md`,
  `CONTRIBUTING.md` and `LICENSE` (`[tool.hatch.build.targets.sdist]`); tests, the agent skills and the
  scanner config stay out.

## Checking a build without uploading

```bash
uv build --out-dir /tmp/sankey-dist
uvx twine check --strict /tmp/sankey-dist/*
uv tool run --from /tmp/sankey-dist/sankey_studio-X.Y.Z-py3-none-any.whl --python 3.14 sankey-studio --help
```
