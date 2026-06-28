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

- Human name: RepoMap
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

RepoMap is in the design/specification stage. The initial specs live under
`docs/specs/`.

## Specifications

- [Architecture](docs/specs/architecture.md)
- [Storage Model](docs/specs/storage-model.md)
- [Extractor Strategy](docs/specs/extractor-strategy.md)
- [Roadmap](docs/specs/roadmap.md)

## License

RepoMap is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
