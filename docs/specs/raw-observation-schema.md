# Raw Observation Schema

RepoMap extractors emit raw observations as newline-delimited JSON before any
database or graph-store normalization happens. The raw stream is the debugging,
fixture, and interchange boundary between deterministic extractors and the
normalizer.

## JSONL Contract

Each line is one JSON object with `schema_version` set to `1`.

Required fields:

- `kind`: observation family, such as `file`, `shell.command`, or
  `python.import`.
- `source_id`: extractor-stable source identity for the observed fact.
- `path`: repository-relative path where the fact was observed.
- `confidence`: one of `extracted`, `heuristic`, `manual`, or `unknown`.
- `extractor`: extractor name.
- `extractor_version`: extractor version.
- `metadata`: extractor-specific object. Empty metadata is `{}`.

Optional fields:

- `start_line` and `end_line`: positive integer evidence line range. If one is
  present, both must be present.
- `name`: extracted name or value.
- `target`: related target key when the extractor can identify one.

Example:

```json
{"confidence":"heuristic","end_line":2,"extractor":"fixture-shell","extractor_version":"0.1.0","kind":"shell.command","metadata":{"fixture":true},"name":"nix build","path":"scripts/build.sh","schema_version":1,"source_id":"scripts/build.sh#call:nix-build","start_line":2,"target":"tool:nix"}
```

The `repo-discovery` extractor emits `file` observations. Their metadata
contains:

- `language`: detected language, or `unknown`.
- `role`: high-level file role, such as `source`, `test`, `config`,
  `documentation`, `entrypoint`, `generated`, or `unknown`.
- `content_hash`: SHA-256 hash of file bytes.
- `executable`: whether the file has an executable bit.
- `generated`: whether the path lives under a generated-output directory.

The `repo-shell` extractor emits conservative `shell.command` observations for
simple shell command invocations discovered from shell-family files. Their
metadata contains:

- `argv`: parsed command arguments after any leading environment assignments.
- `command`: the command token before display-name normalization.
- `raw`: the source line text for the command.

The same extractor emits `shell.source` observations for static `source` and
`.` include statements. Dynamic source paths are skipped. Their metadata
contains:

- `argv`: parsed source/include arguments.
- `source`: the original source path token.
- `resolved_path`: the repository-relative path resolved from the current file.
- `raw`: the source line text for the include.

## Normalization Boundary

The first normalizer maps raw observations into graph-shaped records without a
database dependency:

- one canonical node per raw observation source identity;
- one evidence record per observed file and line range;
- one edge when `target` is present.

The CLI exposes this boundary for fixtures and early integration tests:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg observations normalize raw-observations.jsonl --json
```

The command exits non-zero and prints a validation error when a JSONL line does
not match the schema.
