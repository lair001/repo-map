# Phase T1 Temporary Postgres Teardown Hardening Exit

Status: Complete

Phase T1 hardened the integration-test temporary Postgres harness so failed
bootstrap and teardown paths are less likely to leave current-user System V
shared-memory segments that block later verification runs.

## Motivation

N1 and E2 verification were both blocked by orphaned current-user System V
shared-memory segments from failed temporary Postgres bootstrap/test clusters.
Those incidents were resolved manually with user-authorized, exact-id `ipcrm`
cleanup. T1 moves the safe subset of that cleanup into the test harness.

## Scope

T1 stayed limited to test harness and integration-test infrastructure.

It did not change RepoMap graph behavior, public CLI behavior, MCP behavior,
canonical key grammar, edge vocabulary, extractors, E3 canonical-default
migration behavior, or host-mutators-summary canonical semantics.

## Teardown Guarantees

The temporary Postgres context manager now:

- captures a current-user shared-memory baseline before `initdb` starts;
- tears down when the test body exits normally;
- tears down when the test body raises;
- tears down when cluster bootstrap raises before the context manager returns;
- stops only the specific temporary data directory it created;
- attempts `pg_ctl -m fast -w stop` first;
- escalates to `pg_ctl -m immediate -w stop` only for that same data directory
  if the fast stop fails and the cluster still appears live;
- uses `pg_ctl status -D <temp-data-dir>` as the live-cluster guard; and
- removes the temporary directory only after the cluster no longer appears live.

## IPC Cleanup Safety

The harness uses `ipcs -m -a` and `ipcrm -m` only when those tools are
available. Cleanup is best effort and diagnostic-only if the tools are missing
or fail.

The harness removes only shared-memory segments that are:

- present after teardown;
- absent from the pre-bootstrap baseline;
- owned by the current user;
- created by the current user when creator data is available;
- unattached with `NATTCH == 0`;
- shaped like the leaked temporary Postgres bootstrap segments seen in N1/E2;
  and
- safe to remove because the specific test cluster no longer appears live.

The harness refuses to remove:

- segments that existed before the test started;
- segments owned by another user;
- segments created by another user;
- attached segments;
- semaphores;
- message queues;
- files outside the temporary test directory;
- any segment when the specific test cluster still appears live; and
- ambiguous new current-user segments that do not match the conservative
  Postgres bootstrap segment shape.

When the harness removes segments, it reports the removed SHM ids to stderr.
When it sees ambiguous current-user segments, it reports them and leaves them
alone.

## Manual Diagnosis

If IPC exhaustion still occurs, diagnose manually before removing anything:

```sh
id -un
ps aux | grep -E '[p]ostgres|[p]ostmaster|[i]nitdb'
ipcs -m
ipcs -m -a
```

Manual `ipcrm -m <shmid>` remains incident-specific and user-authorized only.
Never use `sudo`; never remove segments owned by another user; never remove
attached segments; never remove semaphores or message queues.

## Tests

Added unit coverage for:

- baseline segments never selected;
- other-user segments never selected;
- attached segments never selected;
- new current-user unattached Postgres-shaped segments selected;
- missing `ipcs` path safe;
- live-process case skipped;
- `ipcrm` receives only selected SHM ids; and
- ambiguous new current-user segments reported and skipped.

Added integration-harness coverage proving `temporary_postgres()` attempts
cluster stop and IPC cleanup after a bootstrap failure.

## Verification

Final required verification for T1:

- passed `python3 tools/run_tests.py --suite unit`
- passed `python3 tools/run_tests.py --suite int`
- passed `python3 tools/run_tests.py --suite all`
- passed `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
- passed `git diff --check`
- passed `git diff --cached --check`

## Confirmation

- No RepoMap graph behavior changed.
- No public CLI behavior changed.
- No MCP behavior changed.
- No canonical key grammar changed.
- No edge vocabulary changed.
- No extractor behavior changed.
- Phase E3 has not started.
- Host-mutators-summary canonical semantics remain deferred.
