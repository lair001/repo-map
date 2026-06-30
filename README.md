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
- License: AGPL-3.0-or-later plus commercial licensing
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

RepoMap has a working deterministic raw-observation pipeline, legacy
observation-derived Postgres readback, and canonical graph storage/readback.
Discovery emits file, entrypoint, shell command, sourced-file, environment,
host-mutation, Python AST, and static Nix observations as JSONL. Legacy storage
commands still read from the observation-derived `files`, `nodes`, `edges`, and
`evidence` tables for compatibility.

Canonicalization now runs as a tested pure layer before storage. Phase C1 added
raw-observation retention plus `canonical_nodes`, `canonical_edges`,
`canonical_evidence`, and evidence join tables, with developer-facing
`storage load-canonical` for loading canonical fixtures. Phase C2 made
`storage load-files` dual-write both legacy rows and canonical rows in one
transaction while preserving existing public output and legacy readback
behavior. Phase D added public canonical readback commands for canonical nodes,
canonical edges, edge explanations, and depth-1 canonical neighborhoods under
[ADR 0007](docs/adr/0007-canonical-readback-and-explain-query-contracts.md).
Phase E3 made `storage summary` canonical-aware by default while preserving the
previous observation-derived summary shape behind `--legacy`. Phase F2 made
`storage nodes` and `storage edges` canonical by default while keeping their
old observation-derived output behind `--legacy`.
N1 added a static Nix extractor for imports, obvious flake outputs, app program
paths, and raw-only path references without evaluating Nix. The initial specs
live under `docs/specs/`.

## Development

Run the CLI from the source tree:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg --version
PYTHONPATH=src/main/python python3 -m repomap_kg identity --json
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --profile repomap-profile.toml --jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg entrypoints raw-observations.jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg files raw-observations.jsonl --role source
PYTHONPATH=src/main/python python3 -m repomap_kg host-mutators raw-observations.jsonl --category service-management --tool launchctl --json
PYTHONPATH=src/main/python python3 -m repomap_kg host-mutators-summary raw-observations.jsonl --json
PYTHONPATH=src/main/python python3 -m repomap_kg observations normalize raw-observations.jsonl --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage load-files raw-observations.jsonl --repository-name repo-map --root-path . --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage files --root-path . --role source --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage entrypoints --root-path . --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage file-nodes --root-path . --path README.md --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage nodes --root-path . --kind file --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage nodes --legacy --root-path . --kind shell.command --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage neighborhood --root-path . --node tool:nix --direction in --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage file-neighborhood --root-path . --path bin/tool --direction out --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage edges --root-path . --kind executes --target-key tool:nix --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage edges --legacy --root-path . --kind shell.command --target-node tool:nix --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage host-mutators --root-path . --category filesystem-mutation --tool rm --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage host-mutators-summary --root-path . --category filesystem-mutation --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage summary --root-path . --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage summary --legacy --root-path . --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-nodes --root-path . --kind file --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-edges --root-path . --kind executes --target-key tool:nix --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage explain-canonical-edge --root-path . --source-key file:bin/tool --kind executes --target-key tool:nix --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-neighborhood --root-path . --node tool:nix --direction in --json
```

`storage summary` is canonical-aware by default; use `--legacy` when the older
observation-derived summary shape is required.
`storage nodes` and `storage edges` are canonical by default; use `--legacy`
when the older observation-derived stable-key output is required.

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

Future RepoMap releases are licensed under the GNU Affero General Public
License v3.0 or later. See [LICENSE](LICENSE).

Commercial licenses are available for proprietary terms, including
closed-source embedding, private SaaS deployments, OEM use, support, warranty,
indemnity, and custom commercial terms. See
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

Code released before the `apache-2.0-final` tag remains available under the
Apache License, Version 2.0. Those prior Apache-2.0 grants are not revoked by
the licensing change for future releases.
