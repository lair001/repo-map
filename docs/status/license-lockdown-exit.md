# License Lockdown Exit

Date: 2026-06-29

## Scope

This final license lockdown micro-patch is documentation and contribution
governance only.

This phase does not start Phase C2, change storage code, change CLI behavior,
change migrations, or change source code.

## Changes

- `CLA.md` fixes downstream-recipient ambiguity in the patent grant.
- The patent grant now gives sublicensing and relicensing authority to Samuel
  Leighton Lair, as RepoMap project steward, rather than implying downstream
  recipients receive independent rights to sublicense or commercially relicense
  contributor patent rights.
- Downstream recipients receive patent rights only under the RepoMap license
  they receive, such as AGPL-3.0-or-later or a separate commercial license
  granted by Samuel Leighton Lair or an authorized successor.

## Phase Boundary

Phase C2 has not started.

No storage, CLI, migration, or source-code changes were made.

## Verification

The Python test suite was intentionally not run because this is a docs-only
governance change.

Verification for this patch:

- `git diff --check`
