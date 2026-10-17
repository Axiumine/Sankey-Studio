# Security policy

Sankey Studio is a local web app that can read from and (when you opt in) write to MongoDB, so
security reports are taken seriously. This page says how to report a vulnerability and what to
expect.

## Supported versions

| Version | Supported |
|---|---|
| Latest release (0.1.x) | yes |
| `main` (the next release) | yes |
| Older releases | no |

While the project is 0.x only the latest release is supported: a fix lands on `main` and ships as a new
patch release. When a newer minor release is published, the previous one stops receiving security
fixes; that is announced in the release notes and in [CHANGELOG.md](CHANGELOG.md).

## Reporting a vulnerability

Please do not open a public issue, pull request or discussion for a vulnerability.

Report it privately with GitHub's private vulnerability reporting:

1. Open <https://github.com/Axiumine/Sankey-Studio/security/advisories/new>
   (or the "Security" tab of the repository, then "Report a vulnerability").
2. Describe the problem. Helpful details:
   * the commit or version, and how you started the server (`--allow-remote`,
     `--allow-remote-writes`, `--allow-source-writes`, host, MongoDB or file sources);
   * the steps or a small proof of concept (a request, a CSV, a connection string with the
     credentials removed);
   * what an attacker gains and what they need first (network position, a browser tab of the victim,
     a crafted data file, a MongoDB user).

Never include real credentials, real connection strings or other people's data in a report.

## What to expect

* An acknowledgement within 7 days.
* A first assessment (accepted, needs more information, or not a vulnerability, with the reason)
  within 14 days.
* A fix for a confirmed vulnerability of medium or higher severity within 60 days of the report;
  a critical one as soon as possible. This is a small volunteer project, so the dates are targets for
  the maintainers, but a missed date will be explained in the advisory thread.
* Coordinated disclosure: the fix is published together with a GitHub security advisory (and a CVE
  when it applies), and a line in [CHANGELOG.md](CHANGELOG.md). Please keep the report private until
  then. If a report is declined, you may disclose it after telling us so.
* Credit in the advisory and the changelog, unless you ask to stay anonymous.

There is no bug bounty.

## Scope

In scope: the code in this repository, measured against the protections listed under
[Security model](README.md#security-model) and in
[docs/architecture.md](docs/architecture.md#security-design). Examples:

* a way around the loopback, host, Origin or CSRF checks, or the content-type and size caps;
* a path escape from the managed sources folder (traversal, symlinks, writing a file that is not an
  existing allowed one);
* MongoDB access that the guard should refuse (writes, code execution, the `admin`, `local`,
  `config` or `system.*` namespaces, other databases, a write without the saved agreement);
* a connection string, password or other secret in an API response, log, error message or export;
* script injection or formula injection through user text in a figure, an HTML export or a CSV cell;
* a denial of service that a small request causes (the export and upload caps are meant to stop it).

Out of scope:

* behaviour that is documented as a deliberate trade-off, for example no login on a loopback
  server, or that a saved write-back answer is consent and not authorisation (the MongoDB user's
  privileges are the real limit). A report that shows a way around the documented limits is in scope;
* running with `--allow-remote` and `--allow-remote-writes` on an untrusted network;
* weaknesses in a dependency that do not affect Sankey Studio (report them upstream), and
  vulnerabilities that need a machine or browser that is already compromised.

## How we look for vulnerabilities

The project has no hosted CI. The maintainer's git hooks run the checks before a commit or push:
strict typing, a test suite with 100% line and branch coverage and a mutation-score gate, and, before
`main` or a tag is pushed, Semgrep (with project rules against MongoDB writes, shell and dynamic
code, secrets in logs and unsafe frontend patterns), Trivy on the locked dependencies, and Qodana.
See [docs/quality.md](docs/quality.md), [CONTRIBUTING.md](CONTRIBUTING.md) and the
[assurance case](docs/assurance-case.md), which lists the threats, the controls and the known gaps.
