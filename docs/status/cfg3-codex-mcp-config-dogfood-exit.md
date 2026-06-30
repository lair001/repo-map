# CFG3 Codex/MCP Configuration Dogfood Exit

## Scope

CFG3 dogfooded ADR 0010 structured configuration extraction against a compact
Codex/MCP-style fixture that combines JSON, JSONL, JSONC, and TOML. The phase
added fixtures, exact canonicalization coverage, discovery coverage, storage
readback coverage, and example queries.

CFG3 did not add graph key namespaces, edge kinds, public readback default
changes, MCP behavior changes, MCP write/load/discovery tools, command
execution, URL fetching, environment expansion, external schema validation,
secret storage, Phase F work, or Shell/Bats/AWK work.

## Fixture Files

The dogfood fixture lives at:

```text
src/test/fixtures/discovery/config_codex_mcp_dogfood/
  codex/config.toml
  editor/settings.jsonc
  logs/events.jsonl
  mcp/repo-map/config.json
```

The fixture includes:

- MCP server command/program fields;
- `args` arrays;
- environment-variable objects;
- project aliases;
- repo-local path values;
- absolute path values;
- repo-escaping path values;
- HTTP and mailto URL values;
- dummy secret-like values;
- JSONL valid records plus one malformed line;
- JSONC comments and trailing commas; and
- TOML tables plus arrays of tables with stable member keys.

## Graph Facts Produced

Discovery emits:

- 4 `config.document` observations, one each for JSON, JSONL, JSONC, and TOML;
- `config.path` observations for stable object keys and TOML stable array-table
  members;
- `config.reference` observations for clear tool, file, env, URL, external, and
  unknown repo-escaping references;
- 3 `config.jsonl_record` observations for valid JSONL lines; and
- 1 `config.parse_error` observation for the malformed JSONL line.

Canonical storage contains:

- `file:* --defines--> config.document:*`
- `file:* --defines--> config.path:*`
- `config.path:* --references--> tool:*`
- `config.path:* --references--> file:*`
- `config.path:* --references--> env:*`
- `config.path:* --references--> external.url:*`
- `config.path:* --references--> external:file:absolute-config-reference`
- `config.path:* --references--> unknown:file:repo-escaping-config-reference`

## Useful Queries

After discovering and loading a Codex/MCP-style repository, useful readback
queries include:

```sh
repomap-kg storage nodes --root-path <repo-root> --kind config.document --json
repomap-kg storage nodes --root-path <repo-root> --kind config.path --json
repomap-kg storage edges --root-path <repo-root> --kind references --target-key tool:repomap-kg --json
repomap-kg storage edges --root-path <repo-root> --kind references --target-key env:REPOMAP_MCP_CONFIG --json
repomap-kg storage explain-canonical-edge \
  --root-path <repo-root> \
  --source-key 'config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand' \
  --kind references \
  --target-key tool:repomap-kg \
  --json
```

For MCP configuration specifically:

- find configured command fields with `--kind references --target-key tool:*`
  style filters when the target tool is known;
- inspect repo-local file paths by filtering `references` edges with
  `target-key file:<path>`;
- inspect environment-variable mentions by filtering `references` edges with
  `target-key env:<NAME>`;
- use `explain-canonical-edge` to see the raw observation, path, line span,
  extractor, and evidence metadata behind a config reference.

## Secret Handling

The fixture intentionally contains dummy values under secret-prone keys such as
`api_key`, `refresh_token`, `TOKEN`, `API_KEY`, and `PASSWORD`. Tests assert that
those dummy values do not appear in raw observation metadata, canonical
metadata, golden canonical fixtures, or storage readback/explain output.

## Known Gaps

- MCP server names, model names, profile names, prompt aliases, and project
  aliases remain structural `config.path` nodes and metadata; CFG3 did not add
  new namespaces for them.
- JSONL record identity remains evidence-oriented; CFG3 did not add
  `config.record:*` keys.
- Absolute paths remain external placeholders unless a future profile policy
  accepts host-specific path resolution.
- Repo-escaping paths use explicit unknown placeholders rather than fabricated
  precision.
- The extractor does not execute command fields, fetch URLs, expand environment
  variables, validate external schemas, or read/decrypt secrets.

## Tests Added

CFG3 added:

- discovery integration coverage for the combined Codex/MCP dogfood fixture;
- a golden canonicalization fixture under
  `src/test/fixtures/canonicalization/config_codex_mcp_dogfood/`;
- exact golden fixture checks in unit and integration canonical contract tests;
- storage integration coverage that discovers the fixture, loads it through
  `storage load-files`, queries `config.document` and `config.path` nodes,
  queries `defines` and `references` edges, and explains one tool reference, one
  repo-local file reference, and one environment-variable reference; and
- redaction assertions across discovery, golden fixtures, canonical readback,
  and explain output.

## Verification

Verification performed during CFG3:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

## Exit

CFG3 is complete. RepoMap can now dogfood structured configuration extraction
against Codex/MCP-style JSON, JSONL, JSONC, and TOML fixtures. The recommended
next graph-coverage area remains a Shell/Bats/AWK graph-model ADR before
implementation.
