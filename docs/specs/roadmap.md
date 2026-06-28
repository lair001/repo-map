# RepoMap Roadmap

## Phase 0: Project Skeleton

- Establish repository structure.
- Add Apache-2.0 license.
- Add public architecture, storage, extractor, and roadmap specs.
- Define initial coding and testing expectations.

## Phase 1: Core Graph Schema

- Define raw observation JSONL schema.
- Define Postgres schema and migrations.
- Implement repository discovery.
- Implement profile loading.
- Implement normalization from raw observations to graph tables.
- Add CLI commands for database setup and basic inspection.

## Phase 2: File and Entry-Point Graph

- Detect files, languages, executable scripts, and roles.
- Create File, Script, EntryPoint, and Repository nodes.
- Add project profile support for user-facing command directories and internal
  implementation directories.
- Add first CLI queries: `entrypoints`, `files`, and `explain`.

## Phase 3: Shell Extractor

- Parse shell-family scripts.
- Extract functions, sourced files, command invocations, environment contracts,
  redirections, and obvious file operations.
- Mark dynamic shell facts with appropriate confidence.
- Add host-mutator detection.

## Phase 4: Nix Extractor

- Extract imports, flake outputs, packages, apps, checks, dev shells, overlays,
  and script references.
- Add optional safe evaluation mode.
- Connect Nix outputs to executable scripts and tools.

## Phase 5: Python and Ruby Extractors

- Add Python AST-based extraction.
- Add conservative Ruby extraction.
- Connect shell wrappers to Python and Ruby implementation files where possible.

## Phase 6: Query Layer

- Add CLI queries for common impact-analysis work:
  - callers;
  - tests-for;
  - host-mutators;
  - paths;
  - env-contract;
  - blast-radius.

## Phase 7: Reports and Adapters

- Add human-readable reports.
- Add optional MCP adapter after the CLI and database model are useful.
- Consider graph export formats for visualization or dedicated graph tools.

## Deferred Ideas

- Web UI.
- Embedding or vector search.
- Dedicated graph database backend.
- Multi-user server mode.
- Language-server integration.
