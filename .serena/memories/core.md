# RepoMap Core

- Local deterministic knowledge graph builder for polyglot software repos; no LLM-guessed graph edges.
- Primary source tree: `src/main/python/repomap_kg`; tests mirror under `src/test/unit/python/repomap_kg` and `src/test/int/python/repomap_kg`.
- Public specs and ADRs live under `docs/specs` and `docs/adr`; start with architecture, extractor strategy, raw observation schema, storage model, profile schema, roadmap, and the graph identity/key-vocabulary/canonicalizer/canonical-storage ADRs.
- Current pipeline boundary: discovery/language extractors -> raw observation JSONL -> pure canonicalization/normalization boundaries -> additive Postgres storage -> CLI readback. Legacy public readback still uses observation-derived tables.
- Raw observations are the fixture/debug/interchange boundary. See `mem:conventions` for stable-key and confidence expectations.
- Storage uses Postgres relational property-graph tables plus JSONB metadata. Phase C1 added raw-observation retention and canonical graph tables through `2026/06/29-001-core-create_raw_observations.sql` and `2026/06/29-002-core-create_canonical_graph_tables.sql`; `storage load-canonical` is developer-facing only. `storage load-files` does not dual-write canonical rows yet. See `mem:tech_stack` and `mem:task_completion` before touching DB-backed code.
- CLI entrypoint is `repomap_kg.cli:main`; package import name is `repomap_kg`; distribution and command name are `repomap-kg`.
- Current roadmap: Phase C1 is complete with `docs/status/phase-c1-canonical-storage-exit.md`. C2 dual-write is safe to start only after explicit user instruction. Do not add public canonical readback, Phase D queries, MCP, embeddings, parser-backed Python/Nix/Ruby extraction, or replacement/removal of `files`, `nodes`, `edges`, or `evidence` until a later approved phase.
