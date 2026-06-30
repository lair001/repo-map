# CFG1 JSON Configuration Extractor Exit

Date: 2026-06-30

## Scope

CFG1 implemented the JSON-family subset of ADR 0010's structured
configuration graph model.

The phase stayed limited to JSON, JSONL, and conservative JSONC extraction,
canonicalization, fixtures, and canonical storage/readback coverage. It did
not implement TOML, start Shell/Bats/AWK extraction, resume Phase F, change MCP
behavior, add MCP write/load/discovery tools, execute commands found in
configuration files, fetch URLs, expand shell variables, validate external
schemas, store secret values, or add graph vocabulary beyond ADR 0010's
`config.document`, `config.path`, and `references` model.

## Implemented Formats

CFG1 added static extraction for:

- `.json` files parsed with Python stdlib `json`;
- `.jsonl` files parsed line by line, with malformed lines retained as parse
  error observations while valid lines continue to produce records; and
- `.jsonc` files parsed through a conservative stdlib normalizer that removes
  comments outside strings and trailing commas before JSON parsing.

TOML is deliberately deferred to CFG2.

## Raw Observations

CFG1 emits:

- `config.document` for each parsed JSON-family document;
- `config.path` for stable object-key paths and safe structural summaries;
- `config.reference` for conservative file, tool, env, and URL references;
- `config.jsonl_record` for parseable JSONL records; and
- `config.parse_error` for malformed JSON, malformed JSONL lines, or
  unsupported/malformed JSONC.

JSONL record line numbers and record indexes remain evidence, not durable
canonical identity. `config.parse_error` and `config.jsonl_record` are retained
as raw/evidence-oriented observations in CFG1 and do not fabricate canonical
graph facts.

## Canonical Mapping

CFG1 extended graph key version 1 with:

- `config.document:<encoded-file-key>`
- `config.path:<encoded-file-key>:<encoded-config-pointer>`

It did not add `config.record:*`.

Canonicalization now creates:

- `file:* --defines--> config.document:*`
- `file:* --defines--> config.path:*`
- `config.path:* --references--> <target>` when a reference target is
  conservative and explicit.

CFG1 added `references` to the registered canonical edge vocabulary and the
canonical storage DDL edge-kind constraint. The edge means a structured config
value syntactically references another durable target; it does not imply
runtime execution, ownership, endorsement, or dependency.

## Pointer And Array Policy

Config paths use JSON Pointer style identity:

- pointers start with `/`;
- object-key spelling and case are preserved;
- `~` is escaped as `~0`;
- `/` inside a segment is escaped as `~1`;
- the empty pointer maps to `config.document`, not `config.path`.

Ordinary array indexes are not canonical `config.path` identity in CFG1.
Arrays are represented through summary metadata such as value type, length, and
`array_policy=summary-only`. Array element identity remains deferred until a
future phase defines a stable member-key policy.

## Redaction

Secret-prone keys are redacted before raw observations, canonical metadata,
edge metadata, fixtures, and readback output can expose values.

The redaction markers come from ADR 0010 and include `token`, `secret`,
`password`, `passwd`, `api_key`, `apikey`, `credential`, `private_key`,
`access_key`, `refresh_token`, `bearer`, and `auth`.

Redacted metadata preserves safe structural facts such as value type, key path,
`redacted=true`, and redaction reason. Secret values are not used in canonical
keys and are not emitted into golden fixtures or serialized readback output.

## Reference Behavior

CFG1 reference detection is conservative:

- relative file paths that normalize inside the repository target `file:*`;
- repo-escaping file paths target `unknown:file:repo-escaping-config-reference`;
- absolute file paths target `external:file:absolute-config-reference`;
- variable/template/glob/home-style file paths target explicit `dynamic:*`
  placeholders;
- `http`, `https`, and `mailto` strings target `external.url:*` without
  fetching;
- simple command fields target `tool:*`;
- shell fragments and compound commands target
  `dynamic:tool:config-command-fragment`;
