# License Hardening Exit

Date: 2026-06-29

## Scope

This licensing hardening phase tightens RepoMap contribution-governance
documentation after the AGPL-3.0-or-later plus commercial licensing cutover.

This phase does not start Phase C2, change storage code, change CLI behavior,
or change migrations.

## Changes

- `CLA.md` now identifies the grantee as Samuel Leighton Lair, as RepoMap
  project steward.
- `CLA.md` now includes an explicit inbound patent grant covering patent
  claims necessarily infringed by the contribution alone or by combination of
  the contribution with RepoMap.
- `CLA.md` narrows future relicensing language to future RepoMap project
  licenses adopted by the project steward, including open-source,
  source-available, and commercial licenses.
- `CLA.md` and `CONTRIBUTING.md` now require the explicit pull request
  acknowledgment: `I agree to the RepoMap contribution terms in CLA.md.`
- `CONTRIBUTING.md` now says a `Signed-off-by` line does not replace the
  explicit pull request acknowledgment.
- `.github/pull_request_template.md` adds required contribution terms and
  authority checklist items.
- `NOTICE` records the project steward, copyright notice, future
  AGPL-3.0-or-later licensing, commercial-license availability, and the final
  Apache-2.0 baseline.

## Phase Boundary

Phase C2 has not started.

`repomap-kg storage load-files` remains unchanged and does not dual-write
canonical rows.

## Verification

The licensing hardening phase completed these commands successfully:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite all`
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`
- `git diff --check`

`python3 tools/run_tests.py --suite unit` passed with 194 tests and 89.2
percent aggregate coverage.

`python3 tools/run_tests.py --suite all` passed with 246 tests and 91.6
percent aggregate coverage.
