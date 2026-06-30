# Phase E2 Canonical Host-Mutator Readback Exit

Status: Complete

Phase E2 continued ADR 0009 Phase E by adding opt-in canonical readback support
for host-mutator-oriented public storage readback where the canonical equivalent
is straightforward.

## Scope

E2 stayed limited to canonical-aware host-mutator public readback. It did not
change canonical key grammar, add edge kinds, add extractors, add write-capable
MCP tools, start Bash/Bats/AWK extraction, remove legacy commands, remove or
rename legacy stable-key fields, change default legacy output, or make
canonical mode the default.

## Commands Evaluated

- `storage host-mutators`
- `storage host-mutators-summary`

## Commands Updated

`storage host-mutators` now accepts `--canonical`.

In canonical mode, it reads canonical `mutates_host` edges:

- source identity is `file:*` through `source_key`;
- relationship identity is `edge_kind = "mutates_host"`;
- target identity is `host.category:*` through `target_key`;
- `--category` maps to the corresponding `host.category:*` target key;
- `--tool` filters canonical edge metadata, not graph identity;
- JSON output uses the canonical edge record shape with `source_key`,
  `edge_kind`, `target_key`, `graph_key_version`,
  `identity_metadata_hash`, `metadata`, `confidence`, and `conflict`; and
- table output uses the existing canonical edge table formatter.

Legacy mode remains the default when `--canonical` is absent.

## Commands Deferred

`storage host-mutators-summary` was evaluated and intentionally deferred.

Canonical host mutation edges collapse multiple raw observations into one
durable edge. The legacy summary command reports observation-level counts and
privileged counts grouped by category and tool. A canonical equivalent should
define whether those counts come from canonical edge metadata, evidence links,
or a dedicated evidence aggregation query before adding public `--canonical`
summary behavior.

## Compatibility Behavior

- Existing `storage host-mutators` behavior is unchanged without
  `--canonical`.
- Existing `storage host-mutators-summary` behavior is unchanged.
- `storage host-mutators --canonical` rejects invalid canonical source and
  target keys before querying storage.
- Canonical-only filters such as `--source-key`, `--target-key`, and
  `--graph-key-version` are rejected in legacy `storage host-mutators` mode.
- Legacy stable keys are not reinterpreted as canonical keys.
- Canonical output does not expose database integer ids as public identity.

## Canonical Output Behavior

Canonical host-mutator readback returns canonical edge records for:

`file:<path> --mutates_host--> host.category:<category>`

Command/tool details, argv examples, privileged observations, classifier
reasons, and raw command text remain metadata or evidence. Line numbers and raw
observation source ids remain evidence and can be inspected through
`storage explain-canonical-edge`.

## Verification

Development verification:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`

During integration verification, temporary Postgres bootstrap was initially
blocked by orphaned current-user System V shared-memory segments from failed
temporary Postgres test clusters. The user explicitly authorized cleanup for
this E2 incident. Pre-cleanup checks showed user `slair`, no live `postgres`,
`postmaster`, or `initdb` processes, and only the whitelisted current-user
segments with `NATTCH 0`. After removing those exact unattached segments,
`ipcs -m` showed no remaining shared-memory segments, and the integration suite
passed.

Final required verification for E2:

- passed `python3 tools/run_tests.py --suite unit`
- passed `python3 tools/run_tests.py --suite int`
- passed `python3 tools/run_tests.py --suite all`
- passed `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
- passed `git diff --check`
- passed `git diff --cached --check`

## Confirmation

- No new extractors were added.
- No canonical key grammar changed.
- No edge vocabulary changed.
- No write-capable MCP tools were added.
- No default public output changed.
- Phase E3 canonical-default migration has not started.

## Recommendation

E2 is complete. The next Phase E slice should either define canonical summary
semantics for host-mutator summaries or choose a narrow E3 canonical-default
pilot only after tests, docs, examples, and explicit legacy compatibility flags
are in place.
