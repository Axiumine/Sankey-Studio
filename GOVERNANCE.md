# Governance

Sankey Studio is a small project with two maintainers. This page says who decides what, who may
do what, and what happens if the lead maintainer is not available. The people are listed in
[MAINTAINERS.md](MAINTAINERS.md).

## Roles

* **Lead maintainer** (owner). Decides what goes into the project and what does not, reviews and
  merges changes, makes releases (see [docs/release.md](docs/release.md)), triages security reports
  ([SECURITY.md](SECURITY.md)) and answers issues.
* **Co-owner and successor.** Has the same access to the GitHub organization and repository as the lead
  maintainer (access to the PyPI project and to the approval of a release is added separately, see
  [docs/release.md](docs/release.md)). Keeps the project
  running if the lead maintainer cannot: answers security reports, merges and releases fixes. The
  co-owner has agreed to take the project over within a week of the lead maintainer becoming
  unavailable, and the project is GPL-3.0-only, so anyone may also fork it.
* **Contributors.** Anyone who opens an issue or sends a pull request
  ([CONTRIBUTING.md](CONTRIBUTING.md)). Contributors have no special access.
* **Reporters.** Anyone who reports a bug, a request or a vulnerability. Vulnerabilities go through
  GitHub private vulnerability reporting, not a public issue.

## Decisions

Decisions are made in the open, in issues and pull requests. The lead maintainer decides, and
the co-owner is consulted on anything that affects access, releases or security. Choices that shape the design are
written down as decision records in [docs/decisions.md](docs/decisions.md), and a record is changed
only by adding a new one that replaces it.

## Changes and review

Every change from a contributor arrives as a pull request. A maintainer reviews it against
[CONTRIBUTING.md](CONTRIBUTING.md): it follows the layering and the caps, has tests that keep
coverage at 100%, updates the docs and the changelog, and does not weaken a security invariant
([Security model](README.md#security-model)). The maintainers' own changes are checked by the git
hooks before they are pushed; a second reviewer is not required for them yet.

## Access

* Write access is given to a contributor only after several accepted changes and a look at their
  past work (the quality of the changes and how they treated others). Admin access and organization
  ownership stay with the maintainers.
* Everyone with write access must use two-factor authentication, which the `Axiumine` organization
  requires. New write access is given only to accounts that use a TOTP app, a passkey or a security
  key, not SMS.
* Access is removed on request, when someone is inactive for a long time, and at once if an account
  may be compromised.

## Conduct

Everyone in the project's spaces follows the [Code of Conduct](CODE_OF_CONDUCT.md). The maintainers are
the community leaders who enforce it.
