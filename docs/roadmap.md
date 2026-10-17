# Roadmap

Sankey Studio is complete. The maintainers plan no new features: they keep the software working and
safe. This page says what the project intends to do, and not to do, over the next year (to October
2027). It states intentions, not promises or dates. It is looked at again at every release.

## What the maintainers intend to do

* **Fix bugs.** A bug reported in the [issue tracker](https://github.com/Axiumine/Sankey-Studio/issues)
  is fixed and shipped in a patch release ([CONTRIBUTING.md](../CONTRIBUTING.md)).
* **Fix security problems.** A vulnerability is handled as [SECURITY.md](../SECURITY.md) describes:
  private reporting, the response targets, a fix on `main` and a patch release. While the project
  is 0.x only the latest release is supported
  ([Supported versions](../SECURITY.md#supported-versions)).
* **Keep the dependencies patched.** A dependency is bumped when it has a known vulnerability or when
  a new release breaks the application, as [dependencies.md](dependencies.md) describes. A release
  of a dependency that breaks Sankey Studio is treated as a bug.
* **Review and merge good pull requests** (see below), and keep the documentation, the changelog and
  the security notes in step with the code.

## What the project does not intend to do

* **Add features of its own.** The set of features in the [README](../README.md#features) is the set
  the maintainers wanted.
* **Support SQL databases.** Sources and storage are text, files and MongoDB. SQL database support is
  not planned, and a pull request that adds it will not be accepted.
* **Add a login.** "No login gate" is one of the product requirements that no decision may trade away
  ([decisions.md](decisions.md)). The server is loopback-only by default, and
  [Security model](../README.md#security-model) says what protects it instead.

## Pull requests

Feature pull requests from other people are welcome, except for SQL database support. Please open an
issue first, so the idea can be discussed before the work is done. A change must follow the rules in
[CONTRIBUTING.md](../CONTRIBUTING.md): the layering and the code caps, tests that keep line and branch
coverage at 100%, the documentation and the changelog, and no weakening of a security invariant
([Security model](../README.md#security-model)). The maintainers decide what is merged, and a
well-made change can still be declined if it does not fit the software as it is.

## How this page changes

The page is reviewed when a release is made. A change to what the project intends or no longer
intends goes in [CHANGELOG.md](../CHANGELOG.md) and in this page. The architecture decisions behind the
software stay in [decisions.md](decisions.md).
