# Releasing

A release is a version tag (`vX.Y.Z`) on `main`. Pushing the tag starts the only GitHub workflow of
the project, `.github/workflows/release.yml`, which builds the package and uploads it to TestPyPI
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
2. In the repository settings, Environments, create `testpypi` and `pypi`. On `pypi` set a
   required reviewer (yourself): the workflow then stops after the TestPyPI upload and waits for an
   approval, which is the moment to install the TestPyPI files and try them.
3. Optional: turn on branch and tag protection for `v*` so only the owner can create release tags.

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
7. Create the GitHub release for the tag (notes from the CHANGELOG section).

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