- unknown static command-like values target
  `unknown:tool:unknown-config-command`;
- `$FOO`, `${FOO}`, and deterministic environment object keys target `env:*`.

MCP server names, model names, profile names, prompt aliases, and project
aliases remain `config.path` nodes and metadata in CFG1. No `mcp.server:*`,
`model:*`, or `profile:*` namespaces were added.

## Canonical Readback Examples

After discovery and `storage load-files`, use canonical readback:

```sh
repomap-kg storage nodes --kind config.document --json
repomap-kg storage nodes --kind config.path --json
repomap-kg storage edges --kind defines --json
repomap-kg storage edges --kind references --json
```

Explain a config reference edge with canonical edge identity:

```sh
repomap-kg storage explain-canonical-edge \
  --root-path /path/to/repo \
  --source-key 'config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand' \
  --kind references \
  --target-key tool:repomap-kg \
  --json
```

## Fixtures And Tests

CFG1 added:

- graph key builder/parser tests for `config.document` and `config.path`;
- unit tests for JSON object paths, nested pointer escaping, array policy,
  parse errors, JSONL mixed valid/malformed lines, JSONC comments and trailing
  commas, redaction, file/env/tool/URL references, and dynamic/unknown
  placeholders;
- canonicalization tests for `config.document`, `config.path`, `references`,
  raw-only JSONL records, raw-only parse errors, and malformed/missing targets;
- discovery fixture `src/test/fixtures/discovery/config_json_basic/`;
- golden canonicalization fixture
  `src/test/fixtures/canonicalization/config_json_basic/`;
- integration contract coverage for CFG1 graph keys, exact golden
  serialization, JSON-family discovery, and config canonicalization
  diagnostics; and
- storage integration coverage that discovers the config fixture, loads it
  through `storage load-files`, queries canonical `config.document` and
  `config.path` nodes, queries `defines` and `references` edges, and explains a
  `references` edge.

## Known Gaps

- TOML is deferred to CFG2.
- JSONC support is conservative and is not a full JSONC specification
  implementation.
- JSON schema validation and app-specific config semantics are deferred.
- Array element canonical identity is deferred unless a future phase defines a
  stable member-key policy.
- MCP server, model, profile, prompt, and project alias namespaces are deferred.
- URL fetching, command execution, environment expansion, secret hashing,
  cross-project resolution, embeddings, graph visualization, and MCP write
  tools remain out of scope.

## IPC Verification Incident

CFG1 integration verification was initially blocked by current-user System V
shared-memory segments left by failed temporary Postgres bootstrap attempts.
The first sandboxed integration run failed with `Operation not permitted` from
`shmget`; the host-IPC rerun then failed with `No space left on device`,
matching SHMMNI exhaustion.

The user explicitly authorized removal for this CFG1 incident only. Before
cleanup:

- `id -un` returned `slair`;
- `ps aux | grep -E '[p]ostgres|[p]ostmaster|[i]nitdb'` returned no live
  Postgres, postmaster, or initdb processes; and
- `ipcs -m -a` showed the listed shared-memory segments were owned and created
  by `slair`, had `NATTCH 0`, had size `56`, and matched the leaked temporary
  Postgres bootstrap pattern.

Cleanup removed only the exact user-authorized segment IDs with `ipcrm -m`,
without `sudo`. It did not remove semaphores, message queues, files,
directories, other-user segments, attached segments, or any segment outside the
authorized list. After cleanup, `ipcs -m` showed no shared-memory segments.

The integration suite passed after cleanup.

## Verification

The final CFG1 source-change verification suite passed:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

The integration and combined suites require host permissions because the
integration harness starts temporary Postgres clusters and sandboxed `initdb`
cannot allocate shared memory.

## Decision

CFG1 is complete. RepoMap can now extract structural configuration facts from
JSON, JSONL, and conservative JSONC files and make them available through
canonical storage/readback while preserving existing public command defaults
and MCP behavior.
