# Self-Graph Python Extractor Exit

Date: 2026-06-29

## Scope

Phase S1 added parser-backed Python raw observations and canonicalization so
RepoMap can build a useful canonical graph of the RepoMap project itself.

This phase stayed limited to Python extractor dogfooding. It did not start MCP,
Nix extraction, Phase E legacy-query migration, embeddings, graph
visualization, or canonical key grammar changes.

## Implemented Observation Kinds

The Python extractor emits these raw observation kinds from `ast` parsing:

- `python.module`
- `python.import`
- `python.class`
- `python.function`
- `python.method`

All parser-backed Python observations use `confidence="extracted"` and include
path, source id, line spans, extractor name/version, name, target, and
metadata. Python files with syntax errors are skipped by the Python extractor
without crashing discovery.

## Canonical Mapping

Python definitions map to `defines` edges from the source file:

- `file:<path> --defines--> python.module:<module>`
- `file:<path> --defines--> python.class:<module>:<class>`
- `file:<path> --defines--> python.function:<module>:<function>`
- `file:<path> --defines--> python.method:<module>:<class>:<method>`

Python imports map to `imports` edges from the source module:

- `python.module:<source> --imports--> python.module:<target>`
- `python.module:<source> --imports--> external:python.module:<target>`
- `python.module:<source> --imports--> unknown:python.module:<reason>`

Line numbers remain evidence fields. They are not part of canonical keys.

## Self-Graph Commands

These commands graph RepoMap itself and read back canonical Python facts:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --jsonl > /tmp/repomap.jsonl

PYTHONPATH=src/main/python python3 -m repomap_kg storage load-files /tmp/repomap.jsonl \
  --repository-name repo-map \
  --root-path . \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-nodes \
  --root-path . \
  --kind python.module \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-edges \
  --root-path . \
  --kind imports \
  --source-key python.module:repomap_kg.cli \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage explain-canonical-edge \
  --root-path . \
  --source-key python.module:repomap_kg.cli \
  --kind imports \
  --target-key python.module:repomap_kg.storage \
  --json
```

The storage commands assume a migrated RepoMap Postgres database is reachable
through the default Postgres environment or explicit `--pg-*` flags.

## Observed Self-Discovery

This command was run successfully against RepoMap itself:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --jsonl > /private/tmp/repomap-self.jsonl
```

It emitted 1,490 raw observations:

| Kind | Count |
| --- | ---: |
| `file` | 120 |
| `python.class` | 74 |
| `python.function` | 338 |
| `python.import` | 519 |
| `python.method` | 400 |
| `python.module` | 39 |

## Verification

The unit suite passed with the new Python extractor and canonicalization
coverage:

```sh
python3 tools/run_tests.py --suite unit
```

The integration suite could not complete in this run because the host had
orphaned shared-memory segments that caused temporary Postgres `initdb` to fail
with `could not create shared memory segment`. The S1 integration test is in
place and should be rerun after IPC cleanup or reboot:

```sh
python3 tools/run_tests.py --suite int
```

## Decision

Phase S1 has a Python AST extractor, discovery integration, canonical mapping,
golden fixtures, and storage readback coverage for Python facts. The remaining
external verification dependency is a clean temporary-Postgres environment for
the integration suite.
