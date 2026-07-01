---
name: repomap-phase-hygiene
description: Use when planning, documenting, verifying, committing, amending, or reviewing RepoMap phases, ADRs, status exits, docs-only updates, source slices, test harness changes, test report work, smoke tests, or extended-phase exit audits.
---

# RepoMap Phase Hygiene

## Overview

RepoMap history is part of the project audit trail. Every phase commit should
name the phase, state scope and boundaries, and record verification in the
commit body.

## Commit Message Contract

Use this shape for RepoMap phase commits:

```text
PHASE_ID: short imperative summary

Scope:
- what changed
- important boundaries and non-goals

Verification:
- unit: <command and result, or "not run; docs-only">
- int: <command and result, or "not run; docs-only">
- all: <command and result, or "not run; docs-only">
- compileall: <command and result, or "not run; docs-only">
- git diff --check: <result>
- git diff --cached --check: <result>
```

Do not use vague subjects such as "Add docs" or "Update skills". The subject
must preserve the current phase id, such as `API2`, `WARC0`, `RPT1`, or
`Phase D6`.

## Phase Families

Docs-only phase updates include ADRs, status audits, README examples, and skill
docs. Run docs-only verification, and record unit/int/all/compileall as not run
because the change is docs-only. Skill-doc commits should follow the RSS2
public skill pattern; ADR commits should follow the WARC0 ADR pattern.

Source-code phases add or change executable behavior. Use TDD, keep the slice
bounded, add or update exit status, and run unit, int, all, compileall, diff,
and cached-diff checks. If integration tests need host IPC for disposable
Postgres, record both the sandbox limitation and the host-permission rerun.

Test harness phases may change `tools/run_tests.py`, test support packages, or
temporary Postgres behavior. Keep operational cleanup conservative and document
what will not be touched, such as attached, other-user, live-cluster, semaphore,
message-queue, or ambiguous IPC resources.

Test report phases may use focused report-generator tests and targeted
compileall when the slice is isolated to report rendering. Promote to full
unit/int/all verification when runner behavior or broader RepoMap behavior
changes.

Smoke-test phases document a reproducible manual or MCP check. If docs-only,
run docs-only verification and record source tests as not run. Include exact
tool sequence, expected read-only boundary, and failure classification.

Extended-phase exit sub-phases close a larger phase after earlier implementation
slices. Confirm what is already available, what remains unchanged, and which
later phase has not started. These are often docs/status-only.

## ADR Template

RepoMap ADRs normally use:

- `# ADR NNNN: Title`
- `## Status`
- `## Date`
- `## Context`
- `## Decision`
- explicit `## Scope` or `## Scope and Non-Scope`
- policy/model sections for identity, storage, extraction, ingestion, security,
  privacy, readback, or CLI behavior as applicable
- raw observation, canonical namespace, and edge vocabulary sections when graph
  shape changes
- fixture and required-test sections for the next implementation phase
- rejected alternatives
- proposed phases or consequences

ADRs should define boundaries before code lands. Architecture-only ADR commits
must not imply implementation, migrations, MCP tools, provider integrations, or
public default changes unless the ADR explicitly accepts them.

## Pre-Commit Checklist

- Changed files match the intended phase family.
- Subject starts with the phase id.
- Scope records both what changed and what stayed out of scope.
- Verification lists unit, int, all, compileall, `git diff --check`, and
  `git diff --cached --check`.
- Docs-only commits explicitly say source-code tests were not run because the
  change is docs-only.
- The durable record is in the commit message, status doc, or ADR, not only in
  chat.
