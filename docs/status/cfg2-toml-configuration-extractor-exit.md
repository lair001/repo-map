# CFG2 TOML Configuration Extractor Exit

Status: Complete

## Scope

CFG2 implemented the TOML subset of ADR 0010 for structured configuration
extraction. The phase was limited to static `.toml` parsing through Python's
standard-library `tomllib` and reuse of the CFG1 configuration graph model:

- `config.document`
- `config.path`
- `config.reference`
- `config.parse_error`
- `file:* --defines--> config.document:*`
- `file:* --defines--> config.path:*`
- `config.path:* --references--> <target>`

CFG2 did not change public readback defaults, MCP behavior, storage migrations,
graph key namespaces, or edge vocabulary.

## Implemented TOML Patterns

The extractor now emits one `config.document` observation for each parseable
`.toml` file and emits `config.path` observations for:

- TOML tables;
- nested tables;
- dotted keys;
- scalar leaves;
- arrays of scalars as summary-only array paths;
- arrays of tables with deterministic stable member keys;
- arrays of tables without stable member keys as summary-only array paths.

Malformed TOML emits `config.parse_error` with `format=toml`,
`parser=stdlib-tomllib`, and `error_kind=malformed-toml`. Parse errors remain
raw/evidence-only and do not fabricate canonical config nodes.

## Pointer Normalization

TOML structure is normalized into ADR 0010 JSON Pointer style:

- `[mcp_servers.repomap]` becomes `/mcp_servers/repomap`;
- `mcp_servers.repomap.command` becomes `/mcp_servers/repomap/command`;
- `dotted.guide_path = "docs/guide.md"` under `[mcp_servers.repomap]` becomes
  `/mcp_servers/repomap/dotted/guide_path`;
- `[[tools]]` with `name = "repomap"` may emit `/tools/repomap` and
  `/tools/repomap/command`;
- `[[tools]]` with `id = "helper"` may emit `/tools/helper` and
  `/tools/helper/command`.

Numeric array indexes are not used in canonical `config.path:*` keys.

## Redaction

CFG2 reuses CFG1 secret-prone key detection for TOML:

- token
- secret
- password
- passwd
- api_key
- apikey
- credential
- private_key
- access_key
- refresh_token
- bearer
- auth

Secret-prone TOML values are excluded from raw observation metadata, canonical
node metadata, edge metadata, golden fixtures, and serialized readback output.
Redacted metadata preserves safe facts such as `value_type`, `redacted=true`,
and `redaction_reason=secret-prone-key`.

## Reference Behavior

CFG2 reuses CFG1 conservative reference detection for TOML scalar values and
deterministic arrays:

- simple `command`, `cmd`, `executable`, or `program` values produce `tool:*`
  references;
- `args` arrays produce `tool:*` references only when the first element is a
  clear command name, not an option such as `-m`;
- repo-local relative paths produce `file:*` references;
- repo-escaping paths produce `unknown:file:repo-escaping-config-reference`;
- absolute paths produce `external:file:absolute-config-reference`;
- dynamic paths with variables, globs, templates, or home markers produce
  `dynamic:file:config-reference-expanded-from-variable`;
- `http`, `https`, and `mailto` values produce `external.url:*` references
  without fetching;
- environment-object keys and `$FOO`/`${FOO}` values produce `env:*`
  references when deterministic.

Line spans are populated for common TOML scalar keys and for stable array-table
members, so repeated keys such as `command` in different TOML tables can still
produce useful evidence locations.

## Canonical Readback Examples

After running discovery and loading through `storage load-files`, TOML config
facts can be queried with existing canonical-aware commands:

```sh
repomap-kg storage nodes --kind config.document --json
repomap-kg storage nodes --kind config.path --path-prefix mcp/ --json
repomap-kg storage edges --kind references --json
repomap-kg storage explain-canonical-edge \
  --source-key 'config.path:file%3Amcp%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand' \
  --kind references \
  --target-key tool:python3 \
  --json
```

## Tests Added

CFG2 added:

- unit tests for TOML document parsing, tables, dotted keys, nested structures,
  scalar leaves, arrays of scalars, arrays of tables with and without stable
  keys, malformed TOML, redaction, and file/env/tool/URL references;
- a canonicalization unit test proving TOML observations reuse the existing
  config canonicalization contract;
- a discovery fixture under
  `src/test/fixtures/discovery/config_toml_basic/`;
- a golden canonicalization fixture under
  `src/test/fixtures/canonicalization/config_toml_basic/`;
- exact golden fixture coverage in unit and integration contract tests;
- an integration discovery test for TOML fixture observations;
- a storage integration test that discovers TOML, loads through
  `storage load-files`, queries canonical `config.document` and `config.path`
  nodes, queries `defines` and `references` edges, and explains one TOML
  `references` edge.

## Known Gaps

- TOML arrays of tables require unique stable member keys from `name`, `id`,
  `key`, or `project`; duplicate or missing stable member keys remain
  summary-only.
- Numeric array indexes remain excluded from canonical identity.
- Quoted TOML keys with embedded dots are handled conservatively by the current
  lightweight line locator.
- TOML semantics are structural and syntactic only. RepoMap does not validate
  external schemas or interpret app-specific config formats deeply.

## Out Of Scope Confirmations

CFG2 did not:

- change JSON, JSONL, or JSONC behavior beyond shared reference and evidence
  helper refinements needed by TOML;
- resume Phase F;
- start Shell/Bats/AWK extraction;
- change MCP behavior;
- add MCP write, load, or discovery tools;
- execute commands found in config;
- fetch URLs;
- expand environment variables;
- validate external schemas;
- store secret values;
- add graph key namespaces beyond ADR 0010;
- add edge kinds beyond ADR 0010 `references`;
- add `config.record:*`.

## Verification

Verification performed during CFG2:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`
- `python3 tools/run_tests.py --suite all`
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
- `git diff --check`
- `git diff --cached --check`
