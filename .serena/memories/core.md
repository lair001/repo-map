# RepoMap Core

- Local deterministic knowledge graph builder for polyglot software repos; no LLM-guessed graph edges.
- Primary source tree: `src/main/python/repomap_kg`; tests mirror under `src/test/unit/python/repomap_kg` and `src/test/int/python/repomap_kg`.
- Public specs and ADRs live under `docs/specs` and `docs/adr`; start with architecture, extractor strategy, raw observation schema, storage model, profile schema, roadmap, and the graph identity/key-vocabulary/canonicalizer ADRs.
- Pipeline invariant before canonical storage: discovery/language extractors -> raw observation JSONL -> pure canonicalization/normalization boundaries -> Postgres storage -> CLI readback.
- Raw observations are the fixture/debug/interchange boundary. See `mem:conventions` for stable-key and confidence expectations.
- Storage uses Postgres relational property-graph tables plus JSONB metadata. See `mem:tech_stack` and `mem:task_completion` before touching DB-backed code.
- CLI entrypoint is `repomap_kg.cli:main`; package import name is `repomap_kg`; distribution and command name are `repomap-kg`.
- Current roadmap: Phase 3 shell extractor is paused while canonicalization Phase B is built as a pure tested layer. Phase A1/A2 has graph key builders/parsers/validators plus canonical diagnostics/dataclasses/serialization in `repomap_kg.graph_keys`, `repomap_kg.canonical_diagnostics`, and `repomap_kg.canonical`. Phase B1 now has file canonicalization in `repomap_kg.canonicalization` plus exact golden fixture coverage under `src/test/fixtures/canonicalization/files_basic`; no storage, CLI behavior, or extractor changes are allowed until Phase B is complete except pure-layer tests/helpers. Next likely slice: Phase B2 shell observation mappings (`shell.command`, `shell.source`, `shell.env`, `shell.host_mutation`). Shell facts should remain deterministic and evidence-backed.
