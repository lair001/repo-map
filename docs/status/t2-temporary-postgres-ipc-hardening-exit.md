# Phase T2 Temporary Postgres IPC Hardening Exit

Status: Complete

## Scope

T2 stayed limited to the temporary Postgres integration-test harness and its
unit/integration coverage. It did not change RepoMap graph behavior,
extractors, canonicalization semantics, storage schema, public CLI behavior,
MCP behavior, graph key namespaces, edge kinds, Phase F behavior, Shell/Bats/AWK
work, HTML/XML scraper work, generic XML semantics, or Java/Spring/Maven work.

## Recurring Incident Pattern

After T1, CFG1 and XML1 verification still hit temporary Postgres IPC
incidents. The recurring pattern was:

- an integration suite was accidentally invoked in the Codex sandbox;
- sandboxed `ipcs`/System V IPC access was unavailable or denied;
- sandboxed `initdb` failed with IPC errors such as `Operation not permitted`;
- failed bootstrap attempts left current-user, unattached, size-56 System V
  shared-memory segments; and
- later host-access integration runs failed with IPC exhaustion until manual,
  user-authorized cleanup removed the exact leaked segment ids.

## What T1 Already Protected

T1 added conservative in-process cleanup for the shared test harness:

- capture a current-user shared-memory baseline before `initdb`;
- stop only the temporary cluster started by the harness;
- cleanup only post-baseline, current-user, creator-compatible, unattached,
  Postgres-shaped shared-memory segments;
- skip baseline segments, other-user segments, attached segments, semaphores,
  message queues, and ambiguous segments; and
- report cleanup decisions to diagnostics.

That protection works when the Python harness can inspect IPC state and owns the
temporary cluster lifecycle.

## Gap Found

T2 found two related gaps:

1. The large storage integration test file still carried a duplicate local
   `PostgresCluster`, `temporary_postgres`, and Postgres binary discovery
   harness. It imported only `PostgresIpcGuard` from the shared support module.
   This meant T1's hardened support harness was not the single source of truth
   for the main storage integration suite.

2. When `ipcs -m -a` was unavailable or denied before bootstrap, the harness
   could not capture a safe pre-`initdb` baseline. T1 treated missing `ipcs` as
   cleanup-unavailable, but the duplicated integration harness could still
   proceed to `initdb`. In the Codex sandbox, that is exactly the path that can
   create leaked bootstrap shared-memory segments that the same sandboxed
   process cannot safely identify and remove.

## T2 Changes

T2 consolidated the integration harness:

- moved `PostgresCluster`, `temporary_postgres`, `require_postgres_binaries`,
  Postgres binary/share discovery, and the checked subprocess helper into
  `src/test/support/python/repomap_test_support/postgres_harness.py`;
- updated `test_storage.int.test.py` to import `temporary_postgres` and
  `require_postgres_binaries` from the shared support module instead of carrying
  duplicate definitions; and
- moved the bootstrap-failure teardown coverage into the Postgres harness unit
  tests.

T2 also added an explicit pre-`initdb` guard:

- `PostgresIpcGuard.capture_baseline()` now returns `True` only when
  `ipcs -m -a` successfully captures a baseline;
- if baseline capture is unavailable, the temporary Postgres context manager
  raises `SkipTest` before creating a temp data directory or running `initdb`;
- diagnostics say that `ipcs` is unavailable before `initdb` and that safe IPC
  cleanup cannot be guaranteed; and
- cleanup with a missing baseline now reports that cleanup was skipped because
  the baseline was unavailable.

This does not remove pre-existing or ambiguous IPC resources. It prevents the
known sandbox-denied invocation from reaching `initdb` in the first place.

## Remaining Manual Cleanup Boundary

Manual `ipcrm` cleanup remains incident-specific and user-authorized only.
T2 did not add broad machine cleanup.

Manual cleanup still requires the established protocol:

```sh
id -un
ps aux | grep -E '[p]ostgres|[p]ostmaster|[i]nitdb'
ipcs -m
ipcs -m -a
```

Never use `sudo`; never remove semaphores; never remove message queues; never
remove files outside the temporary test directory; never remove other-user
segments; never remove attached segments; never remove baseline/pre-existing
segments; and stop on ambiguity.

## Tests Added Or Moved

T2 added or updated unit coverage for:

- baseline capture reporting unavailable `ipcs` before `initdb`;
- cleanup diagnostics when no baseline exists;
- `temporary_postgres` skipping before cluster construction when no IPC
  baseline can be captured; and
- cleanup running after a `PostgresCluster.start()` bootstrap failure when a
  baseline exists.

The storage integration suite now uses the shared support harness directly.

## Verification Notes

Before the final integration and all-suite verification, host IPC state was
checked:

- `ipcs -m` showed no shared-memory segments.
- no live `postgres`, `postmaster`, `initdb`, or test-runner processes were
  present beyond the inspection command itself.

The final integration and all-suite verification ran with host IPC access.
After verification, `ipcs -m` again showed no shared-memory segments.

## Verification

Verification performed during T2:

```sh
PYTHONPATH=src/main/python:src/test/support/python python3 src/test/unit/python/repomap_kg/test_postgres_harness.unit.test.py
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m py_compile src/test/support/python/repomap_test_support/postgres_harness.py src/test/unit/python/repomap_kg/test_postgres_harness.unit.test.py src/test/int/python/repomap_kg/test_storage.int.test.py
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

## Exit

T2 is complete. The harness now has one shared implementation for storage
integration tests and refuses to run `initdb` when it cannot capture the IPC
baseline needed for safe post-failure cleanup.
