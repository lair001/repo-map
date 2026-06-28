# RepoMap

RepoMap is a local, deterministic knowledge graph builder for polyglot software
repositories.

The first goal is to map how a repository actually works: entry points, scripts,
source/include relationships, imports, generated artifacts, tests, coverage
targets, environment contracts, and host-mutating operations. The project is
designed for repositories where behavior crosses language boundaries through
shell wrappers, Nix configuration, Python utilities, Ruby scripts, generated
files, and command-line tools.

## Project Identity

- Official name: RepoMap
- Git repository: `repo-map`
- Python distribution: `repomap-kg`
- Python import package: `repomap_kg`
- CLI: `repomap-kg`
- License: Apache-2.0
- Primary database: Postgres container

## Design Principles

- Deterministic extractors first; no LLM-guessed graph edges.
- Preserve evidence: graph facts should point back to file paths and lines.
- Mark confidence explicitly: extracted, heuristic, manual, or unknown.
- Treat shell, Nix, and process orchestration as first-class concerns.
- Keep raw extractor output exportable as JSONL.
- Store normalized graph data in Postgres.
- Keep project-specific conventions in profiles rather than hardcoding them.

## Current Status

RepoMap has an initial Python package skeleton with a minimal CLI identity
surface, raw observation JSONL validation, first file and entrypoint queries,
and initial Postgres schema-backed file ingestion. The initial specs live under
`docs/specs/`.

## Development

Run the CLI from the source tree:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg --version
PYTHONPATH=src/main/python python3 -m repomap_kg identity --json
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --profile repomap-profile.toml --jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg entrypoints raw-observations.jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg files raw-observations.jsonl --role source
PYTHONPATH=src/main/python python3 -m repomap_kg observations normalize raw-observations.jsonl --json
```

Run the host-safe test suites with coverage gates:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
```

The project runner uses stdlib `unittest` and `trace`, so the initial test
suite does not require network access or third-party test packages. Unit,
integration, and combined runs enforce an 85 percent aggregate line coverage
gate and print per-file advisory rows.

## Specifications

- [Architecture](docs/specs/architecture.md)
- [Storage Model](docs/specs/storage-model.md)
- [Extractor Strategy](docs/specs/extractor-strategy.md)
- [Project Profile Schema](docs/specs/profile-schema.md)
- [Raw Observation Schema](docs/specs/raw-observation-schema.md)
- [Roadmap](docs/specs/roadmap.md)

## License

RepoMap is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
