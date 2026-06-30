# N1 Static Nix Extractor Exit

Date: 2026-06-29

## Scope

N1 added static Nix extraction for Nix-heavy repositories without evaluating
Nix code.

The phase stayed limited to deterministic text scanning, raw observations,
canonicalization for the first Nix observation kinds, fixtures, and tests. It
did not run `nix eval`, run `nix flake show`, execute project code, start Phase
E, add write-capable MCP tools, change canonical key grammar, change legacy
command output, add embeddings, add graph visualization, or add parser-backed
Ruby extraction.

## Supported Patterns

The Nix extractor reads `.nix` files as text and emits heuristic observations.

Supported raw observation kinds:

- `nix.import`
- `nix.app`
- `nix.package`
- `nix.devShell`
- `nix.check`
- `nix.path_ref`

Supported static import forms:

- `import ./path.nix`
- `imports = [ ./module.nix ... ];`
- multiline `imports = [ ... ];` lists containing relative `.nix` paths

Supported flake output attr forms in `flake.nix`:

- `apps.<system>.<name>`
- `packages.<system>.<name>`
- `devShells.<system>.<name>`
- `checks.<system>.<name>`

Supported app `program` path forms:

- `program = "${self}/bin/tool";`
- `program = toString ./bin/tool;`
- `program = ./bin/tool;`

The extractor also emits `nix.path_ref` for clear static relative repository
path references that are not consumed as imports or app program paths. These
raw observations are retained but are not canonicalized in N1 because ADR 0002
does not define a conservative edge kind for generic path use.

All Nix facts use `confidence="heuristic"` and include path, line span,
source id, extractor name/version, target, and metadata.

## Canonical Mapping

N1 canonicalizes Nix imports and obvious flake outputs:

- `nix.import` maps `file:<source-nix-file> --sources--> file:<target-nix-file>`
  or to an explicit `dynamic:*`, `unknown:*`, or `external:*` placeholder when
  the target cannot be resolved precisely.
- `nix.app` maps `file:<flake.nix> --defines-->
  nix.app:<flake-ref>:<system>:<name>`.
- `nix.app` with a static repository program path also maps
  `nix.app:<flake-ref>:<system>:<name> --exposes_script-->
  file:<program_path>`.
- `nix.package` maps `file:<flake.nix> --defines-->
  nix.package:<flake-ref>:<system>:<name>`.
- `nix.devShell` maps `file:<flake.nix> --defines-->
  nix.devShell:<flake-ref>:<system>:<name>`.
- `nix.check` maps `file:<flake.nix> --defines-->
  nix.check:<flake-ref>:<system>:<name>`.

For local repositories, `flake_ref` is the discovered repository directory
name. For RepoMap itself, that is `repo-map`. Absolute checkout paths are not
used in Nix canonical keys.

## Private-Project Usage

Run discovery and load canonical storage through the existing dual-write path:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg discover /path/to/repo --jsonl \
  > /private/tmp/private-repo-observations.jsonl

PYTHONPATH=src/main/python python3 -m repomap_kg storage load-files \
  /private/tmp/private-repo-observations.jsonl \
  --repository-name private-repo \
  --root-path /path/to/repo \
  --json
```

Example canonical readback commands:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-nodes \
  --root-path /path/to/repo \
  --kind nix.app \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-nodes \
  --root-path /path/to/repo \
  --kind nix.package \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-edges \
  --root-path /path/to/repo \
  --kind sources \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-edges \
  --root-path /path/to/repo \
  --kind defines \
  --source-key file:flake.nix \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage canonical-edges \
  --root-path /path/to/repo \
  --kind exposes_script \
  --json

PYTHONPATH=src/main/python python3 -m repomap_kg storage explain-canonical-edge \
  --root-path /path/to/repo \
  --source-key nix.app:private-repo:aarch64-darwin:tool \
  --kind exposes_script \
  --target-key file:bin/tool \
  --json
```

## Fixtures And Tests

N1 added:

- unit tests for static import extraction;
- unit tests for flake output attr extraction;
- unit tests for app `program` path extraction;
- unit tests for dynamic, external, unknown, and repo-escaping cases;
- canonicalization tests for `nix.import`, `nix.app`, `nix.package`,
  `nix.devShell`, and `nix.check`;
- golden canonicalization fixture
  `src/test/fixtures/canonicalization/nix_flake_basic/`;
- discovery fixture `src/test/fixtures/discovery/nix_flake_basic/`;
- integration coverage that discovers the Nix fixture, loads it through
  `storage load-files`, queries canonical Nix nodes and edges, and explains a
  Nix app `exposes_script` edge.

## Known Gaps

- No Nix evaluation is performed.
- Dynamic attr generation, `eachDefaultSystem`, overlays, module option
  semantics, and flake input resolution are not interpreted.
- `nix.path_ref` remains raw-only because N1 deliberately did not add
  `imports_nix`, `uses_path`, `configures`, `declares`, or similar edge kinds.
- Static scanning is conservative and heuristic; it may miss valid Nix patterns
  that require parsing or evaluation.
- Ruby extraction has not started.
- Phase E legacy-query migration has not started.

## IPC Verification Incident

Integration verification was initially blocked by orphaned System V shared
memory segments from failed temporary Postgres bootstrap attempts. The user
explicitly authorized removal of only the listed current-user segments for this
N1 incident.

Before cleanup:

- `id -un` returned `slair`.
- `ps aux | grep -E '[p]ostgres|[p]ostmaster|[i]nitdb'` returned no live
  Postgres, postmaster, or initdb processes.
- `ipcs -m` and `ipcs -m -a` showed the listed segments were owned and created
  by `slair`, had `NATTCH 0`, and matched the leaked temporary Postgres
  bootstrap pattern.

Cleanup used the user-provided exact shared-memory id loop with `ipcrm -m`,
without `sudo`, and did not remove semaphores, message queues, files,
directories, segments owned by another user, attached segments, or any segment
outside the explicit list. After cleanup, `ipcs -m` showed no shared-memory
segments.

The post-cleanup integration suite and combined suite passed after the cleanup
and N1 coverage fix.

## Verification

The final N1 source-change verification suite passed:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

The integration and combined suites require host permissions because the
integration harness starts temporary Postgres clusters and sandboxed `initdb`
cannot allocate shared memory.

## Decision

N1 is complete. RepoMap now extracts static Nix facts that connect flake
outputs, app scripts, imports, and repository files enough to make canonical
readback useful for Nix-heavy private repositories.
