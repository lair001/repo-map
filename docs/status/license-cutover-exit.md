# License Cutover Exit

Date: 2026-06-29

## Scope

This licensing cutover phase switches future RepoMap releases from Apache-2.0
to AGPL-3.0-or-later plus commercial licensing.

This phase does not start Phase C2, change storage code, change CLI behavior,
or change migrations.

## Baseline

- Old license: Apache-2.0.
- New license: AGPL-3.0-or-later plus commercial licensing.
- Apache final tag: `apache-2.0-final`.
- Apache final commit:
  `22c34fb83869bf24adbb413c4389b9b959b08982`.

Code released before the `apache-2.0-final` tag remains available under the
Apache License, Version 2.0. Prior Apache-2.0 grants are not revoked by the
license change for future RepoMap releases.

## Files Changed

- `LICENSE`: replaced Apache License 2.0 with GNU Affero General Public
  License v3.0 text.
- `pyproject.toml`: changed project license metadata to
  `AGPL-3.0-or-later`.
- `README.md`: changed project identity license and added the license cutover,
  commercial licensing, and prior Apache baseline explanation.
- `COMMERCIAL-LICENSE.md`: added commercial licensing guidance and contact.
- `CONTRIBUTING.md`: added contribution policy and required sign-off or CLA
  acknowledgment.
- `CLA.md`: added contribution license terms.
- `docs/adr/0006-project-licensing-and-commercialization-strategy.md`: marked
  the licensing strategy accepted and recorded the Apache baseline tag.
- `docs/status/license-cutover-exit.md`: records this exit audit.

## Contribution Terms

Future contributions require the contribution terms in `CLA.md`.
Contributors retain copyright, but they grant the RepoMap maintainer broad
rights to use, modify, distribute, sublicense, and relicense contributions as
part of RepoMap, including under AGPL-3.0-or-later and commercial licenses.

Contributions must include either a sign-off line or an explicit pull-request
acknowledgment of `CLA.md`.

## Phase Boundary

Phase C2 has not started. This cutover changed licensing documents and package
metadata only.

`repomap-kg storage load-files` remains unchanged and does not dual-write
canonical rows.

## Verification

The licensing cutover phase completed these commands successfully:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite all`
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`
- `git diff --check`

The first sandboxed `all` run failed before test logic because temporary
Postgres `initdb` could not allocate shared memory. A host-permission rerun
initially found stale, unattached, user-owned shared-memory segments from the
failed bootstrap attempts. After removing only those unattached segments,
`python3 tools/run_tests.py --suite all` passed with 246 tests and 91.6 percent
aggregate coverage.
