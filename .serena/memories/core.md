# RepoMap Core

- Local deterministic knowledge graph builder for polyglot software repos; no LLM-guessed graph edges.
- Primary source tree: `src/main/python/repomap_kg`; tests mirror under `src/test/unit/python/repomap_kg` and `src/test/int/python/repomap_kg`.
- Public specs and ADRs live under `docs/specs` and `docs/adr`; start with architecture, extractor strategy, raw observation schema, storage model, profile schema, roadmap, and the graph identity/key-vocabulary/canonicalizer/canonical-storage ADRs.
- Current pipeline boundary: discovery/language extractors -> raw observation JSONL -> pure canonicalization/normalization boundaries -> additive Postgres storage -> CLI readback. Legacy public readback still uses observation-derived tables.
- Raw observations are the fixture/debug/interchange boundary. See `mem:conventions` for stable-key and confidence expectations.
- Structured configuration extraction is covered in `mem:extractors/configuration`; read it before changing JSON/JSONL/JSONC/TOML config observations, redaction, or `references` edges.
- Storage uses Postgres relational property-graph tables plus JSONB metadata. Phase C1 added raw-observation retention and canonical graph tables through `2026/06/29-001-core-create_raw_observations.sql` and `2026/06/29-002-core-create_canonical_graph_tables.sql`; `storage load-canonical` remains developer-facing only. Phase C2 made `storage load-files` dual-write legacy rows plus raw/canonical storage rows in one transaction while preserving public output/readback. See `mem:tech_stack` and `mem:task_completion` before touching DB-backed code.
- CLI entrypoint is `repomap_kg.cli:main`; package import name is `repomap_kg`; distribution and command name are `repomap-kg`.
- Current roadmap checkpoint: canonical storage/readback, read-only multi-project MCP, Markdown docs extraction, Nix extraction, JSON-family config extraction, TOML config extraction, and the Phase F3 canonical migration pause are complete. Do not start new phases, add graph vocabulary, change public defaults, add extractors, or change MCP write/load behavior without explicit phase instructions.
