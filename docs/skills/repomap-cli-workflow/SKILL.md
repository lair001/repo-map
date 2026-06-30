---
name: repomap-cli-workflow
description: Use when running RepoMap outside MCP to discover a repository, load raw observations into storage, query canonical readback commands, inspect evidence, or prepare a graph for read-only MCP use.
---

# RepoMap CLI Workflow

## Overview

Use RepoMap as a local repository graph builder and readback tool. The normal
flow is discovery, storage load, canonical CLI readback, and optional read-only
MCP readback. Keep extraction and loading outside MCP; MCP is read-only.

## Standard Flow

1. Choose the repository root and profile.
2. Run discovery to JSONL:

```sh
repomap-kg discover <repo-root> --jsonl > /private/tmp/<name>-observations.jsonl
```

3. Load observations into Postgres with `storage load-files`:

```sh
repomap-kg storage load-files /private/tmp/<name>-observations.jsonl \
  --repository-name <name> \
  --root-path <repo-root> \
  --pg-database <database>
```

4. Query public canonical readback commands:

```sh
repomap-kg storage canonical-nodes --root-path <repo-root> --kind python.module --json
repomap-kg storage canonical-edges --root-path <repo-root> --kind imports --json
repomap-kg storage explain-canonical-edge --root-path <repo-root> --source-key <key> --kind <kind> --target-key <key> --json
repomap-kg storage canonical-neighborhood --root-path <repo-root> --node <canonical-key> --direction both --json
```

5. Configure MCP project registry only after storage exists and readback works.

## Current Extraction Families

RepoMap has static extraction and canonicalization for:

- files and shell observations;
- Python AST modules, definitions, and imports;
- static Nix imports and flake output facts;
- Markdown/documentation pages, headings, links, frontmatter, code fences, ADR
  metadata, and skill metadata.

Do not run `nix eval`, execute project code, fetch URLs, execute Markdown code
blocks, or treat MCP as a write surface unless a later accepted phase explicitly
changes that.

## Readback Guidance

Prefer canonical graph identity:

- canonical node keys such as `file:bin/tool`, `python.module:pkg.app`,
  `nix.app:repo-map:aarch64-darwin:default`, and
  `doc.page:file%3AREADME.md`;
- canonical edge identity as source key, edge kind, target key, graph key
  version, and identity metadata hash;
- evidence and raw observations for line spans, extractor versions, and raw
  source ids.

Do not present database integer ids, legacy `stable_key`, raw observation source
ids, or line numbers as canonical identity.
