import os
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.postgres_harness import PostgresIpcGuard

from repomap_kg.cli import main
from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
    load_file_observations,
    query_canonical_edge_records,
    query_canonical_node_records,
    raw_observation_rows_from_observations,
    raw_observation_upsert_sql,
)


class StorageIntegrationTests(unittest.TestCase):
    def test_apply_migrations_creates_core_graph_tables(self):
        require_postgres_binaries()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            tables = postgres.psql_scalar(
                """
SELECT string_agg(table_name, ',' ORDER BY table_name)
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'repositories',
    'runs',
    'files',
    'nodes',
    'edges',
    'evidence',
    'raw_observations',
    'canonical_nodes',
    'canonical_edges',
    'canonical_evidence',
    'canonical_node_evidence',
    'canonical_edge_evidence'
  );
"""
            )
            inserted_path = postgres.psql_scalar(
                """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', '/tmp/fixture')
RETURNING id
\\gset
INSERT INTO runs(repository_id, status)
VALUES (:id, 'complete')
RETURNING id
\\gset run_
INSERT INTO files(
  repository_id,
  path,
  language,
  role,
  content_hash,
  executable,
  generated
)
VALUES (:id, 'bin/tool', 'shell', 'entrypoint', repeat('0', 64), true, false)
RETURNING id
\\gset file_
INSERT INTO nodes(repository_id, file_id, kind, name, stable_key)
VALUES (:id, :file_id, 'file', 'bin/tool', 'file:bin/tool')
RETURNING id
\\gset node_
INSERT INTO evidence(
  repository_id,
  file_id,
  stable_key,
  extractor,
  metadata_json
)
VALUES (
  :id,
  :file_id,
  'evidence:bin/tool:0-0:repo-discovery:bin/tool',
  'repo-discovery',
  '{"source":"test"}'::jsonb
)
RETURNING id
\\gset evidence_
INSERT INTO edges(
  repository_id,
  src_node_id,
  dst_node_id,
  kind,
  stable_key,
  confidence,
  evidence_id
)
VALUES (
  :id,
  :node_id,
  :node_id,
  'self',
  'edge:file:bin/tool:self:file:bin/tool',
  'manual',
  :evidence_id
);
SELECT path FROM files WHERE role = 'entrypoint';
"""
            )

        self.assertEqual(
            tables,
            "canonical_edge_evidence,canonical_edges,canonical_evidence,"
            "canonical_node_evidence,canonical_nodes,edges,evidence,files,"
            "nodes,raw_observations,repositories,runs",
        )
        self.assertEqual(inserted_path, "bin/tool")

    def test_raw_observation_upsert_is_idempotent_for_same_payload_hash(self):
        require_postgres_binaries()
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"language": "markdown", "role": "documentation"},
        )
        row = raw_observation_rows_from_observations([observation])[0]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            count = postgres.psql_scalar(
                f"""
INSERT INTO repositories(name, root_path)
VALUES ('fixture', '/tmp/fixture')
RETURNING id
\\gset repo_
INSERT INTO runs(repository_id, status)
VALUES (:repo_id, 'complete')
RETURNING id
\\gset run_
{raw_observation_upsert_sql(row)}
{raw_observation_upsert_sql(row)}
SELECT count(*) FROM raw_observations WHERE run_id = :run_id;
"""
            )

        self.assertEqual(count, "1")

    def test_raw_observation_upsert_rejects_same_ordinal_different_hash(self):
        require_postgres_binaries()
        original = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"language": "markdown", "role": "documentation"},
        )
        changed = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"language": "markdown", "role": "source"},
        )
        original_row = raw_observation_rows_from_observations([original])[0]
        changed_row = raw_observation_rows_from_observations([changed])[0]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            with self.assertRaisesRegex(
                AssertionError,
                "raw observation payload hash mismatch",
            ):
                postgres.psql_scalar(
                    f"""
INSERT INTO repositories(name, root_path)
VALUES ('fixture', '/tmp/fixture')
RETURNING id
\\gset repo_
INSERT INTO runs(repository_id, status)
VALUES (:repo_id, 'complete')
RETURNING id
\\gset run_
{raw_observation_upsert_sql(original_row)}
{raw_observation_upsert_sql(changed_row)}
SELECT count(*) FROM raw_observations WHERE run_id = :run_id;
"""
                )

    def test_load_file_observations_inserts_repository_run_and_files(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "f" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:echo",
                path="bin/tool",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                target="tool:echo",
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            summary = load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                git_commit="abc123",
                psql_command=postgres.psql_command,
            )
            row = postgres.psql_scalar(
                """
SELECT repositories.name
       || '|'
       || runs.git_commit
       || '|'
       || files.path
       || '|'
       || files.role
       || '|'
       || files.executable::text
       || '|'
       || (files.metadata_json->>'confidence')
FROM files
JOIN repositories ON repositories.id = files.repository_id
JOIN runs ON runs.id = files.last_seen_run_id;
"""
            )
            graph_row = postgres.psql_scalar(
                """
SELECT nodes.kind
       || '|'
       || nodes.stable_key
       || '|'
       || evidence.extractor
       || '|'
       || evidence.stable_key
FROM files
JOIN nodes ON nodes.file_id = files.id
JOIN evidence ON evidence.file_id = files.id
WHERE files.path = 'bin/tool'
  AND nodes.kind = 'file'
  AND evidence.stable_key = 'evidence:bin/tool:0-0:fixture-discovery:bin/tool';
"""
            )

        self.assertEqual(summary.files, 1)
        self.assertEqual(row, "fixture|abc123|bin/tool|entrypoint|true|manual")
        self.assertEqual(
            graph_row,
            "file|node:bin/tool:file:bin/tool|"
            "fixture-discovery|evidence:bin/tool:0-0:fixture-discovery:bin/tool",
        )

    def test_load_file_observations_inserts_relationship_edges(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "f" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"]},
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            edge_row = postgres.psql_scalar(
                """
SELECT src.kind
       || '|'
       || src.stable_key
       || '|'
       || dst.kind
       || '|'
       || dst.stable_key
       || '|'
       || edges.kind
       || '|'
       || edges.confidence
       || '|'
       || evidence.stable_key
FROM edges
JOIN nodes src ON src.id = edges.src_node_id
JOIN nodes dst ON dst.id = edges.dst_node_id
JOIN evidence ON evidence.id = edges.evidence_id
WHERE edges.kind = 'shell.command';
"""
            )

        self.assertEqual(
            edge_row,
            "shell.command|node:bin/tool:shell.command:bin/tool#call:nix-build|"
            "tool|tool:nix|shell.command|heuristic|"
            "evidence:bin/tool:2-2:fixture-shell:bin/tool#call:nix-build",
        )

    def test_storage_load_files_cli_loads_discovery_jsonl(self):
        require_postgres_binaries()
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "e" * 64,
                "generated": False,
                "executable": False,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            raw_jsonl.write_text(observation.to_json_line())
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "storage",
                    "load-files",
                    str(raw_jsonl),
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                    "storage",
                    "load-files",
                    str(raw_jsonl),
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                )
                stored_path = postgres.psql_scalar(
                    "SELECT path FROM files WHERE path = 'README.md';"
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(set(payload), {"files", "repository_id", "run_id"})
        self.assertEqual(payload["files"], 1)
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertRegex(
            text_stdout,
            r"^loaded 1 files into repository [0-9a-f-]+ run [0-9a-f-]+\n$",
        )
        self.assertEqual(stored_path, "README.md")

    def test_storage_load_files_dual_writes_canonical_shell_collapse_fixture(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            counts = postgres.psql_scalar(
                """
SELECT (SELECT count(*) FROM raw_observations)::text
       || '|'
       || (SELECT count(*) FROM canonical_nodes)::text
       || '|'
       || (SELECT count(*) FROM canonical_edges)::text
       || '|'
       || (SELECT count(*) FROM canonical_evidence)::text
       || '|'
       || (SELECT count(*) FROM canonical_node_evidence)::text
       || '|'
       || (SELECT count(*) FROM canonical_edge_evidence)::text
       || '|'
       || (SELECT count(*) FROM files)::text
       || '|'
       || (SELECT count(*) FROM nodes)::text
       || '|'
       || (SELECT count(*) FROM edges)::text
       || '|'
       || (SELECT count(*) FROM evidence)::text;
"""
            )
            edge_row = postgres.psql_scalar(
                """
SELECT source_canonical_key
       || '|'
       || edge_kind
       || '|'
       || target_canonical_key
FROM canonical_edges;
"""
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(set(payload), {"files", "repository_id", "run_id"})
        self.assertEqual(payload["files"], 0)
        self.assertEqual(counts, "2|2|1|2|4|2|0|3|2|2")
        self.assertEqual(edge_row, "file:bin/tool|executes|tool:nix")

    def test_canonical_query_helpers_read_c2_loaded_rows(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, _stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

            all_nodes = query_canonical_node_records(
                postgres.psql_args,
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            file_nodes = query_canonical_node_records(
                postgres.psql_args,
                root_path="/tmp/fixture",
                kind="file",
                path_prefix="bin/",
                psql_command=postgres.psql_command,
            )
            tool_nodes = query_canonical_node_records(
                postgres.psql_args,
                root_path="/tmp/fixture",
                canonical_key="tool:nix",
                psql_command=postgres.psql_command,
            )
            edges = query_canonical_edge_records(
                postgres.psql_args,
                root_path="/tmp/fixture",
                kind="executes",
                source_key="file:bin/tool",
                target_key="tool:nix",
                psql_command=postgres.psql_command,
            )

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(
            [node.canonical_key for node in all_nodes],
            ["file:bin/tool", "tool:nix"],
        )
        self.assertEqual([node.canonical_key for node in file_nodes], ["file:bin/tool"])
        self.assertEqual(file_nodes[0].display_name, "bin/tool")
        self.assertEqual(file_nodes[0].metadata, {})
        self.assertEqual([node.canonical_key for node in tool_nodes], ["tool:nix"])
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].source_key, "file:bin/tool")
        self.assertEqual(edges[0].edge_kind, "executes")
        self.assertEqual(edges[0].target_key, "tool:nix")
        self.assertEqual(len(edges[0].identity_metadata_hash), 64)
        self.assertFalse(edges[0].conflict)

    def test_storage_canonical_nodes_cli_reads_c2_loaded_rows_and_filters(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

            def run_canonical_nodes(*extra_args):
                return run_repo_map_in_process(
                    "storage",
                    "canonical-nodes",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    *extra_args,
                )

            all_exit_code, all_stdout, all_stderr = run_canonical_nodes("--json")
            kind_exit_code, kind_stdout, kind_stderr = run_canonical_nodes(
                "--kind",
                "file",
                "--json",
            )
            key_exit_code, key_stdout, key_stderr = run_canonical_nodes(
                "--canonical-key",
                "tool:nix",
                "--json",
            )
            prefix_exit_code, prefix_stdout, prefix_stderr = run_canonical_nodes(
                "--path-prefix",
                "bin/",
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_canonical_nodes(
                "--canonical-key",
                "tool:nix",
            )

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(all_exit_code, 0, all_stderr)
        all_payload = json.loads(all_stdout)
        self.assertEqual(
            [record["canonical_key"] for record in all_payload],
            ["file:bin/tool", "tool:nix"],
        )
        self.assertEqual(all_payload[0]["kind"], "file")
        self.assertEqual(all_payload[1]["kind"], "tool")
        self.assertIn("metadata", all_payload[0])
        self.assertIn("first_seen_run_id", all_payload[0])
        self.assertIn("last_seen_run_id", all_payload[0])

        self.assertEqual(kind_exit_code, 0, kind_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(kind_stdout)],
            ["file:bin/tool"],
        )

        self.assertEqual(key_exit_code, 0, key_stderr)
        key_payload = json.loads(key_stdout)
        self.assertEqual([record["canonical_key"] for record in key_payload], [
            "tool:nix",
        ])
        self.assertEqual(key_payload[0]["display_name"], "nix")

        self.assertEqual(prefix_exit_code, 0, prefix_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(prefix_stdout)],
            ["file:bin/tool"],
        )

        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("canonical_key", text_stdout)
        self.assertIn("tool:nix", text_stdout)
        self.assertIn("last_seen_run_id", text_stdout)
        self.assertNotIn("metadata", text_stdout)

    def test_storage_canonical_edges_cli_reads_c2_loaded_rows_and_filters(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

            def run_canonical_edges(*extra_args):
                return run_repo_map_in_process(
                    "storage",
                    "canonical-edges",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    *extra_args,
                )

            all_exit_code, all_stdout, all_stderr = run_canonical_edges("--json")
            kind_exit_code, kind_stdout, kind_stderr = run_canonical_edges(
                "--kind",
                "executes",
                "--json",
            )
            source_exit_code, source_stdout, source_stderr = run_canonical_edges(
                "--source-key",
                "file:bin/tool",
                "--json",
            )
            target_exit_code, target_stdout, target_stderr = run_canonical_edges(
                "--target-key",
                "tool:nix",
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_canonical_edges(
                "--kind",
                "executes",
            )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(all_exit_code, 0, all_stderr)
        all_payload = json.loads(all_stdout)
        self.assertEqual(len(all_payload), 1)
        edge = all_payload[0]
        self.assertEqual(edge["source_key"], "file:bin/tool")
        self.assertEqual(edge["edge_kind"], "executes")
        self.assertEqual(edge["target_key"], "tool:nix")
        self.assertEqual(edge["graph_key_version"], 1)
        self.assertEqual(edge["identity_metadata"], {})
        self.assertEqual(len(edge["identity_metadata_hash"]), 64)
        self.assertIn("metadata", edge)
        self.assertIn("first_seen_run_id", edge)
        self.assertIn("last_seen_run_id", edge)

        self.assertEqual(kind_exit_code, 0, kind_stderr)
        self.assertEqual(
            [record["edge_kind"] for record in json.loads(kind_stdout)],
            ["executes"],
        )

        self.assertEqual(source_exit_code, 0, source_stderr)
        self.assertEqual(
            [record["source_key"] for record in json.loads(source_stdout)],
            ["file:bin/tool"],
        )

        self.assertEqual(target_exit_code, 0, target_stderr)
        self.assertEqual(
            [record["target_key"] for record in json.loads(target_stdout)],
            ["tool:nix"],
        )

        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("source_key", text_stdout)
        self.assertIn("file:bin/tool", text_stdout)
        self.assertIn("identity_metadata_hash", text_stdout)
        self.assertIn(edge["identity_metadata_hash"], text_stdout)
        self.assertIn("last_seen_run_id", text_stdout)
        self.assertNotIn("commands", text_stdout)

    def test_storage_canonical_neighborhood_cli_reads_c2_loaded_rows(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

            def run_neighborhood(*extra_args):
                return run_repo_map_in_process(
                    "storage",
                    "canonical-neighborhood",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    *extra_args,
                )

            in_exit_code, in_stdout, in_stderr = run_neighborhood(
                "--node",
                "tool:nix",
                "--direction",
                "in",
                "--json",
            )
            out_exit_code, out_stdout, out_stderr = run_neighborhood(
                "--node",
                "file:bin/tool",
                "--direction",
                "out",
                "--json",
            )
            both_exit_code, both_stdout, both_stderr = run_neighborhood(
                "--node",
                "file:bin/tool",
                "--direction",
                "both",
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_neighborhood(
                "--node",
                "tool:nix",
                "--direction",
                "in",
            )
            missing_exit_code, missing_stdout, missing_stderr = run_neighborhood(
                "--node",
                "tool:missing",
                "--json",
            )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(in_exit_code, 0, in_stderr)
        in_payload = json.loads(in_stdout)
        self.assertEqual(in_payload["center"]["canonical_key"], "tool:nix")
        self.assertEqual(
            [record["canonical_key"] for record in in_payload["nodes"]],
            ["file:bin/tool"],
        )
        self.assertEqual(len(in_payload["edges"]), 1)
        self.assertEqual(in_payload["edges"][0]["source_key"], "file:bin/tool")
        self.assertEqual(in_payload["edges"][0]["edge_kind"], "executes")
        self.assertEqual(in_payload["edges"][0]["target_key"], "tool:nix")
        self.assertEqual(len(in_payload["edges"][0]["identity_metadata_hash"]), 64)

        self.assertEqual(out_exit_code, 0, out_stderr)
        out_payload = json.loads(out_stdout)
        self.assertEqual(out_payload["center"]["canonical_key"], "file:bin/tool")
        self.assertEqual(
            [record["canonical_key"] for record in out_payload["nodes"]],
            ["tool:nix"],
        )
        self.assertEqual([edge["target_key"] for edge in out_payload["edges"]], [
            "tool:nix",
        ])

        self.assertEqual(both_exit_code, 0, both_stderr)
        both_payload = json.loads(both_stdout)
        self.assertEqual(both_payload["center"]["canonical_key"], "file:bin/tool")
        self.assertEqual(
            [record["canonical_key"] for record in both_payload["nodes"]],
            ["tool:nix"],
        )
        self.assertEqual(len(both_payload["edges"]), 1)

        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("center: tool:nix", text_stdout)
        self.assertIn("Nodes:", text_stdout)
        self.assertIn("file:bin/tool", text_stdout)
        self.assertIn("Edges:", text_stdout)
        self.assertIn("identity_metadata_hash", text_stdout)
        self.assertIn(in_payload["edges"][0]["identity_metadata_hash"], text_stdout)
        self.assertNotIn("commands", text_stdout)

        self.assertEqual(missing_exit_code, 0, missing_stderr)
        self.assertEqual(
            json.loads(missing_stdout),
            {"center": None, "nodes": [], "edges": []},
        )

    def test_storage_canonical_neighborhood_cli_validates_arguments(self):
        invalid_key_exit, _invalid_key_stdout, invalid_key_stderr = (
            run_repo_map_in_process(
                "storage",
                "canonical-neighborhood",
                "--root-path",
                "/tmp/fixture",
                "--node",
                "tool:nix#line:12",
                "--json",
            )
        )
        version_exit, _version_stdout, version_stderr = run_repo_map_in_process(
            "storage",
            "canonical-neighborhood",
            "--root-path",
            "/tmp/fixture",
            "--node",
            "tool:nix",
            "--graph-key-version",
            "2",
            "--json",
        )
        depth_exit, _depth_stdout, depth_stderr = run_repo_map_in_process(
            "storage",
            "canonical-neighborhood",
            "--root-path",
            "/tmp/fixture",
            "--node",
            "tool:nix",
            "--depth",
            "2",
            "--json",
        )

        self.assertEqual(invalid_key_exit, 1)
        self.assertIn("invalid node canonical key", invalid_key_stderr)
        self.assertEqual(version_exit, 1)
        self.assertIn("unsupported graph key version", version_stderr)
        self.assertEqual(depth_exit, 1)
        self.assertIn("canonical-neighborhood only supports depth 1", depth_stderr)

    def test_storage_legacy_readback_commands_accept_canonical_mode(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:1:nix-build",
                path="bin/tool",
                start_line=1,
                end_line=1,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"], "command": "nix"},
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:2:nix-flake-check",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix flake check",
                target="tool:nix",
                confidence="manual",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "flake", "check"], "command": "nix"},
            ),
        ]

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as raw_jsonl:
            for observation in observations:
                raw_jsonl.write(observation.to_json_line())
            raw_jsonl.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                )
                load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                    "storage",
                    "load-files",
                    raw_jsonl.name,
                    "--repository-name",
                    "fixture",
                    *storage_args,
                    "--json",
                )
                legacy_nodes_exit, legacy_nodes_stdout, legacy_nodes_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--kind",
                        "shell.command",
                        "--json",
                    )
                )
                canonical_nodes_exit, canonical_nodes_stdout, canonical_nodes_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "nodes",
                        "--canonical",
                        *storage_args,
                        "--kind",
                        "file",
                        "--path-prefix",
                        "bin/",
                        "--json",
                    )
                )
                legacy_edges_exit, legacy_edges_stdout, legacy_edges_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        "shell.command",
                        "--json",
                    )
                )
                canonical_edges_exit, canonical_edges_stdout, canonical_edges_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        "--canonical",
                        *storage_args,
                        "--kind",
                        "executes",
                        "--source-key",
                        "file:bin/tool",
                        "--target-key",
                        "tool:nix",
                        "--json",
                    )
                )
                canonical_neighborhood_exit, canonical_neighborhood_stdout, (
                    canonical_neighborhood_stderr
                ) = run_repo_map_in_process(
                    "storage",
                    "neighborhood",
                    "--canonical",
                    *storage_args,
                    "--node",
                    "tool:nix",
                    "--direction",
                    "in",
                    "--json",
                )
                canonical_file_neighborhood_exit, canonical_file_neighborhood_stdout, (
                    canonical_file_neighborhood_stderr
                ) = run_repo_map_in_process(
                    "storage",
                    "file-neighborhood",
                    "--canonical",
                    *storage_args,
                    "--path",
                    "bin/tool",
                    "--direction",
                    "out",
                    "--json",
                )
                legacy_summary_exit, legacy_summary_stdout, legacy_summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "summary",
                        "--legacy",
                        *storage_args,
                        "--json",
                    )
                )
                default_summary_exit, default_summary_stdout, (
                    default_summary_stderr
                ) = run_repo_map_in_process(
                    "storage",
                    "summary",
                    *storage_args,
                    "--json",
                )
                canonical_summary_exit, canonical_summary_stdout, (
                    canonical_summary_stderr
                ) = run_repo_map_in_process(
                    "storage",
                    "summary",
                    "--canonical",
                    *storage_args,
                    "--json",
                )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(legacy_nodes_exit, 0, legacy_nodes_stderr)
        legacy_nodes = json.loads(legacy_nodes_stdout)
        self.assertIn("node_stable_key", legacy_nodes[0])
        self.assertNotIn("canonical_key", legacy_nodes[0])

        self.assertEqual(canonical_nodes_exit, 0, canonical_nodes_stderr)
        canonical_nodes = json.loads(canonical_nodes_stdout)
        self.assertEqual(
            [record["canonical_key"] for record in canonical_nodes],
            ["file:bin/tool"],
        )
        self.assertNotIn("id", canonical_nodes[0])
        self.assertNotIn("node_stable_key", canonical_nodes[0])

        self.assertEqual(legacy_edges_exit, 0, legacy_edges_stderr)
        legacy_edges = json.loads(legacy_edges_stdout)
        self.assertIn("edge_stable_key", legacy_edges[0])
        self.assertNotIn("source_key", legacy_edges[0])

        self.assertEqual(canonical_edges_exit, 0, canonical_edges_stderr)
        canonical_edges = json.loads(canonical_edges_stdout)
        self.assertEqual(len(canonical_edges), 1)
        self.assertEqual(canonical_edges[0]["source_key"], "file:bin/tool")
        self.assertEqual(canonical_edges[0]["edge_kind"], "executes")
        self.assertEqual(canonical_edges[0]["target_key"], "tool:nix")
        self.assertEqual(len(canonical_edges[0]["identity_metadata_hash"]), 64)
        self.assertNotIn("id", canonical_edges[0])
        self.assertNotIn("edge_stable_key", canonical_edges[0])

        self.assertEqual(
            canonical_neighborhood_exit,
            0,
            canonical_neighborhood_stderr,
        )
        canonical_neighborhood = json.loads(canonical_neighborhood_stdout)
        self.assertEqual(
            canonical_neighborhood["center"]["canonical_key"],
            "tool:nix",
        )
        self.assertEqual(len(canonical_neighborhood["edges"]), 1)

        self.assertEqual(
            canonical_file_neighborhood_exit,
            0,
            canonical_file_neighborhood_stderr,
        )
        canonical_file_neighborhood = json.loads(canonical_file_neighborhood_stdout)
        self.assertEqual(
            canonical_file_neighborhood["center"]["canonical_key"],
            "file:bin/tool",
        )
        self.assertEqual(
            [edge["target_key"] for edge in canonical_file_neighborhood["edges"]],
            ["tool:nix"],
        )

        self.assertEqual(legacy_summary_exit, 0, legacy_summary_stderr)
        legacy_summary = json.loads(legacy_summary_stdout)
        self.assertIn("nodes", legacy_summary)
        self.assertIn("edges", legacy_summary)
        self.assertNotIn("canonical_nodes", legacy_summary)

        self.assertEqual(default_summary_exit, 0, default_summary_stderr)
        default_summary = json.loads(default_summary_stdout)
        self.assertNotIn("nodes", default_summary)
        self.assertNotIn("repository_id", default_summary)

        self.assertEqual(canonical_summary_exit, 0, canonical_summary_stderr)
        canonical_summary = json.loads(canonical_summary_stdout)
        self.assertEqual(default_summary, canonical_summary)
        self.assertEqual(canonical_summary["root_path"], "/tmp/fixture")
        self.assertEqual(canonical_summary["repository_name"], "fixture")
        self.assertEqual(canonical_summary["runs"], 1)
        self.assertEqual(canonical_summary["raw_observations"], 3)
        self.assertEqual(canonical_summary["canonical_nodes"], 2)
        self.assertEqual(canonical_summary["canonical_edges"], 1)
        self.assertEqual(canonical_summary["canonical_evidence"], 3)
        self.assertIn("legacy_nodes", canonical_summary)
        self.assertIn("legacy_edges", canonical_summary)
        self.assertIn("legacy_evidence", canonical_summary)
        self.assertNotIn("repository_id", canonical_summary)

    def test_storage_legacy_readback_canonical_mode_validates_arguments(self):
        bad_node_exit, _bad_node_stdout, bad_node_stderr = run_repo_map_in_process(
            "storage",
            "nodes",
            "--canonical",
            "--root-path",
            "/tmp/fixture",
            "--canonical-key",
            "file:bin/tool#line:12",
            "--json",
        )
        bad_edge_exit, _bad_edge_stdout, bad_edge_stderr = run_repo_map_in_process(
            "storage",
            "edges",
            "--canonical",
            "--root-path",
            "/tmp/fixture",
            "--source-key",
            "file:bin/tool#line:12",
            "--json",
        )
        bad_version_exit, _bad_version_stdout, bad_version_stderr = (
            run_repo_map_in_process(
                "storage",
                "neighborhood",
                "--canonical",
                "--root-path",
                "/tmp/fixture",
                "--node",
                "tool:nix",
                "--graph-key-version",
                "2",
                "--json",
            )
        )

        self.assertEqual(bad_node_exit, 1)
        self.assertIn("invalid canonical key", bad_node_stderr)
        self.assertEqual(bad_edge_exit, 1)
        self.assertIn("invalid source canonical key", bad_edge_stderr)
        self.assertEqual(bad_version_exit, 1)
        self.assertIn("unsupported graph key version", bad_version_stderr)

    def test_storage_explain_canonical_edge_cli_reads_c2_loaded_evidence(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

            def run_explain(*extra_args):
                return run_repo_map_in_process(
                    "storage",
                    "explain-canonical-edge",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:bin/tool",
                    "--kind",
                    "executes",
                    "--target-key",
                    "tool:nix",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    *extra_args,
                )

            json_exit_code, json_stdout, json_stderr = run_explain("--json")
            text_exit_code, text_stdout, text_stderr = run_explain()
            missing_exit_code, missing_stdout, missing_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "explain-canonical-edge",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:bin/tool",
                    "--kind",
                    "executes",
                    "--target-key",
                    "tool:missing",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(json_exit_code, 0, json_stderr)
        payload = json.loads(json_stdout)
        self.assertEqual(payload["edge"]["source_key"], "file:bin/tool")
        self.assertEqual(payload["edge"]["edge_kind"], "executes")
        self.assertEqual(payload["edge"]["target_key"], "tool:nix")
        self.assertEqual(payload["edge"]["graph_key_version"], 1)
        self.assertEqual(payload["edge"]["identity_metadata"], {})
        self.assertEqual(len(payload["edge"]["identity_metadata_hash"]), 64)
        self.assertEqual(len(payload["evidence"]), 2)
        self.assertEqual(
            [record["raw_observation"]["ordinal"] for record in payload["evidence"]],
            [0, 1],
        )
        self.assertEqual(
            [record["raw_observation"]["kind"] for record in payload["evidence"]],
            ["shell.command", "shell.command"],
        )
        self.assertTrue(
            all(
                len(record["raw_observation"]["payload_hash"]) == 64
                for record in payload["evidence"]
            )
        )
        self.assertEqual(
            [record["path"] for record in payload["evidence"]],
            ["bin/tool", "bin/tool"],
        )
        self.assertEqual(
            [record["extractor"] for record in payload["evidence"]],
            ["repo-shell", "repo-shell"],
        )

        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("edge:", text_stdout)
        self.assertIn("identity_metadata_hash", text_stdout)
        self.assertIn(payload["edge"]["identity_metadata_hash"], text_stdout)
        self.assertIn("evidence:", text_stdout)
        self.assertIn("raw_observation.ordinal", text_stdout)
        self.assertIn("repo-shell", text_stdout)

        self.assertEqual(missing_exit_code, 0, missing_stderr)
        self.assertEqual(
            json.loads(missing_stdout),
            {"edge": None, "evidence": []},
        )

    def test_storage_loads_python_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("python_package")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "python-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                nodes_exit_code, nodes_stdout, nodes_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "canonical-nodes",
                        *storage_args,
                        "--json",
                    )
                )
                imports_exit_code, imports_stdout, imports_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "canonical-edges",
                        *storage_args,
                        "--kind",
                        "imports",
                        "--source-key",
                        "python.module:pkg.app",
                        "--json",
                    )
                )
                public_imports_exit, public_imports_stdout, (
                    public_imports_stderr
                ) = run_repo_map_in_process(
                    "storage",
                    "edges",
                    "--canonical",
                    *storage_args,
                    "--kind",
                    "imports",
                    "--source-key",
                    "python.module:pkg.app",
                    "--json",
                )
                explain_exit_code, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "python.module:pkg.app",
                        "--kind",
                        "imports",
                        "--target-key",
                        "python.module:pkg.lib.helper",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "file",
                "python.module",
                "python.import",
                "python.class",
                "python.function",
                "python.method",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(nodes_exit_code, 0, nodes_stderr)
        node_keys = {
            record["canonical_key"]
            for record in json.loads(nodes_stdout)
        }
        self.assertTrue(
            {
                "file:src/main/python/pkg/app.py",
                "file:src/main/python/pkg/lib/helper.py",
                "python.module:pkg.app",
                "python.module:pkg.lib.helper",
                "python.class:pkg.app:Service",
                "python.function:pkg.app:build",
                "python.method:pkg.app:Service:run",
                "external:python.module:json",
                "unknown:python.module:missing-module",
            }.issubset(node_keys)
        )

        self.assertEqual(imports_exit_code, 0, imports_stderr)
        import_edges = json.loads(imports_stdout)
        self.assertEqual(
            [record["target_key"] for record in import_edges],
            [
                "external:python.module:json",
                "python.module:pkg.lib.helper",
                "unknown:python.module:missing-module",
            ],
        )
        self.assertTrue(
            all(
                record["source_key"] == "python.module:pkg.app"
                for record in import_edges
            )
        )
        self.assertEqual(public_imports_exit, 0, public_imports_stderr)
        self.assertEqual(json.loads(public_imports_stdout), import_edges)

        self.assertEqual(explain_exit_code, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["source_key"], "python.module:pkg.app")
        self.assertEqual(explanation["edge"]["edge_kind"], "imports")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "python.module:pkg.lib.helper",
        )
        self.assertEqual(len(explanation["evidence"]), 1)
        evidence = explanation["evidence"][0]
        self.assertEqual(evidence["raw_observation"]["kind"], "python.import")
        self.assertEqual(
            evidence["path"],
            "src/main/python/pkg/app.py",
        )
        self.assertEqual(evidence["start_line"], 1)

    def test_storage_loads_nix_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("nix_flake_basic")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "nix-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_nodes(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "canonical-nodes",
                        *storage_args,
                        "--kind",
                        kind,
                        "--json",
                    )

                app_exit, app_stdout, app_stderr = canonical_nodes("nix.app")
                package_exit, package_stdout, package_stderr = canonical_nodes(
                    "nix.package"
                )
                dev_shell_exit, dev_shell_stdout, dev_shell_stderr = (
                    canonical_nodes("nix.devShell")
                )
                check_exit, check_stdout, check_stderr = canonical_nodes("nix.check")

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "canonical-edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--json",
                    )

                sources_exit, sources_stdout, sources_stderr = canonical_edges(
                    "sources"
                )
                defines_exit, defines_stdout, defines_stderr = canonical_edges(
                    "defines"
                )
                exposes_exit, exposes_stdout, exposes_stderr = canonical_edges(
                    "exposes_script"
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "nix.app:nix_flake_basic:aarch64-darwin:tool",
                        "--kind",
                        "exposes_script",
                        "--target-key",
                        "file:bin/tool",
                        "--json",
                    )
                )
                raw_path_refs = postgres.psql_scalar(
                    "SELECT count(*) FROM raw_observations "
                    "WHERE payload_json ->> 'kind' = 'nix.path_ref';"
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "nix.import",
                "nix.app",
                "nix.package",
                "nix.devShell",
                "nix.check",
                "nix.path_ref",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(app_exit, 0, app_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(app_stdout)],
            ["nix.app:nix_flake_basic:aarch64-darwin:tool"],
        )
        self.assertEqual(package_exit, 0, package_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(package_stdout)],
            ["nix.package:nix_flake_basic:aarch64-darwin:default"],
        )
        self.assertEqual(dev_shell_exit, 0, dev_shell_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(dev_shell_stdout)],
            ["nix.devShell:nix_flake_basic:aarch64-darwin:default"],
        )
        self.assertEqual(check_exit, 0, check_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(check_stdout)],
            ["nix.check:nix_flake_basic:aarch64-darwin:unit"],
        )

        self.assertEqual(sources_exit, 0, sources_stderr)
        self.assertIn(
            ("file:flake.nix", "file:modules/base.nix"),
            {
                (record["source_key"], record["target_key"])
                for record in json.loads(sources_stdout)
            },
        )
        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertTrue(
            {
                "nix.app:nix_flake_basic:aarch64-darwin:tool",
                "nix.package:nix_flake_basic:aarch64-darwin:default",
                "nix.devShell:nix_flake_basic:aarch64-darwin:default",
                "nix.check:nix_flake_basic:aarch64-darwin:unit",
            }.issubset(define_targets)
        )
        self.assertEqual(exposes_exit, 0, exposes_stderr)
        self.assertEqual(
            [
                (record["source_key"], record["target_key"])
                for record in json.loads(exposes_stdout)
            ],
            [("nix.app:nix_flake_basic:aarch64-darwin:tool", "file:bin/tool")],
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(
            explanation["edge"]["source_key"],
            "nix.app:nix_flake_basic:aarch64-darwin:tool",
        )
        self.assertEqual(explanation["edge"]["edge_kind"], "exposes_script")
        self.assertEqual(explanation["edge"]["target_key"], "file:bin/tool")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "nix.app",
        )
        self.assertEqual(raw_path_refs, "2")

    def test_storage_loads_markdown_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("markdown_docs_basic")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "markdown-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_nodes(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "canonical-nodes",
                        *storage_args,
                        "--kind",
                        kind,
                        "--json",
                    )

                page_exit, page_stdout, page_stderr = canonical_nodes("doc.page")
                section_exit, section_stdout, section_stderr = canonical_nodes(
                    "doc.section"
                )
                adr_exit, adr_stdout, adr_stderr = canonical_nodes("doc.adr")
                skill_exit, skill_stdout, skill_stderr = canonical_nodes("doc.skill")

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "canonical-edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--json",
                    )

                defines_exit, defines_stdout, defines_stderr = canonical_edges(
                    "defines"
                )
                links_exit, links_stdout, links_stderr = canonical_edges("links_to")
                public_links_exit, public_links_stdout, public_links_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        "--canonical",
                        *storage_args,
                        "--kind",
                        "links_to",
                        "--json",
                    )
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "doc.section:file%3AREADME.md:docs-fixture",
                        "--kind",
                        "links_to",
                        "--target-key",
                        "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "markdown.document",
                "markdown.heading",
                "markdown.link",
                "markdown.frontmatter",
                "markdown.code_fence",
                "markdown.adr_metadata",
                "markdown.skill_metadata",
            }.issubset(discovered_kinds)
        )
        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(page_exit, 0, page_stderr)
        page_keys = {record["canonical_key"] for record in json.loads(page_stdout)}
        self.assertTrue(
            {
                "doc.page:file%3AREADME.md",
                "doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
                "doc.page:file%3Adocs%2Fskills%2Fexample%2FSKILL.md",
                "doc.page:file%3AAGENTS.md",
            }.issubset(page_keys)
        )
        self.assertEqual(section_exit, 0, section_stderr)
        self.assertIn(
            "doc.section:file%3AREADME.md:docs-fixture",
            {record["canonical_key"] for record in json.loads(section_stdout)},
        )
        self.assertEqual(adr_exit, 0, adr_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(adr_stdout)],
            ["doc.adr:0008"],
        )
        self.assertEqual(skill_exit, 0, skill_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(skill_stdout)],
            ["doc.skill:example"],
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("doc.page:file%3AREADME.md", define_targets)
        self.assertIn("doc.adr:0008", define_targets)
        self.assertIn("doc.skill:example", define_targets)

        self.assertEqual(links_exit, 0, links_stderr)
        link_edges = json.loads(links_stdout)
        self.assertEqual(public_links_exit, 0, public_links_stderr)
        self.assertEqual(json.loads(public_links_stdout), link_edges)
        self.assertIn(
            (
                "doc.section:file%3AREADME.md:docs-fixture",
                "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
            ),
            {
                (record["source_key"], record["target_key"])
                for record in link_edges
            },
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {record["target_key"] for record in link_edges},
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "links_to")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "markdown.link",
        )

    def test_mcp_read_only_tools_read_python_canonical_graph(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "python_package",
            "raw_observations.jsonl",
        )
        from repomap_kg.mcp_server import (
            handle_jsonrpc_message,
            repomap_canonical_edges,
            repomap_canonical_neighborhood,
            repomap_canonical_nodes,
            repomap_explain_canonical_edge,
            repomap_projects,
            repomap_status,
            serve_stdio,
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            mcp_args = {
                "root_path": "/tmp/fixture",
                "pg_host": str(postgres.socket_dir),
                "pg_port": str(postgres.port),
                "pg_user": postgres.user,
                "pg_database": "postgres",
                "psql_command": postgres.psql_command,
            }
            jsonrpc_args = {
                key: value
                for key, value in mcp_args.items()
                if key != "psql_command"
            }
            status = repomap_status(**mcp_args)
            modules = repomap_canonical_nodes(**mcp_args, kind="python.module")
            imports = repomap_canonical_edges(
                **mcp_args,
                kind="imports",
                source_key="python.module:pkg.app",
            )
            explanation = repomap_explain_canonical_edge(
                **mcp_args,
                source_key="python.module:pkg.app",
                kind="imports",
                target_key="python.module:pkg.lib.helper",
                identity_metadata={},
            )
            neighborhood = repomap_canonical_neighborhood(
                **mcp_args,
                node="python.module:pkg.app",
                direction="out",
            )
            with tempfile.TemporaryDirectory() as mcp_config_tmpdir:
                mcp_config_path = Path(mcp_config_tmpdir) / "config.json"
                mcp_config_path.write_text(
                    json.dumps(
                        {
                            "default_project": "fixture",
                            "projects": {
                                "fixture": {
                                    "root_path": "/tmp/fixture",
                                    "pg_host": str(postgres.socket_dir),
                                    "pg_port": str(postgres.port),
                                    "pg_user": postgres.user,
                                    "pg_database": "postgres",
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                with patch.dict(
                    "os.environ",
                    {
                        "REPOMAP_MCP_CONFIG": str(mcp_config_path),
                        "REPOMAP_PSQL_COMMAND": postgres.psql_command,
                    },
                    clear=False,
                ):
                    projects_payload = repomap_projects()
                    project_status = repomap_status()
                    project_modules = repomap_canonical_nodes(
                        project="fixture",
                        kind="python.module",
                    )
                    project_imports = repomap_canonical_edges(
                        project="fixture",
                        kind="imports",
                        source_key="python.module:pkg.app",
                    )
                    project_explanation = repomap_explain_canonical_edge(
                        project="fixture",
                        source_key="python.module:pkg.app",
                        kind="imports",
                        target_key="python.module:pkg.lib.helper",
                        identity_metadata={},
                    )
                    project_neighborhood = repomap_canonical_neighborhood(
                        project="fixture",
                        node="python.module:pkg.app",
                        direction="out",
                    )
                    jsonrpc_project_status = handle_jsonrpc_message(
                        {
                            "jsonrpc": "2.0",
                            "id": 13,
                            "method": "tools/call",
                            "params": {
                                "name": "repomap_status",
                                "arguments": {},
                            },
                        }
                    )
                    jsonrpc_project_modules = handle_jsonrpc_message(
                        {
                            "jsonrpc": "2.0",
                            "id": 14,
                            "method": "tools/call",
                            "params": {
                                "name": "repomap_canonical_nodes",
                                "arguments": {
                                    "project": "fixture",
                                    "kind": "python.module",
                                },
                            },
                        }
                    )
            initialize_response = handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
            )
            tools_response = handle_jsonrpc_message(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
            )
            with patch.dict(
                "os.environ",
                {"REPOMAP_PSQL_COMMAND": postgres.psql_command},
                clear=False,
            ):
                jsonrpc_status = handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "repomap_status",
                            "arguments": jsonrpc_args,
                        },
                    }
                )
                jsonrpc_modules = handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "repomap_canonical_nodes",
                            "arguments": {**jsonrpc_args, "kind": "python.module"},
                        },
                    }
                )
                jsonrpc_imports = handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "tools/call",
                        "params": {
                            "name": "repomap_canonical_edges",
                            "arguments": {
                                **jsonrpc_args,
                                "kind": "imports",
                                "source_key": "python.module:pkg.app",
                            },
                        },
                    }
                )
                jsonrpc_explanation = handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "tools/call",
                        "params": {
                            "name": "repomap_explain_canonical_edge",
                            "arguments": {
                                **jsonrpc_args,
                                "source_key": "python.module:pkg.app",
                                "kind": "imports",
                                "target_key": "python.module:pkg.lib.helper",
                                "identity_metadata": {},
                            },
                        },
                    }
                )
                jsonrpc_neighborhood = handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {
                            "name": "repomap_canonical_neighborhood",
                            "arguments": {
                                **jsonrpc_args,
                                "node": "python.module:pkg.app",
                                "direction": "out",
                            },
                        },
                    }
                )
                jsonrpc_missing = handle_jsonrpc_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 8,
                        "method": "tools/call",
                        "params": {
                            "name": "repomap_missing",
                            "arguments": jsonrpc_args,
                        },
                    }
                )
            stdio_output = StringIO()
            serve_stdio(
                input_stream=StringIO(
                    "\n"
                    '{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n'
                    '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                    '[]\n'
                ),
                output_stream=stdio_output,
            )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertTrue(status["read_only"])
        self.assertEqual(status["repository_name"], "fixture")
        self.assertEqual(status["graph_key_version"], 1)
        self.assertGreaterEqual(status["counts"]["nodes"], 8)
        self.assertNotIn("repository_id", status)

        self.assertEqual(
            [record["canonical_key"] for record in modules],
            ["python.module:pkg.app", "python.module:pkg.lib.helper"],
        )

        self.assertEqual(
            [record["target_key"] for record in imports],
            [
                "external:python.module:json",
                "python.module:pkg.lib.helper",
                "unknown:python.module:missing-module",
            ],
        )
        self.assertTrue(
            all(record["edge_kind"] == "imports" for record in imports)
        )

        self.assertEqual(
            explanation["edge"]["target_key"],
            "python.module:pkg.lib.helper",
        )
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "python.import",
        )

        self.assertEqual(
            neighborhood["center"]["canonical_key"],
            "python.module:pkg.app",
        )
        self.assertEqual(
            [record["target_key"] for record in neighborhood["edges"]],
            [
                "external:python.module:json",
                "python.module:pkg.lib.helper",
                "unknown:python.module:missing-module",
            ],
        )

        self.assertEqual(
            initialize_response["result"]["serverInfo"]["name"],
            "repomap-kg",
        )
        self.assertEqual(
            [tool["name"] for tool in tools_response["result"]["tools"]],
            [
                "repomap_status",
                "repomap_projects",
                "repomap_canonical_nodes",
                "repomap_canonical_edges",
                "repomap_explain_canonical_edge",
                "repomap_canonical_neighborhood",
            ],
        )
        self.assertEqual(projects_payload["default_project"], "fixture")
        self.assertEqual(
            projects_payload["projects"],
            [
                {
                    "name": "fixture",
                    "default": True,
                    "root_path": "/tmp/fixture",
                    "pg_database": "postgres",
                    "pg_host": str(postgres.socket_dir),
                    "pg_port": str(postgres.port),
                    "pg_user": postgres.user,
                }
            ],
        )
        self.assertEqual(project_status["project"], "fixture")
        self.assertEqual(project_status["repository_name"], "fixture")
        self.assertEqual(
            [record["canonical_key"] for record in project_modules],
            ["python.module:pkg.app", "python.module:pkg.lib.helper"],
        )
        self.assertEqual(
            [record["target_key"] for record in project_imports],
            [
                "external:python.module:json",
                "python.module:pkg.lib.helper",
                "unknown:python.module:missing-module",
            ],
        )
        self.assertEqual(
            project_explanation["edge"]["target_key"],
            "python.module:pkg.lib.helper",
        )
        self.assertEqual(
            project_neighborhood["center"]["canonical_key"],
            "python.module:pkg.app",
        )
        self.assertEqual(
            jsonrpc_project_status["result"]["structuredContent"]["project"],
            "fixture",
        )
        self.assertEqual(
            [
                record["canonical_key"]
                for record in jsonrpc_project_modules["result"]["structuredContent"]
            ],
            ["python.module:pkg.app", "python.module:pkg.lib.helper"],
        )
        self.assertEqual(
            jsonrpc_status["result"]["structuredContent"]["repository_name"],
            "fixture",
        )
        self.assertEqual(
            [
                record["canonical_key"]
                for record in jsonrpc_modules["result"]["structuredContent"]
            ],
            ["python.module:pkg.app", "python.module:pkg.lib.helper"],
        )
        self.assertEqual(
            [
                record["target_key"]
                for record in jsonrpc_imports["result"]["structuredContent"]
            ],
            [
                "external:python.module:json",
                "python.module:pkg.lib.helper",
                "unknown:python.module:missing-module",
            ],
        )
        self.assertEqual(
            jsonrpc_explanation["result"]["structuredContent"]["edge"]["target_key"],
            "python.module:pkg.lib.helper",
        )
        self.assertEqual(
            jsonrpc_neighborhood["result"]["structuredContent"]["center"][
                "canonical_key"
            ],
            "python.module:pkg.app",
        )
        self.assertTrue(jsonrpc_missing["result"]["isError"])
        stdio_lines = stdio_output.getvalue().splitlines()
        self.assertEqual(len(stdio_lines), 2)
        self.assertEqual(
            json.loads(stdio_lines[0])["result"]["tools"][0]["name"],
            "repomap_status",
        )
        self.assertEqual(json.loads(stdio_lines[1])["error"]["code"], -32700)

    def test_storage_load_files_retains_unsupported_future_observation(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "unsupported_kind",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            counts = postgres.psql_scalar(
                """
SELECT (SELECT count(*) FROM raw_observations)::text
       || '|'
       || (SELECT count(*) FROM canonical_nodes)::text
       || '|'
       || (SELECT count(*) FROM canonical_edges)::text
       || '|'
       || (SELECT count(*) FROM canonical_evidence)::text;
"""
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(set(payload), {"files", "repository_id", "run_id"})
        self.assertEqual(payload["files"], 0)
        self.assertEqual(counts, "1|0|0|0")

    def test_storage_load_files_canonical_failure_rolls_back_legacy_rows(self):
        require_postgres_binaries()
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "e" * 64,
                "generated": False,
                "executable": False,
            },
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            postgres.psql_scalar(
                """
CREATE OR REPLACE FUNCTION fail_canonical_node_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'simulated canonical failure';
END;
$$;
CREATE TRIGGER fail_canonical_nodes
BEFORE INSERT ON canonical_nodes
FOR EACH ROW EXECUTE FUNCTION fail_canonical_node_insert();
SELECT 'ok';
"""
            )

            with self.assertRaisesRegex(StorageSchemaError, "simulated canonical failure"):
                load_file_observations(
                    postgres.psql_args,
                    [observation],
                    repository_name="fixture",
                    root_path="/tmp/fixture",
                    psql_command=postgres.psql_command,
                )

            counts = postgres.psql_scalar(
                """
SELECT (SELECT count(*) FROM repositories)::text
       || '|'
       || (SELECT count(*) FROM runs)::text
       || '|'
       || (SELECT count(*) FROM files)::text
       || '|'
       || (SELECT count(*) FROM nodes)::text
       || '|'
       || (SELECT count(*) FROM evidence)::text
       || '|'
       || (SELECT count(*) FROM raw_observations)::text
       || '|'
       || (SELECT count(*) FROM canonical_nodes)::text;
"""
            )

        self.assertEqual(counts, "0|0|0|0|0|0|0")

    def test_storage_load_canonical_cli_loads_shell_collapse_fixture(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "shell_executes_collapse",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-canonical",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            counts = postgres.psql_scalar(
                """
SELECT (SELECT count(*) FROM raw_observations)::text
       || '|'
       || (SELECT count(*) FROM canonical_edges)::text
       || '|'
       || (SELECT count(*) FROM canonical_edge_evidence)::text
       || '|'
       || (SELECT count(*) FROM nodes)::text
       || '|'
       || (SELECT count(*) FROM edges)::text
       || '|'
       || (SELECT count(*) FROM evidence)::text;
"""
            )
            edge_row = postgres.psql_scalar(
                """
SELECT source_canonical_key
       || '|'
       || edge_kind
       || '|'
       || target_canonical_key
FROM canonical_edges;
"""
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["raw_observations"], 2)
        self.assertEqual(payload["canonical_edges"], 1)
        self.assertEqual(payload["canonical_edge_evidence_links"], 2)
        self.assertEqual(counts, "2|1|2|0|0|0")
        self.assertEqual(edge_row, "file:bin/tool|executes|tool:nix")

    def test_storage_load_canonical_retains_unsupported_future_observation(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "unsupported_kind",
            "raw_observations.jsonl",
        )

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-canonical",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            counts = postgres.psql_scalar(
                """
SELECT (SELECT count(*) FROM raw_observations)::text
       || '|'
       || (SELECT count(*) FROM canonical_nodes)::text
       || '|'
       || (SELECT count(*) FROM canonical_edges)::text
       || '|'
       || (SELECT count(*) FROM canonical_evidence)::text;
"""
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["raw_observations"], 1)
        self.assertEqual(payload["canonical_nodes"], 0)
        self.assertEqual(payload["canonical_edges"], 0)
        self.assertEqual(counts, "1|0|0|0")

    def test_storage_load_canonical_cli_loads_golden_fixture_matrix(self):
        require_postgres_binaries()
        fixture_names = [
            "files_basic",
            "files_conflict",
            "malformed_target_placeholder",
            "malformed_target_rebuilt",
            "shell_env_missing_variable",
            "shell_env_read",
            "shell_env_write",
            "shell_env_write_collapse",
            "shell_executes_nix",
            "shell_host_mutation_package",
            "shell_source_dynamic",
            "shell_source_repo_escape",
            "shell_source_static",
            "unsupported_kind",
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            for fixture_name in fixture_names:
                with self.subTest(fixture_name=fixture_name):
                    raw_jsonl = canonicalization_fixture(
                        fixture_name,
                        "raw_observations.jsonl",
                    )
                    exit_code, stdout, stderr = run_repo_map_in_process(
                        "storage",
                        "load-canonical",
                        str(raw_jsonl),
                        "--repository-name",
                        f"fixture-{fixture_name}",
                        "--root-path",
                        f"/tmp/fixture/{fixture_name}",
                        "--pg-host",
                        str(postgres.socket_dir),
                        "--pg-port",
                        str(postgres.port),
                        "--pg-user",
                        postgres.user,
                        "--pg-database",
                        "postgres",
                        "--psql-command",
                        postgres.psql_command,
                        "--json",
                    )

                    self.assertEqual(exit_code, 0, stderr)
                    payload = json.loads(stdout)
                    self.assertGreater(payload["raw_observations"], 0)

            counts = postgres.psql_scalar(
                """
SELECT (SELECT count(*) FROM raw_observations)::text
       || '|'
       || (SELECT count(*) FROM canonical_nodes)::text
       || '|'
       || (SELECT count(*) FROM canonical_edges)::text
       || '|'
       || (SELECT count(*) FROM canonical_evidence)::text;
"""
            )

        self.assertEqual(counts, "16|24|11|15")

    def test_storage_files_cli_reads_loaded_file_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="generated/report.json",
                path="generated/report.json",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "json",
                    "role": "generated",
                    "content_hash": "a" * 64,
                    "generated": True,
                    "executable": False,
                },
            ),
            RawObservation(
                kind="file",
                source_id="src/main/python/app.py",
                path="src/main/python/app.py",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "python",
                    "role": "source",
                    "content_hash": "b" * 64,
                    "generated": False,
                    "executable": False,
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "files",
                "--root-path",
                "/tmp/fixture",
                "--role",
                "source",
                "--language",
                "python",
                "--generated",
                "exclude",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            payload,
            [
                {
                    "path": "src/main/python/app.py",
                    "language": "python",
                    "role": "source",
                    "confidence": "manual",
                    "generated": False,
                    "executable": False,
                }
            ],
        )

    def test_storage_files_cli_reports_psql_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            failing_psql = Path(tmpdir) / "psql"
            failing_psql.write_text(
                "#!/bin/sh\n"
                "echo connection refused >&2\n"
                "exit 2\n"
            )
            failing_psql.chmod(0o755)

            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "files",
                "--root-path",
                "/tmp/fixture",
                "--psql-command",
                str(failing_psql),
                "--json",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("connection refused", stderr)

    def test_storage_load_files_cli_reports_bad_summary_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            raw_jsonl.write_text("")
            bad_json_psql = Path(tmpdir) / "psql"
            bad_json_psql.write_text(
                "#!/bin/sh\n"
                "echo '{bad json}'\n"
                "exit 0\n"
            )
            bad_json_psql.chmod(0o755)

            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--psql-command",
                str(bad_json_psql),
                "--json",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("load summary", stderr)

    def test_storage_entrypoints_cli_reads_loaded_entrypoint_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="file",
                source_id="scripts/helper.sh",
                path="scripts/helper.sh",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "d" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "entrypoints",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual([record["path"] for record in payload], ["bin/tool"])
        self.assertTrue(payload[0]["executable"])

    def test_storage_file_nodes_cli_reads_loaded_graph_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "markdown",
                    "role": "documentation",
                    "content_hash": "d" * 64,
                    "generated": False,
                    "executable": False,
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "file-nodes",
                "--root-path",
                "/tmp/fixture",
                "--path",
                "bin/tool",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                "storage",
                "file-nodes",
                "--root-path",
                "/tmp/fixture",
                "--path",
                "README.md",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            [record["path"] for record in payload],
            ["bin/tool"],
        )
        self.assertEqual(payload[0]["node_kind"], "file")
        self.assertEqual(payload[0]["node_stable_key"], "node:bin/tool:file:bin/tool")
        self.assertEqual(
            payload[0]["evidence_stable_key"],
            "evidence:bin/tool:0-0:fixture-discovery:bin/tool",
        )
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("node_stable_key", text_stdout)
        self.assertIn("README.md", text_stdout)
        self.assertNotIn("bin/tool", text_stdout)

    def test_storage_nodes_cli_reads_loaded_graph_nodes(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="python.import",
                source_id="bin/tool#import:json",
                path="bin/tool",
                start_line=3,
                end_line=3,
                name="json",
                target="module:json",
                confidence="heuristic",
                extractor="fixture-python",
                extractor_version="0.1.0",
                metadata={"module": "json"},
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "nodes",
                "--root-path",
                "/tmp/fixture",
                "--kind",
                "shell.command",
                "--path",
                "bin/tool",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                "storage",
                "nodes",
                "--root-path",
                "/tmp/fixture",
                "--stable-key",
                "tool:nix",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["path"], "bin/tool")
        self.assertEqual(payload[0]["node_kind"], "shell.command")
        self.assertEqual(
            payload[0]["node_stable_key"],
            "node:bin/tool:shell.command:bin/tool#call:nix-build",
        )
        self.assertEqual(payload[0]["start_line"], 2)
        self.assertEqual(payload[0]["end_line"], 2)
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("node_stable_key", text_stdout)
        self.assertIn("tool:nix", text_stdout)
        self.assertIn("tool", text_stdout)
        self.assertNotIn("module:json", text_stdout)

    def test_storage_neighborhood_cli_reads_depth_one_graph(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="python.import",
                source_id="bin/tool#import:json",
                path="bin/tool",
                start_line=3,
                end_line=3,
                name="json",
                target="module:json",
                confidence="heuristic",
                extractor="fixture-python",
                extractor_version="0.1.0",
                metadata={"module": "json"},
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "neighborhood",
                "--root-path",
                "/tmp/fixture",
                "--node",
                "tool:nix",
                "--direction",
                "in",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                "storage",
                "neighborhood",
                "--root-path",
                "/tmp/fixture",
                "--node",
                "node:bin/tool:python.import:bin/tool#import:json",
                "--direction",
                "out",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["center"]["node_stable_key"], "tool:nix")
        self.assertEqual(
            {
                node["node_stable_key"]
                for node in payload["nodes"]
            },
            {
                "tool:nix",
                "node:bin/tool:shell.command:bin/tool#call:nix-build",
            },
        )
        self.assertEqual(len(payload["edges"]), 1)
        self.assertEqual(payload["edges"][0]["edge_kind"], "shell.command")
        self.assertEqual(payload["edges"][0]["dst_node_stable_key"], "tool:nix")
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("center_node_stable_key", text_stdout)
        self.assertIn("module:json", text_stdout)
        self.assertIn("python.import", text_stdout)
        self.assertNotIn("tool:nix", text_stdout)

    def test_storage_file_neighborhood_cli_reads_path_graph(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="python.import",
                source_id="bin/tool#import:json",
                path="bin/tool",
                start_line=3,
                end_line=3,
                name="json",
                target="module:json",
                confidence="heuristic",
                extractor="fixture-python",
                extractor_version="0.1.0",
                metadata={"module": "json"},
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "file-neighborhood",
                "--root-path",
                "/tmp/fixture",
                "--path",
                "bin/tool",
                "--direction",
                "out",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                "storage",
                "file-neighborhood",
                "--root-path",
                "/tmp/fixture",
                "--path",
                "bin/tool",
                "--direction",
                "out",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["path"], "bin/tool")
        self.assertEqual(
            {
                node["node_stable_key"]
                for node in payload["centers"]
            },
            {
                "node:bin/tool:file:bin/tool",
                "node:bin/tool:shell.command:bin/tool#call:nix-build",
                "node:bin/tool:python.import:bin/tool#import:json",
            },
        )
        self.assertEqual(
            {
                edge["dst_node_stable_key"]
                for edge in payload["edges"]
            },
            {"tool:nix", "module:json"},
        )
        self.assertEqual(
            {
                node["node_stable_key"]
                for node in payload["nodes"]
            },
            {
                "node:bin/tool:file:bin/tool",
                "node:bin/tool:shell.command:bin/tool#call:nix-build",
                "node:bin/tool:python.import:bin/tool#import:json",
                "tool:nix",
                "module:json",
            },
        )
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("file_path: bin/tool", text_stdout)
        self.assertIn("center_nodes: 3", text_stdout)
        self.assertIn("tool:nix", text_stdout)
        self.assertIn("module:json", text_stdout)

    def test_storage_edges_cli_reads_loaded_relationship_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="python.import",
                source_id="bin/tool#import:json",
                path="bin/tool",
                start_line=3,
                end_line=3,
                name="json",
                target="module:json",
                confidence="heuristic",
                extractor="fixture-python",
                extractor_version="0.1.0",
                metadata={"module": "json"},
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "edges",
                "--root-path",
                "/tmp/fixture",
                "--kind",
                "shell.command",
                "--target-node",
                "tool:nix",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                "storage",
                "edges",
                "--root-path",
                "/tmp/fixture",
                "--kind",
                "python.import",
                "--source-node",
                "node:bin/tool:python.import:bin/tool#import:json",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["path"], "bin/tool")
        self.assertEqual(payload[0]["edge_kind"], "shell.command")
        self.assertEqual(payload[0]["dst_node_stable_key"], "tool:nix")
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("edge_stable_key", text_stdout)
        self.assertIn("python.import", text_stdout)
        self.assertIn("module:json", text_stdout)
        self.assertNotIn("tool:nix", text_stdout)

    def test_storage_host_mutators_cli_reads_loaded_relationship_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="scripts/maintain.sh",
                path="scripts/maintain.sh",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "0" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id=(
                    "scripts/maintain.sh"
                    "#host-mutation:2:filesystem-mutation-rm"
                ),
                path="scripts/maintain.sh",
                start_line=2,
                end_line=2,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["sudo", "rm", "-rf", "/Library/Caches/example"],
                    "category": "filesystem-mutation",
                    "effective_argv": ["rm", "-rf", "/Library/Caches/example"],
                    "privileged": True,
                    "reason": "rm host filesystem path",
                    "tool": "rm",
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "host-mutators",
                "--root-path",
                "/tmp/fixture",
                "--category",
                "filesystem-mutation",
                "--tool",
                "rm",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

        payload = json.loads(stdout)
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(payload[0]["path"], "scripts/maintain.sh")
        self.assertEqual(payload[0]["category"], "filesystem-mutation")
        self.assertEqual(payload[0]["target"], "host:filesystem-mutation")
        self.assertEqual(payload[0]["effective_argv"], [
            "rm",
            "-rf",
            "/Library/Caches/example",
        ])

    def test_storage_host_mutators_canonical_cli_reads_mutates_host_edges(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="scripts/maintain.sh",
                path="scripts/maintain.sh",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "0" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id=(
                    "scripts/maintain.sh"
                    "#host-mutation:2:filesystem-mutation-rm"
                ),
                path="scripts/maintain.sh",
                start_line=2,
                end_line=2,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["sudo", "rm", "-rf", "/Library/Caches/example"],
                    "category": "filesystem-mutation",
                    "effective_argv": ["rm", "-rf", "/Library/Caches/example"],
                    "privileged": True,
                    "reason": "rm host filesystem path",
                    "tool": "rm",
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "host-mutators",
                "--canonical",
                "--root-path",
                "/tmp/fixture",
                "--category",
                "filesystem-mutation",
                "--tool",
                "rm",
                "--source-key",
                "file:scripts/maintain.sh",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            explain_exit_code, explain_stdout, explain_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "explain-canonical-edge",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:scripts/maintain.sh",
                    "--kind",
                    "mutates_host",
                    "--target-key",
                    "host.category:filesystem-mutation",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )

        payload = json.loads(stdout)
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["source_key"], "file:scripts/maintain.sh")
        self.assertEqual(payload[0]["edge_kind"], "mutates_host")
        self.assertEqual(
            payload[0]["target_key"],
            "host.category:filesystem-mutation",
        )
        self.assertEqual(payload[0]["graph_key_version"], 1)
        self.assertEqual(payload[0]["confidence"], "heuristic")
        self.assertFalse(payload[0]["conflict"])
        self.assertEqual(payload[0]["metadata"]["tools"], ["rm"])
        self.assertTrue(payload[0]["metadata"]["privileged_observed"])
        self.assertNotIn("stable_key", payload[0])
        self.assertNotIn("id", payload[0])

        explain_payload = json.loads(explain_stdout)
        self.assertEqual(explain_exit_code, 0, explain_stderr)
        self.assertEqual(
            explain_payload["edge"]["target_key"],
            "host.category:filesystem-mutation",
        )
        self.assertEqual(
            explain_payload["evidence"][0]["path"],
            "scripts/maintain.sh",
        )
        self.assertEqual(
            explain_payload["evidence"][0]["metadata"]["tool"],
            "rm",
        )

    def test_storage_host_mutators_summary_cli_reads_loaded_counts(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="scripts/maintain.sh",
                path="scripts/maintain.sh",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "0" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id=(
                    "scripts/maintain.sh"
                    "#host-mutation:2:filesystem-mutation-rm"
                ),
                path="scripts/maintain.sh",
                start_line=2,
                end_line=2,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["sudo", "rm", "-rf", "/Library/Caches/example"],
                    "category": "filesystem-mutation",
                    "effective_argv": ["rm", "-rf", "/Library/Caches/example"],
                    "privileged": True,
                    "reason": "rm host filesystem path",
                    "tool": "rm",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id=(
                    "scripts/maintain.sh"
                    "#host-mutation:3:filesystem-mutation-rm"
                ),
                path="scripts/maintain.sh",
                start_line=3,
                end_line=3,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["rm", "-rf", "~/Library/Caches/example"],
                    "category": "filesystem-mutation",
                    "effective_argv": ["rm", "-rf", "~/Library/Caches/example"],
                    "privileged": False,
                    "reason": "rm host filesystem path",
                    "tool": "rm",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host-mutation:4:package",
                path="scripts/maintain.sh",
                start_line=4,
                end_line=4,
                name="brew install",
                target="host:package-management",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["brew", "install", "postgresql"],
                    "category": "package-management",
                    "effective_argv": ["brew", "install", "postgresql"],
                    "privileged": False,
                    "reason": "brew install",
                    "tool": "brew",
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "host-mutators-summary",
                "--root-path",
                "/tmp/fixture",
                "--category",
                "filesystem-mutation",
                "--tool",
                "rm",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

        payload = json.loads(stdout)
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(payload, [
            {
                "category": "filesystem-mutation",
                "count": 2,
                "privileged_count": 1,
                "tool": "rm",
            }
        ])

    def test_storage_summary_cli_defaults_to_canonical_counts(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="python.import",
                source_id="bin/tool#import:json",
                path="bin/tool",
                start_line=3,
                end_line=3,
                name="json",
                target="module:json",
                confidence="heuristic",
                extractor="fixture-python",
                extractor_version="0.1.0",
                metadata={"module": "json"},
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "summary",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                "storage",
                "summary",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
            )
            legacy_exit_code, legacy_stdout, legacy_stderr = run_repo_map_in_process(
                "storage",
                "summary",
                "--legacy",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["repository_name"], "fixture")
        self.assertEqual(payload["runs"], 1)
        self.assertEqual(payload["files"], 1)
        self.assertEqual(payload["raw_observations"], 3)
        self.assertEqual(payload["canonical_nodes"], 4)
        self.assertEqual(payload["canonical_edges"], 2)
        self.assertEqual(payload["canonical_evidence"], 3)
        self.assertIn("legacy_nodes", payload)
        self.assertIn("legacy_edges", payload)
        self.assertIn("legacy_evidence", payload)
        self.assertNotIn("repository_id", payload)
        self.assertNotIn("latest_run_id", payload)
        self.assertNotIn("nodes", payload)
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertIn("root_path", text_stdout)
        self.assertIn("canonical_nodes", text_stdout)
        self.assertNotIn("latest_run_id", text_stdout)
        self.assertNotIn("repository_id", text_stdout)
        self.assertIn("/tmp/fixture", text_stdout)
        self.assertEqual(legacy_exit_code, 0, legacy_stderr)
        legacy_payload = json.loads(legacy_stdout)
        self.assertEqual(legacy_payload["nodes"], 5)
        self.assertEqual(legacy_payload["edges"], 2)
        self.assertEqual(legacy_payload["evidence"], 3)
        self.assertIsInstance(legacy_payload["repository_id"], int)
        self.assertIsInstance(legacy_payload["latest_run_id"], int)
        self.assertNotIn("canonical_nodes", legacy_payload)

    def test_temporary_postgres_teardown_runs_after_start_failure(self):
        clusters = []

        class FailingCluster:
            def __init__(self, root):
                self.root = root
                self.stopped = False
                clusters.append(self)

            def start(self):
                raise RuntimeError("bootstrap failed")

            def stop(self):
                self.stopped = True

            def is_running(self):
                return False

        with patch(__name__ + ".PostgresCluster", FailingCluster):
            with patch(__name__ + ".PostgresIpcGuard") as guard_class:
                guard = guard_class.return_value
                with self.assertRaisesRegex(RuntimeError, "bootstrap failed"):
                    with temporary_postgres():
                        pass

        self.assertEqual(len(clusters), 1)
        self.assertTrue(clusters[0].stopped)
        guard.capture_baseline.assert_called_once_with()
        guard.cleanup.assert_called_once_with(live_test_processes=False)


class PostgresCluster:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.socket_dir = root / "socket"
        self.log = root / "postgres.log"
        self.port = 5432
        self.user = "repo_map_test"
        self.bin_dir = postgres_bin_dir()
        self.psql_command = str(self.bin_dir / "psql")
        self.socket_dir.mkdir()
        self.psql_args = [
            "-h",
            str(self.socket_dir),
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            "postgres",
        ]

    def start(self):
        run(
            [
                str(self.bin_dir / "initdb"),
                "-D",
                str(self.data),
                "-A",
                "trust",
                "-U",
                self.user,
                "-L",
                str(postgres_share_dir()),
            ]
        )
        run(
            [
                str(self.bin_dir / "pg_ctl"),
                "-D",
                str(self.data),
                "-l",
                str(self.log),
                "-o",
                f"-k {self.socket_dir} -h '' -p {self.port}",
                "-w",
                "start",
            ]
        )
        return self

    def stop(self):
        if self.data.exists():
            if not self.is_running():
                return
            try:
                self._stop_with_mode("fast")
            except AssertionError:
                if self.is_running():
                    self._stop_with_mode("immediate")

    def _stop_with_mode(self, mode: str):
        run(
            [
                str(self.bin_dir / "pg_ctl"),
                "-D",
                str(self.data),
                "-m",
                mode,
                "-w",
                "stop",
            ]
        )

    def is_running(self) -> bool:
        if not self.data.exists():
            return False
        try:
            result = subprocess.run(
                [
                    str(self.bin_dir / "pg_ctl"),
                    "-D",
                    str(self.data),
                    "status",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return True
        return result.returncode == 0

    def psql_scalar(self, sql: str) -> str:
        command = [self.psql_command, *self.psql_args, "-At", "-v", "ON_ERROR_STOP=1"]
        result = run(command, sql)
        lines = [line for line in result.stdout.splitlines() if line]
        return lines[-1] if lines else ""


class temporary_postgres:
    def __enter__(self):
        self.ipc_guard = PostgresIpcGuard()
        self.ipc_guard.capture_baseline()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cluster = PostgresCluster(Path(self.tmpdir.name))
        try:
            return self.cluster.start()
        except BaseException:
            self._teardown()
            raise

    def __exit__(self, exc_type, exc, tb):
        self._teardown()

    def _teardown(self):
        cluster = getattr(self, "cluster", None)
        stop_error = None
        live_test_processes = False
        if cluster is not None:
            try:
                cluster.stop()
            except BaseException as error:
                stop_error = error
            finally:
                live_test_processes = cluster.is_running()
                self.ipc_guard.cleanup(
                    live_test_processes=live_test_processes,
                )
        try:
            if stop_error is not None:
                raise stop_error
        finally:
            if not live_test_processes:
                self.tmpdir.cleanup()


def require_postgres_binaries():
    bin_dir = postgres_bin_dir()
    missing = [
        command
        for command in ("initdb", "pg_ctl", "psql")
        if not (bin_dir / command).exists()
    ]
    if missing:
        raise unittest.SkipTest(
            f"missing Postgres binaries in {bin_dir}: {', '.join(missing)}"
        )
    postgres_share_dir()


def canonicalization_fixture(name: str, filename: str) -> Path:
    return (
        Path(__file__).parents[3]
        / "fixtures"
        / "canonicalization"
        / name
        / filename
    )


def discovery_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "discovery" / name


def postgres_share_dir() -> Path:
    share = postgres_config_path("--sharedir")
    if share is None:
        share = postgres_bin_dir().parent / "share" / "postgresql"
    if not (share / "postgres.bki").exists():
        raise unittest.SkipTest(f"missing Postgres share directory: {share}")
    return share


def postgres_bin_dir() -> Path:
    bindir = postgres_config_path("--bindir")
    if bindir is not None:
        return bindir
    initdb = Path(shutil.which("initdb") or "initdb").resolve()
    return initdb.parent


def postgres_config_path(option: str) -> Path | None:
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    result = subprocess.run(
        [pg_config, option],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value:
        return None
    return Path(value).resolve()


def run(command, input_text=None):
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    try:
        return subprocess.run(
            command,
            check=True,
            env=env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as error:
        raise AssertionError(
            f"command failed: {command}\n"
            f"stdout:\n{error.stdout}\n"
            f"stderr:\n{error.stderr}"
        ) from error


def run_repo_map_in_process(*args):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(list(args))
    return exit_code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
