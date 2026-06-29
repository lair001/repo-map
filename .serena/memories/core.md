# RepoMap Core

- Local deterministic knowledge graph builder for polyglot software repos; no LLM-guessed graph edges.
- Primary source tree: `src/main/python/repomap_kg`; tests mirror under `src/test/unit/python/repomap_kg` and `src/test/int/python/repomap_kg`.
- Public specs live under `docs/specs`; start with architecture, extractor strategy, raw observation schema, storage model, profile schema, and roadmap.
- Pipeline invariant: discovery/language extractors -> raw observation JSONL -> normalization -> Postgres storage -> CLI readback.
- Raw observations are the fixture/debug/interchange boundary. See `mem:conventions` for stable-key and confidence expectations.
- Storage uses Postgres relational property-graph tables plus JSONB metadata. See `mem:tech_stack` and `mem:task_completion` before touching DB-backed code.
- CLI entrypoint is `repomap_kg.cli:main`; package import name is `repomap_kg`; distribution and command name are `repomap-kg`.
- Current roadmap: Phase 3 shell extractor is underway. Current discovery emits simple `shell.command`, static `shell.source`, static `shell.env`, and first-pass `shell.host_mutation` observations for package, service, system activation, and obvious filesystem mutations; `repomap-kg host-mutators <raw-observations.jsonl>` and `repomap-kg storage host-mutators --root-path <path>` read those host-mutating facts back as table or JSON. Shell facts should remain deterministic and evidence-backed.
