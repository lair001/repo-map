import os
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.cli import main
from repomap_kg.github_api_ingestion import (
    GitHubTransportResponse,
    acquire_github_api_source,
)
from repomap_kg.observations import RawObservation
from repomap_kg.source_ingestion import (
    FeedFetchResponse,
    import_archive_source,
    import_warc_source,
    ingest_feed_source,
)
from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
    load_file_observations,
    query_api_summary,
    query_bulk_summary,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_email_summary,
    query_js_summary,
    query_openapi_summary,
    query_python_summary,
    query_ruby_summary,
    query_terraform_summary,
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

    def test_ops_config_check_cli_probes_postgres_status_read_only(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            graph_root = Path(tmpdir) / "repo-map"
            graph_root.mkdir()
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                before_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")
                config_path.write_text(
                    f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "postgres"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{graph_root}"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                    encoding="utf-8",
                )

                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "config-check",
                    "--config",
                    str(config_path),
                    "--check-db",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                after_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["postgres_status"]["db_checked"])
        self.assertTrue(payload["postgres_status"]["connected"])
        self.assertTrue(payload["postgres_status"]["schema_available"])
        self.assertTrue(payload["postgres_status"]["required_tables"]["repositories"])
        self.assertEqual(before_count, "0")
        self.assertEqual(after_count, before_count)
        self.assertTrue(payload["safety"]["no_destructive_operations"])
        self.assertNotIn("DROP", stdout.upper())
        self.assertEqual(stderr, "")

    def test_ops_graphs_cli_checks_storage_status_read_only(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            graph_root = Path(tmpdir) / "repo-map"
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                postgres.psql_scalar(
                    f"""
INSERT INTO repositories(name, root_path)
VALUES ('repo-map', '{graph_root}')
"""
                )
                repo_id = postgres.psql_scalar(
                    "SELECT id FROM repositories WHERE name = 'repo-map';"
                )
                before_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")
                config_path.write_text(
                    f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "postgres"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{graph_root}"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                    encoding="utf-8",
                )

                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "graphs",
                    "--config",
                    str(config_path),
                    "--check-db",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                after_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["db_checked"])
        status = payload["graphs"][0]["storage_status"]
        self.assertTrue(status["db_checked"])
        self.assertTrue(status["schema_available"])
        self.assertTrue(status["repository_exists"])
        self.assertEqual(status["repository_id"], int(repo_id))
        self.assertEqual(status["raw_observations"], 0)
        self.assertEqual(status["canonical_nodes"], 0)
        self.assertEqual(status["canonical_edges"], 0)
        self.assertEqual(before_count, "1")
        self.assertEqual(after_count, before_count)
        self.assertFalse(payload["security"]["destructive_db_actions"])
        self.assertNotIn("DROP", stdout.upper())
        self.assertEqual(stderr, "")

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

    def test_bulk_import_cli_loads_mixed_corpus_through_storage(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(bulk_fixture_root() / "mixed_corpus", root / "mixed_corpus")
            corpus = root / "mixed_corpus"
            corpus_root = str(corpus.resolve())
            input_body = (corpus / "mail" / "single-message.eml").read_text(
                encoding="utf-8"
            )
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "bulk",
                    "import",
                    "--config",
                    str(corpus / "bulk.toml"),
                    "--repository-name",
                    "fixture-bulk",
                    "--root-path",
                    corpus_root,
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
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=corpus_root,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                bulk_summary = query_bulk_summary(
                    postgres.psql_args,
                    root_path=corpus_root,
                    psql_command=postgres.psql_command,
                )
                bulk_summary_exit_code, bulk_summary_stdout, bulk_summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        corpus_root,
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
                table_exit_code, table_stdout, table_stderr = run_repo_map_in_process(
                    "storage",
                    "bulk-summary",
                    "--root-path",
                    corpus_root,
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
                manifest_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM raw_observations
WHERE payload_json->'metadata' ? 'bulk_run_id';
"""
                )
                manifest_dir_exists = (corpus / ".repomap" / "bulk-runs").is_dir()

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["source_id"], "fixture-mixed-corpus")
        self.assertEqual(payload["repository_id"], 1)
        self.assertTrue(payload["no_provider_api"])
        self.assertTrue(manifest_dir_exists)
        self.assertIn("email.message", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("python.module", kinds)
        self.assertIn("doc.page", kinds)
        self.assertNotEqual(manifest_count, "0")
        self.assertIn("bulk_relative_path", raw_payload)
        self.assertNotIn(str(corpus), raw_payload)
        self.assertNotIn("mixed-corpus-secret-value", raw_payload)
        self.assertIn("mixed-corpus-secret-value", input_body)
        self.assertEqual(bulk_summary_exit_code, 0, bulk_summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        bulk_summary_payload = json.loads(bulk_summary_stdout)
        self.assertEqual(bulk_summary.bulk_runs, 1)
        self.assertEqual(bulk_summary.sources, 1)
        self.assertEqual(bulk_summary.source_ids, ("fixture-mixed-corpus",))
        self.assertEqual(bulk_summary.corpus_kinds["mixed_corpus"], 1)
        self.assertEqual(bulk_summary.file_count_included, 6)
        self.assertEqual(bulk_summary.file_count_skipped, 2)
        self.assertEqual(bulk_summary.extractor_counts["javascript"], 1)
        self.assertEqual(bulk_summary.skip_reasons["excluded_directory"], 1)
        self.assertGreater(bulk_summary.observations_with_bulk_provenance, 0)
        self.assertTrue(bulk_summary.no_provider_api)
        self.assertTrue(bulk_summary.no_external_fetch)
        self.assertTrue(bulk_summary.no_source_mutation)
        self.assertTrue(bulk_summary.no_archive_decompression)
        self.assertEqual(bulk_summary_payload["bulk_runs"], 1)
        self.assertEqual(bulk_summary_payload["source_ids"], ["fixture-mixed-corpus"])
        self.assertEqual(bulk_summary_payload["corpus_kinds"]["mixed_corpus"], 1)
        self.assertNotIn(str(corpus), bulk_summary_stdout)
        self.assertNotIn("mixed-corpus-secret-value", bulk_summary_stdout)
        self.assertIn("bulk_runs", table_stdout)
        self.assertIn("mixed_corpus=1", table_stdout)
        self.assertNotIn(str(corpus), table_stdout)
        self.assertNotIn("mixed-corpus-secret-value", table_stdout)

    def test_api_acquire_cli_loads_fixture_response_through_storage(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                api_fixture_root() / "readonly_fixture_api",
                root / "readonly_fixture_api",
            )
            config_path = root / "readonly_fixture_api" / "api-source.toml"
            source_text = (
                root / "readonly_fixture_api" / "responses" / "items.json"
            ).read_text(encoding="utf-8")
            root_path = str(root.resolve())
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "api",
                    "acquire",
                    "--config",
                    str(config_path),
                    "--repository-name",
                    "fixture-api",
                    "--root-path",
                    root_path,
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
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                api_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'api.%';
"""
                )
                provenance_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM raw_observations
WHERE payload_json->'metadata' ? 'api_run_id';
"""
                )
                api_summary = query_api_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                )
                api_summary_exit_code, api_summary_stdout, api_summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "api-summary",
                        "--root-path",
                        root_path,
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
                table_exit_code, table_stdout, table_stderr = run_repo_map_in_process(
                    "storage",
                    "api-summary",
                    "--root-path",
                    root_path,
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
                manifest_dir_exists = (root / ".repomap" / "api-runs").is_dir()

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        api_summary_payload = json.loads(api_summary_stdout)
        self.assertEqual(payload["source_id"], "fixture-readonly-api")
        self.assertEqual(payload["repository_id"], 1)
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        self.assertTrue(manifest_dir_exists)
        self.assertIn("file", kinds)
        self.assertIn("config.document", kinds)
        self.assertEqual(api_canonical_count, "0")
        self.assertNotEqual(provenance_count, "0")
        self.assertIn("api.response", raw_payload)
        self.assertIn("api_retention_policy", raw_payload)
        self.assertIn("config.document", raw_payload)
        self.assertNotIn(str(root), raw_payload)
        self.assertNotIn("fixture-secret-value", raw_payload)
        self.assertNotIn("fixture-api-token", raw_payload)
        self.assertIn("fixture-secret-value", source_text)
        self.assertNotIn(str(root), stdout)
        self.assertNotIn("fixture-secret-value", stdout)
        self.assertEqual(api_summary_exit_code, 0, api_summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(api_summary.api_runs, 1)
        self.assertEqual(api_summary.sources, 1)
        self.assertEqual(api_summary.source_ids, ("fixture-readonly-api",))
        self.assertEqual(api_summary.source_types["api.rest"], 1)
        self.assertEqual(
            api_summary.api_source_classes["api.custom_documented_api"],
            1,
        )
        self.assertEqual(api_summary.provider_names["Fixture Provider"], 1)
        self.assertEqual(api_summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(api_summary.requests, 1)
        self.assertEqual(api_summary.responses, 1)
        self.assertEqual(api_summary.methods["GET"], 1)
        self.assertEqual(api_summary.downstream_routes["config"], 1)
        self.assertEqual(api_summary.response_types["application/json"], 1)
        self.assertEqual(api_summary.redacted_responses, 1)
        self.assertEqual(api_summary.routed_artifacts, 1)
        self.assertGreater(api_summary.observations_with_api_provenance, 0)
        self.assertGreaterEqual(api_summary.config_documents_from_api, 1)
        self.assertTrue(api_summary.no_network)
        self.assertTrue(api_summary.no_mutation)
        self.assertTrue(api_summary.no_credentials_resolved)
        self.assertTrue(api_summary.no_scheduler)
        self.assertTrue(api_summary.no_provider_specific_behavior)
        self.assertEqual(api_summary_payload["api_runs"], 1)
        self.assertEqual(api_summary_payload["source_ids"], ["fixture-readonly-api"])
        self.assertEqual(api_summary_payload["methods"]["GET"], 1)
        self.assertNotIn(str(root), api_summary_stdout)
        self.assertNotIn("fixture-secret-value", api_summary_stdout)
        self.assertNotIn("fixture-api-token", api_summary_stdout)
        self.assertNotIn(str(root), table_stdout)
        self.assertNotIn("fixture-secret-value", table_stdout)
        self.assertNotIn("fixture-api-token", table_stdout)
        self.assertIn("api_runs", table_stdout)
        self.assertIn("Fixture Provider=1", table_stdout)

    def test_github_acquire_cli_loads_fixture_response_through_storage(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                github_api_fixture_root() / "readonly_public_repo",
                root / "readonly_public_repo",
            )
            config_path = root / "readonly_public_repo" / "github-source.toml"
            source_text = (
                root / "readonly_public_repo" / "responses" / "repository.json"
            ).read_text(encoding="utf-8")
            root_path = str(root.resolve())
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "github",
                    "acquire",
                    "--config",
                    str(config_path),
                    "--repository-name",
                    "fixture-github",
                    "--root-path",
                    root_path,
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
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                api_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'api.%';
"""
                )
                github_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'github.%';
"""
                )
                provenance_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM raw_observations
WHERE payload_json->'metadata' ? 'api_run_id';
"""
                )
                api_summary = query_api_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                )
                api_summary_exit_code, api_summary_stdout, api_summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "api-summary",
                        "--root-path",
                        root_path,
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
                manifest_text = next(
                    (root / ".repomap" / "api-runs").glob(
                        "github-public-fixture/*/manifest.json"
                    )
                ).read_text(encoding="utf-8")
                manifest_dir_exists = (root / ".repomap" / "api-runs").is_dir()

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        api_summary_payload = json.loads(api_summary_stdout)
        self.assertEqual(payload["source_id"], "github-public-fixture")
        self.assertEqual(payload["owner"], "fixture-owner")
        self.assertEqual(payload["repository"], "fixture-repo")
        self.assertEqual(payload["repository_id"], 1)
        self.assertEqual(payload["requests"], 5)
        self.assertTrue(payload["fixture_transport_only"])
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        self.assertTrue(manifest_dir_exists)
        self.assertIn("file", kinds)
        self.assertIn("config.document", kinds)
        self.assertEqual(api_canonical_count, "0")
        self.assertEqual(github_canonical_count, "0")
        self.assertNotEqual(provenance_count, "0")
        self.assertIn("api.response", raw_payload)
        self.assertIn("github.repository", raw_payload)
        self.assertIn("github.issue", raw_payload)
        self.assertIn("github.pull_request", raw_payload)
        self.assertIn("github.release", raw_payload)
        self.assertIn("github.workflow_run", raw_payload)
        self.assertIn("api_retention_policy", raw_payload)
        self.assertIn("config.document", raw_payload)
        self.assertNotIn(str(root), raw_payload)
        self.assertNotIn("fixture-secret-value", raw_payload)
        self.assertNotIn("fixture-github-token", raw_payload)
        self.assertNotIn("fixture-private-key", raw_payload)
        self.assertIn("fixture-secret-value", source_text)
        self.assertNotIn(str(root), stdout)
        self.assertNotIn("fixture-secret-value", stdout)
        self.assertNotIn("fixture-github-token", stdout)
        self.assertNotIn("fixture-private-key", stdout)
        self.assertNotIn("fixture-secret-value", manifest_text)
        self.assertNotIn("fixture-github-token", manifest_text)
        self.assertNotIn("fixture-private-key", manifest_text)
        self.assertEqual(api_summary_exit_code, 0, api_summary_stderr)
        self.assertEqual(api_summary.api_runs, 1)
        self.assertEqual(api_summary.sources, 1)
        self.assertEqual(api_summary.source_ids, ("github-public-fixture",))
        self.assertEqual(api_summary.source_types["api.rest"], 1)
        self.assertEqual(api_summary.api_source_classes["api.github.repository"], 1)
        self.assertEqual(api_summary.provider_names["GitHub"], 1)
        self.assertEqual(api_summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(api_summary.requests, 5)
        self.assertEqual(api_summary.responses, 5)
        self.assertEqual(api_summary.methods["GET"], 5)
        self.assertEqual(api_summary.downstream_routes["config"], 5)
        self.assertEqual(api_summary.response_types["application/json"], 5)
        self.assertEqual(api_summary.redacted_responses, 5)
        self.assertEqual(api_summary.routed_artifacts, 5)
        self.assertGreater(api_summary.observations_with_api_provenance, 0)
        self.assertGreaterEqual(api_summary.config_documents_from_api, 5)
        self.assertTrue(api_summary.no_network)
        self.assertTrue(api_summary.no_mutation)
        self.assertTrue(api_summary.no_credentials_resolved)
        self.assertTrue(api_summary.no_scheduler)
        self.assertEqual(api_summary_payload["source_ids"], ["github-public-fixture"])
        self.assertEqual(api_summary_payload["methods"]["GET"], 5)
        self.assertNotIn(str(root), api_summary_stdout)
        self.assertNotIn("fixture-secret-value", api_summary_stdout)
        self.assertNotIn("fixture-github-token", api_summary_stdout)
        self.assertNotIn("fixture-private-key", api_summary_stdout)

    def test_github_public_rest_plan_cli_and_mocked_acquire_load_storage(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                github_api_fixture_root() / "public_real_transport_config",
                root / "public_real_transport_config",
            )
            config_path = root / "public_real_transport_config" / "github-source.toml"
            root_path = str(root.resolve())
            plan_exit_code, plan_stdout, plan_stderr = run_repo_map_in_process(
                "github",
                "plan",
                "--config",
                str(config_path),
                "--json",
            )
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                summary = acquire_github_api_source(
                    config_path,
                    repository_name="fixture-github-real",
                    root_path=root,
                    psql_args=postgres.psql_args,
                    psql_command=postgres.psql_command,
                    transport=MockedGitHubRestTransport(
                        [
                            GitHubTransportResponse(
                                status_code=200,
                                body=json.dumps(
                                    {
                                        "id": 1001,
                                        "name": "fixture-repo",
                                        "full_name": "fixture-owner/fixture-repo",
                                        "private": False,
                                        "clone_url": "https://fixture-token@example.invalid/repo.git",
                                    },
                                    sort_keys=True,
                                ).encode("utf-8"),
                                response_type="application/json",
                                rate_limit={
                                    "x-ratelimit-limit": "60",
                                    "x-ratelimit-remaining": "59",
                                },
                            ),
                            GitHubTransportResponse(
                                status_code=200,
                                body=json.dumps(
                                    [
                                        {
                                            "number": 1,
                                            "title": "Fixture issue",
                                            "body": "public issue body should not be stored",
                                            "token": "fixture-token",
                                        }
                                    ],
                                    sort_keys=True,
                                ).encode("utf-8"),
                                response_type="application/json",
                                rate_limit={
                                    "x-ratelimit-limit": "60",
                                    "x-ratelimit-remaining": "58",
                                },
                            ),
                        ]
                    ),
                )
                kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=postgres.psql_command,
                    )
                }
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                api_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'api.%';
"""
                )
                github_canonical_count = postgres.psql_scalar(
                    """
SELECT count(*)::text
FROM canonical_nodes
WHERE kind LIKE 'github.%';
"""
                )
                api_summary = query_api_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                )
                manifest_text = next(
                    (root / ".repomap" / "api-runs").glob(
                        "github-public-real-fixture/*/manifest.json"
                    )
                ).read_text(encoding="utf-8")

        self.assertEqual(plan_exit_code, 0, plan_stderr)
        plan_payload = json.loads(plan_stdout)
        self.assertEqual(plan_payload["transport"], "github_public_rest")
        self.assertTrue(plan_payload["network_capable"])
        self.assertFalse(plan_payload["fixture_transport_only"])
        self.assertEqual(plan_payload["request_count"], 2)
        self.assertNotIn(str(root), plan_stdout)
        self.assertEqual(summary.source_id, "github-public-real-fixture")
        self.assertEqual(summary.transport, "github_public_rest")
        self.assertFalse(summary.fixture_transport_only)
        self.assertFalse(summary.no_network)
        self.assertEqual(summary.requests, 2)
        self.assertEqual(summary.responses, 2)
        self.assertIn("file", kinds)
        self.assertIn("config.document", kinds)
        self.assertEqual(api_canonical_count, "0")
        self.assertEqual(github_canonical_count, "0")
        self.assertIn('"transport": "github_public_rest"', raw_payload)
        self.assertIn("api.response", raw_payload)
        self.assertIn("github.repository", raw_payload)
        self.assertIn("github.issue", raw_payload)
        self.assertIn("body_sha256", raw_payload)
        self.assertNotIn("public issue body should not be stored", raw_payload)
        self.assertNotIn("fixture-token", raw_payload)
        self.assertNotIn(str(root), raw_payload)
        self.assertIn('"transport": "github_public_rest"', manifest_text)
        self.assertIn('"x-ratelimit-remaining": "58"', manifest_text)
        self.assertNotIn("fixture-token", manifest_text)
        self.assertEqual(api_summary.api_runs, 1)
        self.assertEqual(api_summary.source_ids, ("github-public-real-fixture",))
        self.assertEqual(api_summary.requests, 2)
        self.assertEqual(api_summary.responses, 2)
        self.assertFalse(api_summary.no_network)
        self.assertTrue(api_summary.no_mutation)
        self.assertTrue(api_summary.no_credentials_resolved)
        self.assertTrue(api_summary.no_scheduler)

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

    def test_storage_load_files_reads_ruby_nodes_references_and_explain(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture("ruby_basic", "raw_observations.jsonl")
        root_path = "/tmp/ruby-fixture"

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
                "ruby-fixture",
                "--root-path",
                root_path,
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

            ruby_files = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="ruby.file",
                psql_command=postgres.psql_command,
            )
            ruby_classes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="ruby.class",
                canonical_key="ruby.class:Example%3A%3ARunner",
                psql_command=postgres.psql_command,
            )
            routes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="ruby.route",
                psql_command=postgres.psql_command,
            )
            references = query_canonical_edge_records(
                postgres.psql_args,
                root_path=root_path,
                kind="references",
                source_key="ruby.file:file%3Alib%2Fexample.rb",
                target_key="file:lib/example/service.rb",
                psql_command=postgres.psql_command,
            )
            explanation = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path=root_path,
                source_key=references[0].source_key,
                kind=references[0].edge_kind,
                target_key=references[0].target_key,
                identity_metadata_hash=references[0].identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            ruby_summary = query_ruby_summary(
                postgres.psql_args,
                root_path=root_path,
                psql_command=postgres.psql_command,
            )
            summary_exit_code, summary_stdout, summary_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "ruby-summary",
                    "--root-path",
                    root_path,
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

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertGreaterEqual(len(ruby_files), 10)
        self.assertEqual(
            [node.canonical_key for node in ruby_classes],
            ["ruby.class:Example%3A%3ARunner"],
        )
        self.assertTrue(
            any(node.canonical_key.startswith("ruby.route:") for node in routes)
        )
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].edge_kind, "references")
        self.assertIsNotNone(explanation.edge)
        self.assertEqual(explanation.edge.source_key, "ruby.file:file%3Alib%2Fexample.rb")
        self.assertGreaterEqual(ruby_summary.ruby_files, 10)
        self.assertGreaterEqual(ruby_summary.routes, 2)
        self.assertGreaterEqual(ruby_summary.test_methods, 1)
        self.assertGreaterEqual(ruby_summary.gem_dependencies, 4)
        self.assertGreaterEqual(ruby_summary.vagrant_configs, 5)
        self.assertGreaterEqual(ruby_summary.rake_tasks, 2)
        self.assertEqual(ruby_summary.profile_counts["sinatra"], 1)
        self.assertEqual(ruby_summary.profile_counts["vagrantfile"], 1)
        self.assertTrue(ruby_summary.no_execution)
        summary_payload = json.loads(summary_stdout)
        self.assertEqual(summary_payload["ruby_files"], ruby_summary.ruby_files)
        self.assertEqual(summary_payload["routes"], ruby_summary.routes)
        self.assertEqual(
            summary_payload["profile_counts"]["sinatra"],
            ruby_summary.profile_counts["sinatra"],
        )
        self.assertTrue(summary_payload["no_execution"])
        readback_payload = "\n".join(
            (
                *(str(node.to_dict()) for node in ruby_files),
                *(str(node.to_dict()) for node in ruby_classes),
                *(str(node.to_dict()) for node in routes),
                *(str(edge.to_dict()) for edge in references),
                str(explanation.to_dict()),
                str(ruby_summary.to_dict()),
                summary_stdout,
            )
        )
        self.assertNotIn("EXAMPLE_API_KEY", readback_payload)
        self.assertNotIn("EXAMPLE_SESSION_SECRET", readback_payload)

    def test_storage_load_files_reads_js_nodes_references_and_explain(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture("js_basic", "raw_observations.jsonl")
        root_path = "/tmp/js-fixture"

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
                "js-fixture",
                "--root-path",
                root_path,
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

            js_files = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.file",
                psql_command=postgres.psql_command,
            )
            js_classes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.class",
                canonical_key="js.class:file%3Asrc%2Findex.js:Runner",
                psql_command=postgres.psql_command,
            )
            components = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.component",
                psql_command=postgres.psql_command,
            )
            routes = query_canonical_node_records(
                postgres.psql_args,
                root_path=root_path,
                kind="js.route",
                psql_command=postgres.psql_command,
            )
            references = query_canonical_edge_records(
                postgres.psql_args,
                root_path=root_path,
                kind="references",
                source_key="js.module:file%3Asrc%2Findex.js",
                target_key="file:src/util.mjs",
                psql_command=postgres.psql_command,
            )
            explanation = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path=root_path,
                source_key=references[0].source_key,
                kind=references[0].edge_kind,
                target_key=references[0].target_key,
                identity_metadata_hash=references[0].identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            js_summary = query_js_summary(
                postgres.psql_args,
                root_path=root_path,
                psql_command=postgres.psql_command,
            )
            summary_exit_code, summary_stdout, summary_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "js-summary",
                    "--root-path",
                    root_path,
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
            table_exit_code, table_stdout, table_stderr = run_repo_map_in_process(
                "storage",
                "js-summary",
                "--root-path",
                root_path,
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
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertGreaterEqual(len(js_files), 10)
        self.assertEqual(
            [node.canonical_key for node in js_classes],
            ["js.class:file%3Asrc%2Findex.js:Runner"],
        )
        self.assertTrue(
            any(node.canonical_key.startswith("js.component:") for node in components)
        )
        self.assertTrue(any(node.canonical_key.startswith("js.route:") for node in routes))
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].edge_kind, "references")
        self.assertIsNotNone(explanation.edge)
        self.assertEqual(explanation.edge.source_key, "js.module:file%3Asrc%2Findex.js")
        self.assertGreaterEqual(js_summary.js_files, 10)
        self.assertGreaterEqual(js_summary.components, 5)
        self.assertGreaterEqual(js_summary.routes, 2)
        self.assertGreaterEqual(js_summary.test_suites, 2)
        self.assertGreaterEqual(js_summary.test_cases, 2)
        self.assertGreaterEqual(js_summary.hooks, 2)
        self.assertGreaterEqual(js_summary.test_expectations, 2)
        self.assertGreaterEqual(js_summary.source_map_references, 1)
        self.assertGreaterEqual(js_summary.dynamic_diagnostics, 5)
        self.assertEqual(js_summary.profile_counts["jest"], 2)
        self.assertGreaterEqual(js_summary.profile_counts["react"], 4)
        self.assertEqual(js_summary.profile_counts["angular"], 2)
        self.assertEqual(js_summary.profile_counts["vue"], 1)
        self.assertEqual(js_summary.profile_counts["test_report_asset"], 1)
        self.assertEqual(js_summary.test_report_asset_files, 1)
        self.assertTrue(js_summary.no_execution)
        summary_payload = json.loads(summary_stdout)
        self.assertEqual(summary_payload["js_files"], js_summary.js_files)
        self.assertEqual(summary_payload["components"], js_summary.components)
        self.assertEqual(
            summary_payload["profile_counts"]["react"],
            js_summary.profile_counts["react"],
        )
        self.assertTrue(summary_payload["no_execution"])
        self.assertIn("js_files", table_stdout)
        self.assertIn("profile_counts", table_stdout)
        self.assertIn("react=", table_stdout)
        self.assertIn("no_execution", table_stdout)
        readback_payload = "\n".join(
            (
                *(str(node.to_dict()) for node in js_files),
                *(str(node.to_dict()) for node in js_classes),
                *(str(node.to_dict()) for node in components),
                *(str(node.to_dict()) for node in routes),
                *(str(edge.to_dict()) for edge in references),
                str(explanation.to_dict()),
                str(js_summary.to_dict()),
                summary_stdout,
                table_stdout,
            )
        )
        self.assertNotIn("placeholder", readback_payload)
        self.assertNotIn("Bearer ${apiToken}", readback_payload)

    def test_storage_loads_js5_framework_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("js5_frameworks")

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
                        "js5-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                js_summary = query_js_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        expected_framework_kinds = {
            "node.entrypoint",
            "node.require",
            "node.export",
            "express.app",
            "express.router",
            "express.route",
            "express.middleware",
            "express.error_handler",
            "nest.module",
            "nest.controller",
            "nest.provider",
            "nest.route",
            "next.page",
            "next.api_route",
            "next.app_route",
            "next.route",
            "jest.suite",
            "jest.test",
            "jest.expectation",
            "jest.mock",
            "jquery.selector",
            "jquery.event",
            "jquery.ajax",
            "jquery.plugin_reference",
            "js.framework_reference",
        }
        self.assertTrue(expected_framework_kinds.issubset(discovered_kinds))
        self.assertNotIn("fake-js5-jquery-token", discover_stdout)
        self.assertNotIn("SECRET_TOKEN", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(expected_framework_kinds.issubset(raw_kinds))
        self.assertNotIn("fake-js5-jquery-token", raw_payload)
        self.assertNotIn("SECRET_TOKEN", raw_payload)
        canonical_kinds = {node.kind for node in canonical_nodes}
        self.assertIn("js.file", canonical_kinds)
        self.assertIn("js.route", canonical_kinds)
        self.assertFalse(
            any(
                node.kind.startswith(
                    ("express.", "nest.", "next.", "jest.", "jquery.", "node.")
                )
                for node in canonical_nodes
            )
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )
        self.assertGreaterEqual(js_summary.js_files, 8)
        self.assertGreaterEqual(js_summary.routes, 1)
        self.assertGreaterEqual(js_summary.test_cases, 1)

    def test_storage_js_framework_summary_reads_js5_evidence_without_reload(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("js5_frameworks")

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
                        "js6-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_count_before = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "js-framework-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "js-framework-summary",
                        *storage_args,
                    )
                )
                raw_count_after = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(raw_count_before, raw_count_after)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["repository_name"], "js6-fixture")
        self.assertGreaterEqual(payload["framework_observations"], 25)
        self.assertGreaterEqual(payload["framework_profiles"]["node"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["express"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["nest"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["next"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["jest"], 1)
        self.assertGreaterEqual(payload["framework_profiles"]["jquery"], 1)
        self.assertEqual(payload["node"]["entrypoints"], 1)
        self.assertGreaterEqual(payload["node"]["requires"], 1)
        self.assertEqual(payload["express"]["apps"], 1)
        self.assertGreaterEqual(payload["express"]["routes"], 4)
        self.assertEqual(payload["express"]["error_handlers"], 1)
        self.assertGreaterEqual(payload["express"]["dynamic_routes"], 1)
        self.assertEqual(payload["nest"]["modules"], 1)
        self.assertEqual(payload["nest"]["controllers"], 1)
        self.assertEqual(payload["nest"]["providers"], 1)
        self.assertGreaterEqual(payload["nest"]["routes"], 2)
        self.assertGreaterEqual(payload["next"]["pages"], 2)
        self.assertEqual(payload["next"]["api_routes"], 1)
        self.assertEqual(payload["next"]["app_routes"], 1)
        self.assertGreaterEqual(payload["next"]["route_handlers"], 2)
        self.assertEqual(payload["jest"]["suites"], 1)
        self.assertEqual(payload["jest"]["tests"], 1)
        self.assertEqual(payload["jest"]["expectations"], 2)
        self.assertGreaterEqual(payload["jest"]["mocks"], 3)
        self.assertEqual(payload["jquery"]["selectors"], 2)
        self.assertEqual(payload["jquery"]["events"], 3)
        self.assertEqual(payload["jquery"]["ajax_references"], 2)
        self.assertEqual(payload["jquery"]["plugin_references"], 1)
        self.assertGreaterEqual(payload["generic_js"]["canonical_routes"], 1)
        self.assertGreaterEqual(payload["generic_js"]["canonical_test_cases"], 1)
        self.assertTrue(payload["safety"]["no_execution"])
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["raw_profile_only"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertIn("framework_observations", table_stdout)
        self.assertIn("entrypoints=1", table_stdout)
        self.assertIn("no_fetch=true", table_stdout)
        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-js5-jquery-token", readback_payload)
        self.assertNotIn("SECRET_TOKEN", readback_payload)
        self.assertFalse(
            any(
                node.kind.startswith(
                    ("express.", "nest.", "next.", "jest.", "jquery.", "node.")
                )
                for node in canonical_nodes
            )
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )

    def test_storage_loads_eml_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("mail_basic")

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
                        "mail-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                mailboxes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.mailbox",
                    psql_command=postgres.psql_command,
                )
                messages = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.message",
                    psql_command=postgres.psql_command,
                )
                addresses = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.address",
                    psql_command=postgres.psql_command,
                )
                parts = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.part",
                    psql_command=postgres.psql_command,
                )
                attachment_stubs = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.attachment_stub",
                    psql_command=postgres.psql_command,
                )
                thread_hints = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="email.thread_hint",
                    psql_command=postgres.psql_command,
                )
                references = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="references",
                    psql_command=postgres.psql_command,
                )
                defines = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="defines",
                    psql_command=postgres.psql_command,
                )
                mailbox_define = next(
                    edge
                    for edge in defines
                    if edge.source_key.startswith("email.mailbox:")
                    and edge.target_key.startswith("email.message:")
                )
                eml_define = next(
                    edge
                    for edge in defines
                    if edge.source_key == "file:single-message.eml"
                    and edge.target_key.startswith("email.message:")
                )
                thread_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("email.message:")
                    and edge.target_key.startswith("unknown:email-message:")
                )
                address_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("email.message:")
                    and edge.target_key.startswith("email.address:")
                )
                list_unsubscribe_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("email.message:")
                    and edge.target_key.startswith("external.url:")
                    and "list_unsubscribe" in edge.metadata.get("reference_kinds", [])
                )
                explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=thread_reference.source_key,
                    kind=thread_reference.edge_kind,
                    target_key=thread_reference.target_key,
                    identity_metadata_hash=thread_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                mailbox_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=mailbox_define.source_key,
                    kind=mailbox_define.edge_kind,
                    target_key=mailbox_define.target_key,
                    identity_metadata_hash=mailbox_define.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                eml_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=eml_define.source_key,
                    kind=eml_define.edge_kind,
                    target_key=eml_define.target_key,
                    identity_metadata_hash=eml_define.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                address_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=address_reference.source_key,
                    kind=address_reference.edge_kind,
                    target_key=address_reference.target_key,
                    identity_metadata_hash=address_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                list_unsubscribe_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    source_key=list_unsubscribe_reference.source_key,
                    kind=list_unsubscribe_reference.edge_kind,
                    target_key=list_unsubscribe_reference.target_key,
                    identity_metadata_hash=(
                        list_unsubscribe_reference.identity_metadata_hash
                    ),
                    psql_command=postgres.psql_command,
                )
                email_summary = query_email_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "email-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "email-summary",
                        *storage_args,
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        self.assertIn("email.message", {record["kind"] for record in discovered})
        self.assertIn("email.mailbox", {record["kind"] for record in discovered})
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertTrue(mailboxes)
        self.assertGreaterEqual(len(messages), 8)
        self.assertGreaterEqual(len(addresses), 2)
        self.assertTrue(parts)
        self.assertTrue(attachment_stubs)
        self.assertTrue(thread_hints)
        self.assertIsNotNone(explanation.edge)
        self.assertIsNotNone(mailbox_explanation.edge)
        self.assertIsNotNone(eml_explanation.edge)
        self.assertIsNotNone(address_explanation.edge)
        self.assertIsNotNone(list_unsubscribe_explanation.edge)
        self.assertEqual(
            explanation.evidence[0].raw_observation["kind"],
            "email.reference",
        )
        self.assertEqual(
            mailbox_explanation.evidence[0].raw_observation["kind"],
            "email.message",
        )
        self.assertEqual(
            eml_explanation.evidence[0].raw_observation["kind"],
            "email.message",
        )
        self.assertEqual(
            address_explanation.evidence[0].raw_observation["kind"],
            "email.address",
        )
        self.assertEqual(
            list_unsubscribe_explanation.evidence[0].raw_observation["kind"],
            "email.reference",
        )
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertGreaterEqual(email_summary.mailboxes, 1)
        self.assertGreaterEqual(email_summary.messages, len(messages))
        self.assertGreaterEqual(email_summary.eml_messages, 8)
        self.assertGreaterEqual(email_summary.mbox_messages, 2)
        self.assertGreaterEqual(email_summary.addresses, 2)
        self.assertGreaterEqual(email_summary.address_observations, 2)
        self.assertGreaterEqual(email_summary.address_domains, 1)
        self.assertGreaterEqual(email_summary.mime_parts, len(parts))
        self.assertGreaterEqual(email_summary.text_plain_parts, 1)
        self.assertGreaterEqual(email_summary.text_html_parts, 1)
        self.assertGreaterEqual(email_summary.attachment_stubs, 1)
        self.assertGreaterEqual(email_summary.inline_attachments, 1)
        self.assertGreaterEqual(email_summary.content_id_parts, 1)
        self.assertGreaterEqual(email_summary.thread_hints, 1)
        self.assertGreaterEqual(email_summary.message_references, 1)
        self.assertGreaterEqual(email_summary.external_url_references, 1)
        self.assertGreaterEqual(email_summary.list_unsubscribe_references, 1)
        self.assertGreaterEqual(email_summary.parse_errors, 1)
        self.assertGreaterEqual(email_summary.malformed_or_oversized_diagnostics, 1)
        self.assertGreaterEqual(email_summary.message_id_present, 1)
        self.assertGreaterEqual(email_summary.message_id_missing_or_invalid, 1)
        self.assertGreaterEqual(email_summary.messages_with_attachments, 1)
        self.assertGreaterEqual(email_summary.messages_with_html, 1)
        self.assertGreaterEqual(email_summary.messages_with_plain, 1)
        self.assertGreaterEqual(email_summary.mailbox_limits, 0)
        self.assertTrue(email_summary.no_provider_api)
        self.assertTrue(email_summary.no_mutation)
        self.assertTrue(email_summary.no_body_text)
        self.assertTrue(email_summary.no_attachment_content)
        summary_payload = json.loads(summary_stdout)
        self.assertEqual(summary_payload["messages"], email_summary.messages)
        self.assertEqual(summary_payload["mailboxes"], email_summary.mailboxes)
        self.assertTrue(summary_payload["no_provider_api"])
        self.assertTrue(summary_payload["no_body_text"])
        self.assertIn("mailboxes", table_stdout)
        self.assertIn("attachment_stubs", table_stdout)
        self.assertIn("no_provider_api", table_stdout)
        self.assertIn("no_attachment_content", table_stdout)
        readback_payload = "\n".join(
            (
                discover_stdout,
                *(str(node.to_dict()) for node in mailboxes),
                *(str(node.to_dict()) for node in messages),
                *(str(node.to_dict()) for node in addresses),
                *(str(node.to_dict()) for node in parts),
                *(str(node.to_dict()) for node in attachment_stubs),
                *(str(node.to_dict()) for node in thread_hints),
                *(str(edge.to_dict()) for edge in defines),
                *(str(edge.to_dict()) for edge in references),
                str(explanation.to_dict()),
                str(mailbox_explanation.to_dict()),
                str(eml_explanation.to_dict()),
                str(address_explanation.to_dict()),
                str(list_unsubscribe_explanation.to_dict()),
                str(email_summary.to_dict()),
                summary_stdout,
                table_stdout,
            )
        )
        self.assertNotIn("alice@example.invalid", readback_payload)
        self.assertNotIn("bob@example.invalid", readback_payload)
        self.assertNotIn("Example Sender", readback_payload)
        self.assertNotIn("Example Recipient", readback_payload)
        self.assertNotIn("Quarterly planning code", readback_payload)
        self.assertNotIn("Fixture body", readback_payload)
        self.assertNotIn("fixture body", readback_payload)
        self.assertNotIn("invoice-secret-code.txt", readback_payload)
        self.assertNotIn("fake-mail-reset-code", readback_payload)
        self.assertNotIn("fake-mail-token", readback_payload)
        self.assertNotIn("Sample MBOX private subject", readback_payload)
        self.assertNotIn("Sample MBOX body text", readback_payload)
        self.assertNotIn("sample-mbox-secret-note.txt", readback_payload)

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
                        "--legacy",
                        *storage_args,
                        "--kind",
                        "shell.command",
                        "--json",
                    )
                )
                default_nodes_exit, default_nodes_stdout, default_nodes_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--kind",
                        "file",
                        "--path-prefix",
                        "bin/",
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
                        "--legacy",
                        *storage_args,
                        "--kind",
                        "shell.command",
                        "--json",
                    )
                )
                default_edges_exit, default_edges_stdout, default_edges_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
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

        self.assertEqual(default_nodes_exit, 0, default_nodes_stderr)
        default_nodes = json.loads(default_nodes_stdout)

        self.assertEqual(canonical_nodes_exit, 0, canonical_nodes_stderr)
        canonical_nodes = json.loads(canonical_nodes_stdout)
        self.assertEqual(default_nodes, canonical_nodes)
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

        self.assertEqual(default_edges_exit, 0, default_edges_stderr)
        default_edges = json.loads(default_edges_stdout)

        self.assertEqual(canonical_edges_exit, 0, canonical_edges_stderr)
        canonical_edges = json.loads(canonical_edges_stdout)
        self.assertEqual(default_edges, canonical_edges)
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
            "--root-path",
            "/tmp/fixture",
            "--canonical-key",
            "file:bin/tool#line:12",
            "--json",
        )
        bad_edge_exit, _bad_edge_stdout, bad_edge_stderr = run_repo_map_in_process(
            "storage",
            "edges",
            "--root-path",
            "/tmp/fixture",
            "--source-key",
            "file:bin/tool#line:12",
            "--json",
        )
        conflict_node_exit, _conflict_node_stdout, conflict_node_stderr = (
            run_repo_map_in_process(
                "storage",
                "nodes",
                "--canonical",
                "--legacy",
                "--root-path",
                "/tmp/fixture",
                "--json",
            )
        )
        legacy_node_filter_exit, _legacy_node_filter_stdout, (
            legacy_node_filter_stderr
        ) = run_repo_map_in_process(
            "storage",
            "nodes",
            "--root-path",
            "/tmp/fixture",
            "--stable-key",
            "tool:nix",
            "--json",
        )
        canonical_node_filter_exit, _canonical_node_filter_stdout, (
            canonical_node_filter_stderr
        ) = run_repo_map_in_process(
            "storage",
            "nodes",
            "--legacy",
            "--root-path",
            "/tmp/fixture",
            "--canonical-key",
            "file:bin/tool",
            "--json",
        )
        conflict_edge_exit, _conflict_edge_stdout, conflict_edge_stderr = (
            run_repo_map_in_process(
                "storage",
                "edges",
                "--canonical",
                "--legacy",
                "--root-path",
                "/tmp/fixture",
                "--json",
            )
        )
        legacy_edge_filter_exit, _legacy_edge_filter_stdout, (
            legacy_edge_filter_stderr
        ) = run_repo_map_in_process(
            "storage",
            "edges",
            "--root-path",
            "/tmp/fixture",
            "--source-node",
            "tool:nix",
            "--json",
        )
        canonical_edge_filter_exit, _canonical_edge_filter_stdout, (
            canonical_edge_filter_stderr
        ) = run_repo_map_in_process(
            "storage",
            "edges",
            "--legacy",
            "--root-path",
            "/tmp/fixture",
            "--source-key",
            "file:bin/tool",
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
        self.assertEqual(conflict_node_exit, 1)
        self.assertIn("cannot combine --canonical and --legacy", conflict_node_stderr)
        self.assertEqual(legacy_node_filter_exit, 1)
        self.assertIn("stable-key is a legacy node filter", legacy_node_filter_stderr)
        self.assertEqual(canonical_node_filter_exit, 1)
        self.assertIn(
            "canonical-key is a canonical node filter",
            canonical_node_filter_stderr,
        )
        self.assertEqual(conflict_edge_exit, 1)
        self.assertIn("cannot combine --canonical and --legacy", conflict_edge_stderr)
        self.assertEqual(legacy_edge_filter_exit, 1)
        self.assertIn("source-node is a legacy edge filter", legacy_edge_filter_stderr)
        self.assertEqual(canonical_edge_filter_exit, 1)
        self.assertIn(
            "source-key is a canonical edge filter",
            canonical_edge_filter_stderr,
        )
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

    def test_storage_loads_json_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("config_json_basic")

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
                        "config-fixture",
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

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("config.document")
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                public_refs_exit, public_refs_stdout, public_refs_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        "--canonical",
                        *storage_args,
                        "--kind",
                        "references",
                        "--json",
                    )
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                        "--kind",
                        "references",
                        "--target-key",
                        "tool:repomap-kg",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.jsonl_record",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fixture-secret-placeholder", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertTrue(
            {
                "config.document:file%3Aevents.jsonl",
                "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                "config.document:file%3Asettings.jsonc",
            }.issubset(document_keys)
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fapi_key",
            path_keys,
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
            define_targets,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        self.assertEqual(public_refs_exit, 0, public_refs_stderr)
        self.assertEqual(json.loads(public_refs_stdout), reference_edges)
        self.assertIn(
            (
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                "tool:repomap-kg",
            ),
            {
                (record["source_key"], record["target_key"])
                for record in reference_edges
            },
        )
        self.assertIn(
            "env:REPOMAP_MCP_CONFIG",
            {record["target_key"] for record in reference_edges},
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {record["target_key"] for record in reference_edges},
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(explanation["edge"]["target_key"], "tool:repomap-kg")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("fixture-secret-placeholder", explain_stdout)

    def test_storage_loads_tfjson_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("tfjson1_ecosystem_config")

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
                        "tfjson-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "ecosystem.config_profile",
                "npm.package",
                "npm.script",
                "npm.dependency",
                "typescript.config",
                "typescript.reference",
                "angular.project",
                "angular.target",
                "jest.config",
                "nest.config",
                "playwright.config",
                "terraform.file",
                "terraform.required_provider",
                "terraform.resource",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.reference",
                "kubernetes.resource",
                "argocd.application",
                "liquibase.changelog",
                "liquibase.changeset",
                "docker.reference",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fake-tfjson-package-secret", discover_stdout)
        self.assertNotIn("fake-tfjson-terraform-secret", discover_stdout)
        self.assertNotIn("fake-tfjson-tfvars-secret", discover_stdout)
        self.assertNotIn("fake-tfjson-k8s-secret", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {"npm.package", "terraform.resource", "kubernetes.resource"}.issubset(
                raw_kinds
            )
        )
        self.assertNotIn("fake-tfjson-package-secret", raw_payload)
        self.assertNotIn("fake-tfjson-terraform-secret", raw_payload)
        self.assertNotIn("fake-tfjson-tfvars-secret", raw_payload)
        self.assertNotIn("fake-tfjson-k8s-secret", raw_payload)
        self.assertIn("config.document", canonical_kinds)
        self.assertIn("config.path", canonical_kinds)
        self.assertNotIn("terraform.resource", canonical_kinds)
        self.assertNotIn("npm.package", canonical_kinds)
        self.assertNotIn("kubernetes.resource", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )

    def test_storage_loads_python_ecosystem_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = python_ecosystem_fixture("dogfood")

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
                        "py1-dogfood-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "python.package_file",
                "python.requirement",
                "python.pyproject",
                "python.build_system",
                "python.tool_config",
                "python.test_file",
                "python.unittest_case",
                "python.pytest_test",
            }.issubset(discovered_kinds)
        )

        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {
                "python.package_file",
                "python.requirement",
                "python.pyproject",
                "python.build_system",
                "python.tool_config",
                "python.test_file",
                "python.unittest_case",
                "python.pytest_test",
            }.issubset(raw_kinds)
        )
        self.assertIn("python.module", canonical_kinds)
        self.assertIn("python.method", canonical_kinds)
        self.assertIn("config.document", canonical_kinds)
        self.assertNotIn("python.requirement", canonical_kinds)
        self.assertNotIn("python.pytest_test", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges}
            - {"defines", "references", "imports"},
            set(),
        )
        self.assertNotIn("fake-python", raw_payload)

    def test_storage_loads_python_web_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = python_web_fixture()

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
                        "py2-web-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {
                "python.flask_route",
                "python.fastapi_route",
                "python.fastapi_dependency",
                "python.django_urlpattern",
                "python.django_view",
                "python.django_model",
                "python.django_setting_reference",
                "python.reference",
                "python.redaction",
            }.issubset(raw_kinds)
        )
        self.assertIn("python.module", canonical_kinds)
        self.assertIn("python.function", canonical_kinds)
        self.assertIn("python.class", canonical_kinds)
        self.assertNotIn("python.flask_route", canonical_kinds)
        self.assertNotIn("python.fastapi_route", canonical_kinds)
        self.assertNotIn("python.django_urlpattern", canonical_kinds)
        self.assertNotIn("python.django_model", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges}
            - {"defines", "references", "imports"},
            set(),
        )
        self.assertNotIn("fake-flask", raw_payload)
        self.assertNotIn("fake-fastapi", raw_payload)
        self.assertNotIn("fake-django", raw_payload)
        self.assertNotIn("fixture item summary", raw_payload)
        self.assertNotIn("fixture bulk description", raw_payload)

    def test_storage_python_summary_reads_py1_py2_evidence_without_reload(self):
        require_postgres_binaries()
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_root = Path(tmpdir) / "python-summary-dogfood"
            shutil.copytree(python_ecosystem_fixture("dogfood"), fixture_root)
            shutil.copytree(python_web_fixture(), fixture_root / "web")

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
                            "py3-dogfood-fixture",
                            *storage_args,
                            "--json",
                        )
                    )
                    raw_count_before = postgres.psql_scalar(
                        "SELECT COUNT(*)::text FROM raw_observations;"
                    )
                    summary = query_python_summary(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                    summary_exit_code, summary_stdout, summary_stderr = (
                        run_repo_map_in_process(
                            "storage",
                            "python-summary",
                            *storage_args,
                            "--json",
                        )
                    )
                    table_exit_code, table_stdout, table_stderr = (
                        run_repo_map_in_process(
                            "storage",
                            "python-summary",
                            *storage_args,
                        )
                    )
                    raw_count_after = postgres.psql_scalar(
                        "SELECT COUNT(*)::text FROM raw_observations;"
                    )
                    raw_payload = postgres.psql_scalar(
                        """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                    )
                    canonical_nodes = query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                    canonical_edges = query_canonical_edge_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(raw_count_before, raw_count_after)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["repository_name"], "py3-dogfood-fixture")
        self.assertEqual(payload["package_files"]["requirements"], 2)
        self.assertEqual(payload["package_files"]["pyproject"], 1)
        self.assertGreaterEqual(payload["python_observations"], 40)
        self.assertGreaterEqual(payload["packaging"]["requirements"], 4)
        self.assertGreaterEqual(payload["packaging"]["build_systems"], 1)
        self.assertGreaterEqual(payload["packaging"]["tool_configs"], 1)
        self.assertGreaterEqual(payload["tests"]["test_files"], 1)
        self.assertGreaterEqual(payload["tests"]["unittest_cases"], 1)
        self.assertGreaterEqual(payload["tests"]["pytest_tests"], 1)
        self.assertGreaterEqual(payload["tests"]["assertions"], 2)
        self.assertGreaterEqual(payload["frameworks"]["flask_apps"], 1)
        self.assertGreaterEqual(payload["frameworks"]["flask_routes"], 1)
        self.assertGreaterEqual(payload["frameworks"]["fastapi_apps"], 1)
        self.assertGreaterEqual(payload["frameworks"]["fastapi_routes"], 1)
        self.assertGreaterEqual(payload["frameworks"]["fastapi_dependencies"], 1)
        self.assertGreaterEqual(payload["frameworks"]["django_urlpatterns"], 1)
        self.assertGreaterEqual(payload["frameworks"]["django_views"], 1)
        self.assertGreaterEqual(payload["frameworks"]["django_models"], 1)
        self.assertGreaterEqual(payload["references"]["total"], 1)
        self.assertGreaterEqual(payload["references"]["local_file_refs"], 1)
        self.assertGreaterEqual(payload["references"]["framework_refs"], 1)
        self.assertGreaterEqual(payload["redactions"]["framework_settings"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["parse_errors"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["dynamic_constructs"], 1)
        self.assertGreaterEqual(payload["generic_python"]["modules"], 1)
        self.assertGreaterEqual(payload["generic_python"]["functions"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_documents"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_paths"], 1)
        self.assertTrue(payload["dogfooding"]["repo_map_profile_observed"])
        self.assertTrue(payload["dogfooding"]["bounded"])
        self.assertFalse(payload["dogfooding"]["generated_report_committed"])
        self.assertTrue(payload["safety"]["no_execution"])
        self.assertTrue(payload["safety"]["no_imports"])
        self.assertTrue(payload["safety"]["no_test_execution"])
        self.assertTrue(payload["safety"]["no_framework_startup"])
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["no_package_install"])
        self.assertTrue(payload["safety"]["no_openapi_fetch"])
        self.assertTrue(payload["safety"]["raw_profile_only"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertEqual(summary.package_files["requirements"], 2)
        self.assertGreaterEqual(summary.frameworks["flask_routes"], 1)
        self.assertIn("python_observations", table_stdout)
        self.assertIn("requirements=2", table_stdout)
        self.assertIn("fastapi_routes", table_stdout)
        self.assertIn("repo_map_profile_observed=true", table_stdout)
        self.assertIn("no_imports=true", table_stdout)

        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-python", readback_payload)
        self.assertNotIn("fake-flask", readback_payload)
        self.assertNotIn("fake-fastapi", readback_payload)
        self.assertNotIn("fake-django", readback_payload)
        self.assertNotIn("user:pass@", readback_payload)
        self.assertNotIn("fake-python", raw_payload)
        canonical_kinds = {record.kind for record in canonical_nodes}
        self.assertIn("python.module", canonical_kinds)
        self.assertIn("python.function", canonical_kinds)
        self.assertIn("config.document", canonical_kinds)
        self.assertFalse(
            any(
                kind
                in {
                    "python.requirement",
                    "python.pytest_test",
                    "python.unittest_case",
                    "python.flask_route",
                    "python.fastapi_route",
                    "python.django_urlpattern",
                    "python.django_model",
                }
                for kind in canonical_kinds
            )
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges}
            - {"defines", "references", "imports"},
            set(),
        )

    def test_storage_loads_tfhcl_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = terraform_hcl_fixture("basic")

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
                        "tfhcl-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "terraform.file",
                "terraform.block",
                "terraform.required_version",
                "terraform.required_provider",
                "terraform.backend",
                "terraform.provider",
                "terraform.resource",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.reference",
                "terraform.import",
                "terraform.redaction",
                "terraform.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fake-tfhcl-provider-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-module-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-prod-tfvars-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-tfvars-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-import-secret", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {"terraform.block", "terraform.resource", "terraform.variable"}.issubset(
                raw_kinds
            )
        )
        self.assertNotIn("fake-tfhcl-provider-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-module-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-prod-tfvars-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-tfvars-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-import-secret", raw_payload)
        self.assertNotIn("terraform.resource", canonical_kinds)
        self.assertNotIn("terraform.module", canonical_kinds)
        self.assertNotIn("terraform.variable", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )

    def test_storage_terraform_summary_reads_hcl_evidence_without_reload(self):
        require_postgres_binaries()
        fixture_root = terraform_hcl_fixture("basic")

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
                        "tfhcl2-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_count_before = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                summary = query_terraform_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "terraform-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "terraform-summary",
                        *storage_args,
                    )
                )
                raw_count_after = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(raw_count_before, raw_count_after)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["repository_name"], "tfhcl2-fixture")
        self.assertEqual(payload["file_families"]["tf"], 2)
        self.assertEqual(payload["file_families"]["tfvars"], 1)
        self.assertEqual(payload["file_families"]["terraform.tfvars"], 1)
        self.assertEqual(payload["file_families"]["auto.tfvars"], 1)
        self.assertEqual(summary.file_families["tf"], 2)
        self.assertGreaterEqual(payload["terraform_observations"], 20)
        self.assertEqual(payload["terraform_files"], 5)
        self.assertGreaterEqual(payload["terraform"]["blocks"], 10)
        self.assertGreaterEqual(payload["terraform"]["providers"], 1)
        self.assertGreaterEqual(payload["terraform"]["required_providers"], 1)
        self.assertGreaterEqual(payload["terraform"]["required_versions"], 1)
        self.assertGreaterEqual(payload["terraform"]["backends"], 1)
        self.assertGreaterEqual(payload["terraform"]["resources"], 1)
        self.assertGreaterEqual(payload["terraform"]["data_sources"], 1)
        self.assertGreaterEqual(payload["terraform"]["modules"], 1)
        self.assertGreaterEqual(payload["terraform"]["variables"], 4)
        self.assertGreaterEqual(payload["terraform"]["outputs"], 1)
        self.assertGreaterEqual(payload["terraform"]["locals"], 1)
        self.assertGreaterEqual(payload["terraform"]["moved"], 1)
        self.assertGreaterEqual(payload["terraform"]["imports"], 1)
        self.assertGreaterEqual(payload["terraform"]["checks"], 1)
        self.assertGreaterEqual(payload["terraform"]["removed"], 1)
        self.assertGreaterEqual(payload["references"]["total"], 1)
        self.assertGreaterEqual(payload["references"]["module_sources"], 1)
        self.assertGreaterEqual(payload["references"]["local_module_refs"], 1)
        self.assertGreaterEqual(payload["references"]["remote_refs_not_fetched"], 1)
        self.assertGreaterEqual(payload["references"]["depends_on"], 1)
        self.assertGreaterEqual(payload["references"]["provider_aliases"], 1)
        self.assertEqual(payload["tfvars"]["files"], 3)
        self.assertGreaterEqual(payload["tfvars"]["variables"], 3)
        self.assertFalse(payload["tfvars"]["literal_values_exposed"])
        self.assertGreaterEqual(payload["redactions"]["tfvars_values"], 3)
        self.assertGreaterEqual(payload["redactions"]["secret_like_fields"], 1)
        self.assertGreaterEqual(payload["redactions"]["credentialed_urls"], 1)
        self.assertGreaterEqual(payload["redactions"]["import_ids"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["parse_errors"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["malformed_hcl"], 1)
        self.assertGreaterEqual(payload["generic_config"]["file_nodes"], 5)
        self.assertTrue(payload["safety"]["no_execution"])
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["no_terraform_cli"])
        self.assertTrue(payload["safety"]["tfvars_redacted"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertIn("terraform_observations", table_stdout)
        self.assertIn("remote_refs_not_fetched", table_stdout)
        self.assertIn("literal_values_exposed=false", table_stdout)
        self.assertIn("no_terraform_cli=true", table_stdout)

        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-tfhcl-provider-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-module-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-prod-tfvars-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-tfvars-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-import-secret", readback_payload)
        self.assertNotIn("user:pass@", readback_payload)
        self.assertFalse(
            any(record.kind.startswith("terraform.") for record in canonical_nodes)
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )

    def test_storage_loads_feed_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("feed_static_basic")

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
                        "feed-fixture",
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

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("feed.document")
                )
                channel_exit, channel_stdout, channel_stderr = (
                    canonical_nodes("feed.channel")
                )
                item_exit, item_stdout, item_stderr = canonical_nodes("feed.item")
                author_exit, author_stdout, author_stderr = (
                    canonical_nodes("feed.author")
                )
                category_exit, category_stdout, category_stderr = (
                    canonical_nodes("feed.category")
                )

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                references = (
                    json.loads(references_stdout) if references_exit == 0 else []
                )
                item_link_edge = next(
                    (
                        record
                        for record in references
                        if record["source_key"].startswith("feed.item:")
                        and record["target_key"]
                        == "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1"
                    ),
                    None,
                )
                if item_link_edge is not None:
                    explain_exit, explain_stdout, explain_stderr = (
                        run_repo_map_in_process(
                            "storage",
                            "explain-canonical-edge",
                            *storage_args,
                            "--source-key",
                            item_link_edge["source_key"],
                            "--kind",
                            "references",
                            "--target-key",
                            item_link_edge["target_key"],
                            "--json",
                        )
                    )
                else:
                    explain_exit, explain_stdout, explain_stderr = (
                        1,
                        "",
                        "missing feed item link edge",
                    )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "feed.document",
                "feed.channel",
                "feed.item",
                "feed.link",
                "feed.enclosure",
                "feed.author",
                "feed.category",
                "feed.content",
                "feed.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fixture-feed-secret", discover_stdout)
        self.assertNotIn("throw new Error", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {record["canonical_key"] for record in json.loads(document_stdout)}
        self.assertTrue(
            {
                "feed.document:file%3Arss.xml",
                "feed.document:file%3Aatom.xml",
                "feed.document:file%3Afeed.json",
            }.issubset(document_keys)
        )

        self.assertEqual(channel_exit, 0, channel_stderr)
        self.assertGreaterEqual(len(json.loads(channel_stdout)), 3)
        self.assertEqual(item_exit, 0, item_stderr)
        items = json.loads(item_stdout)
        self.assertTrue(any(record["metadata"].get("duplicate_identity") for record in items))
        self.assertTrue(
            any(record["metadata"].get("identity_strength") == "weak" for record in items)
        )
        self.assertEqual(author_exit, 0, author_stderr)
        self.assertGreaterEqual(len(json.loads(author_stdout)), 2)
        self.assertEqual(category_exit, 0, category_stderr)
        self.assertGreaterEqual(len(json.loads(category_stdout)), 2)

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("feed.document:file%3Arss.xml", define_targets)
        self.assertTrue(any(target.startswith("feed.item:") for target in define_targets))

        self.assertEqual(references_exit, 0, references_stderr)
        reference_pairs = {
            (record["source_key"].split(":", 1)[0], record["target_key"])
            for record in references
        }
        self.assertIn(
            (
                "feed.item",
                "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1",
            ),
            reference_pairs,
        )
        self.assertIn(("feed.item", "file:media/rss-audio.mp3"), reference_pairs)
        self.assertTrue(
            any(target.startswith("feed.author:") for _, target in reference_pairs)
        )
        self.assertTrue(
            any(target.startswith("feed.category:") for _, target in reference_pairs)
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1",
        )
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "feed.link",
        )
        self.assertNotIn("fixture-feed-secret", explain_stdout)

    def test_sources_ingest_feed_loads_configured_feed_artifact(self):
        require_postgres_binaries()
        config_path = source_fixture("allowed-rss.toml")
        feed_body = (discovery_fixture("feed_static_basic") / "rss.xml").read_bytes()
        calls = []

        def fetcher(config):
            calls.append(config.url)
            return FeedFetchResponse(
                status=200,
                headers={"content-type": "application/rss+xml"},
                body=feed_body,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir) / "fixture-repo"
            root_path.mkdir()
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                summary = ingest_feed_source(
                    config_path,
                    repository_name="fixture",
                    root_path=root_path,
                    psql_args=postgres.psql_args,
                    psql_command=postgres.psql_command,
                    fetcher=fetcher,
                    clock=fixed_source_clock,
                )
                documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="feed.document",
                    psql_command=postgres.psql_command,
                )
                items = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="feed.item",
                    psql_command=postgres.psql_command,
                )
                references = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="references",
                    psql_command=postgres.psql_command,
                )
                raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(calls, ["https://example.invalid/rss.xml"])
        self.assertEqual(summary.source_id, "example-rss-feed")
        self.assertEqual(summary.load_summary.repository_id, 1)
        self.assertEqual(summary.load_summary.files, 1)
        self.assertEqual(raw_count, str(summary.observations))
        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0].canonical_key.startswith("feed.document:"))
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(
            any(
                edge.source_key.startswith("feed.item:")
                and edge.target_key.startswith("external.url:")
                for edge in references
            )
        )
        source_metadata = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id_configured": "example-rss-feed"', source_metadata)
        self.assertNotIn("fixture-secret", source_metadata)

    def test_sources_import_archive_loads_local_static_artifact_fixture(self):
        require_postgres_binaries()
        config_path = archive_source_fixture("allowed-test-report.toml")
        root_path = source_ingestion_fixture_root()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            summary = import_archive_source(
                config_path,
                repository_name="fixture",
                root_path=root_path,
                psql_args=postgres.psql_args,
                psql_command=postgres.psql_command,
                clock=fixed_source_clock,
            )
            html_documents = query_canonical_node_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="html.document",
                psql_command=postgres.psql_command,
            )
            css_documents = query_canonical_node_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="css.document",
                psql_command=postgres.psql_command,
            )
            config_documents = query_canonical_node_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="config.document",
                psql_command=postgres.psql_command,
            )
            feed_documents = query_canonical_node_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="feed.document",
                psql_command=postgres.psql_command,
            )
            js_files = query_canonical_node_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="js.file",
                psql_command=postgres.psql_command,
            )
            js_summary = query_js_summary(
                postgres.psql_args,
                root_path=str(root_path),
                psql_command=postgres.psql_command,
            )
            references = query_canonical_edge_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="references",
                psql_command=postgres.psql_command,
            )
            styles = query_canonical_edge_records(
                postgres.psql_args,
                root_path=str(root_path),
                kind="styles",
                psql_command=postgres.psql_command,
            )
            html_js_reference = next(
                edge
                for edge in references
                if edge.target_key == (
                    "file:archive_artifacts/example-test-report/static/app.js"
                )
            )
            html_js_explanation = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path=str(root_path),
                source_key=html_js_reference.source_key,
                kind=html_js_reference.edge_kind,
                target_key=html_js_reference.target_key,
                identity_metadata_hash=html_js_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            js_source_map_reference = next(
                edge
                for edge in references
                if edge.target_key == (
                    "file:archive_artifacts/example-test-report/static/app.js.map"
                )
            )
            js_source_map_explanation = query_canonical_edge_explanation(
                postgres.psql_args,
                root_path=str(root_path),
                source_key=js_source_map_reference.source_key,
                kind=js_source_map_reference.edge_kind,
                target_key=js_source_map_reference.target_key,
                identity_metadata_hash=js_source_map_reference.identity_metadata_hash,
                psql_command=postgres.psql_command,
            )
            raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(summary.source_id, "example-test-report")
        self.assertEqual(summary.included_files, 8)
        self.assertEqual(summary.load_summary.files, 8)
        self.assertEqual(raw_count, str(summary.observations))
        self.assertTrue(html_documents)
        self.assertTrue(css_documents)
        self.assertTrue(config_documents)
        self.assertTrue(feed_documents)
        self.assertTrue(js_files)
        self.assertGreaterEqual(js_summary.test_report_asset_files, 1)
        self.assertGreaterEqual(js_summary.source_map_references, 1)
        self.assertTrue(
            any(edge.target_key.startswith("external.url:") for edge in references)
        )
        self.assertIsNotNone(html_js_explanation.edge)
        self.assertTrue(html_js_explanation.evidence)
        self.assertIsNotNone(js_source_map_explanation.edge)
        self.assertTrue(js_source_map_explanation.evidence)
        self.assertTrue(styles)
        source_metadata = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-test-report"', source_metadata)
        self.assertIn('"artifact_manifest_id"', source_metadata)
        self.assertIn('"profile": "test_report_asset"', source_metadata)
        self.assertIn('"not_fetched": true', source_metadata)
        self.assertIn(
            "file:archive_artifacts/example-test-report/static/app.js.map",
            source_metadata,
        )
        explain_payload = json.dumps(
            {
                "html": html_js_explanation.to_dict(),
                "source_map": js_source_map_explanation.to_dict(),
            },
            sort_keys=True,
        )
        self.assertNotIn("fixture-secret", source_metadata)
        self.assertNotIn("fixture-secret", explain_payload)

    def test_sources_import_archive_cli_loads_fixture_and_preserves_json_summary(self):
        require_postgres_binaries()
        config_path = archive_source_fixture("allowed-test-report.toml")
        root_path = source_ingestion_fixture_root()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "sources",
                "import-archive",
                "--config",
                str(config_path),
                "--repository-name",
                "fixture",
                "--root-path",
                str(root_path),
                "--psql-command",
                postgres.psql_command,
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--json",
            )
            raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["source_id"], "example-test-report")
        self.assertEqual(payload["source_type"], "test_report.artifact")
        self.assertEqual(payload["included_files"], 8)
        self.assertEqual(str(payload["observations"]), raw_count)

    def test_sources_import_warc_loads_local_warc_fixture(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = copy_warc_fixture_root(Path(tmpdir))
            config_path = root_path / "warc_sources" / "allowed-warc.toml"
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                summary = import_warc_source(
                    config_path,
                    repository_name="fixture",
                    root_path=root_path,
                    psql_args=postgres.psql_args,
                    psql_command=postgres.psql_command,
                    clock=fixed_source_clock,
                )
                warc_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="warc.document",
                    psql_command=postgres.psql_command,
                )
                warc_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="warc.record",
                    psql_command=postgres.psql_command,
                )
                html_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="html.document",
                    psql_command=postgres.psql_command,
                )
                css_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="css.document",
                    psql_command=postgres.psql_command,
                )
                config_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="config.document",
                    psql_command=postgres.psql_command,
                )
                js_files = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="js.file",
                    psql_command=postgres.psql_command,
                )
                js_summary = query_js_summary(
                    postgres.psql_args,
                    root_path=str(root_path),
                    psql_command=postgres.psql_command,
                )
                references = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(root_path),
                    kind="references",
                    psql_command=postgres.psql_command,
                )
                raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
                warc_reference = next(
                    edge
                    for edge in references
                    if edge.source_key.startswith("warc.record:")
                    and edge.target_key.startswith("external.url:")
                )
                explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(root_path),
                    source_key=warc_reference.source_key,
                    kind=warc_reference.edge_kind,
                    target_key=warc_reference.target_key,
                    identity_metadata_hash=warc_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )
                js_source_map_reference = next(
                    edge
                    for edge in references
                    if edge.target_key.endswith("/record-0005/payload.js.map")
                )
                js_source_map_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=str(root_path),
                    source_key=js_source_map_reference.source_key,
                    kind=js_source_map_reference.edge_kind,
                    target_key=js_source_map_reference.target_key,
                    identity_metadata_hash=js_source_map_reference.identity_metadata_hash,
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(summary.source_id, "example-warc-archive")
        self.assertEqual(summary.record_count, 8)
        self.assertEqual(summary.routed_payloads, 4)
        self.assertEqual(summary.load_summary.files, 4)
        self.assertEqual(raw_count, str(summary.observations))
        self.assertEqual(len(warc_documents), 1)
        self.assertEqual(len(warc_records), 8)
        self.assertTrue(html_documents)
        self.assertTrue(css_documents)
        self.assertTrue(config_documents)
        self.assertTrue(js_files)
        self.assertGreaterEqual(js_summary.saved_page_asset_files, 1)
        self.assertGreaterEqual(js_summary.source_map_references, 1)
        self.assertTrue(
            any(edge.source_key.startswith("warc.record:") for edge in references)
        )
        self.assertIsNotNone(explanation.edge)
        self.assertTrue(explanation.evidence)
        self.assertIsNotNone(js_source_map_explanation.edge)
        self.assertTrue(js_source_map_explanation.evidence)
        source_metadata = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        explain_payload = json.dumps(
            {
                "warc": explanation.to_dict(),
                "source_map": js_source_map_explanation.to_dict(),
            },
            sort_keys=True,
        )
        self.assertIn('"warc_record_key"', source_metadata)
        self.assertIn('"warc_payload_path"', source_metadata)
        self.assertIn('"artifact_extractor_route": "javascript"', source_metadata)
        self.assertIn('"not_fetched": true', source_metadata)
        self.assertNotIn("fixture-secret", source_metadata)
        self.assertNotIn("fixture-secret", explain_payload)

    def test_sources_import_warc_cli_loads_fixture_and_preserves_json_summary(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = copy_warc_fixture_root(Path(tmpdir))
            config_path = root_path / "warc_sources" / "allowed-warc.toml"
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "sources",
                    "import-warc",
                    "--config",
                    str(config_path),
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    str(root_path),
                    "--psql-command",
                    postgres.psql_command,
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--json",
                )
                raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["source_id"], "example-warc-archive")
        self.assertEqual(payload["source_type"], "saved_page.archive")
        self.assertEqual(payload["record_count"], 8)
        self.assertEqual(payload["routed_payloads"], 4)
        self.assertEqual(str(payload["observations"]), raw_count)

    def test_mcp_read_only_source_feed_tools_read_rss2_loaded_rows(self):
        require_postgres_binaries()
        config_path = source_fixture("allowed-rss.toml")
        feed_body = (discovery_fixture("feed_static_basic") / "rss.xml").read_bytes()
        calls = []

        def fetcher(config):
            calls.append(config.url)
            return FeedFetchResponse(
                status=200,
                headers={"content-type": "application/rss+xml"},
                body=feed_body,
            )

        from repomap_kg.mcp_server import (
            repomap_explain_source_feed_item,
            repomap_ingested_sources,
            repomap_source_feed_items,
            repomap_source_references,
            repomap_source_runs,
            repomap_source_summary,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir) / "fixture-repo"
            root_path.mkdir()
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                ingest_feed_source(
                    config_path,
                    repository_name="fixture",
                    root_path=root_path,
                    psql_args=postgres.psql_args,
                    psql_command=postgres.psql_command,
                    fetcher=fetcher,
                    clock=fixed_source_clock,
                )
                mcp_args = {
                    "root_path": str(root_path),
                    "pg_host": str(postgres.socket_dir),
                    "pg_port": str(postgres.port),
                    "pg_user": postgres.user,
                    "pg_database": "postgres",
                    "psql_command": postgres.psql_command,
                }
                sources = repomap_ingested_sources(
                    **mcp_args,
                    source_type="feed.rss",
                )
                summary = repomap_source_summary(
                    **mcp_args,
                    source_id="example-rss-feed",
                )
                runs = repomap_source_runs(
                    **mcp_args,
                    source_id="example-rss-feed",
                )
                items = repomap_source_feed_items(
                    **mcp_args,
                    source_id="example-rss-feed",
                )
                references = repomap_source_references(
                    **mcp_args,
                    source_id="example-rss-feed",
                    target_kind="external.url",
                )
                explanation = repomap_explain_source_feed_item(
                    **mcp_args,
                    item_key=items[0]["item_key"],
                    source_id="example-rss-feed",
                )

        self.assertEqual(calls, ["https://example.invalid/rss.xml"])
        self.assertEqual([record["source_id"] for record in sources], ["example-rss-feed"])
        self.assertEqual(sources[0]["source_type"], "feed.rss")
        self.assertEqual(sources[0]["policy_status"], "allowed_with_limits")
        self.assertGreaterEqual(sources[0]["canonical_feed_item_count"], 1)
        self.assertEqual(summary["source_id"], "example-rss-feed")
        self.assertEqual(summary["feed_documents"], 1)
        self.assertEqual(summary["feed_channels"], 1)
        self.assertGreaterEqual(summary["feed_items"], 1)
        self.assertEqual(runs[0]["source_run_id"], "20260630T120000Z")
        self.assertEqual(runs[0]["http_status"], 200)
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(items[0]["item_key"].startswith("feed.item:"))
        self.assertIn(items[0]["identity_strength"], {"strong", "weak", "structural"})
        self.assertTrue(
            all(reference["not_fetched"] for reference in references),
            references,
        )
        self.assertTrue(
            all(reference["target_key"].startswith("external.url:") for reference in references),
            references,
        )
        self.assertEqual(explanation["item"]["canonical_key"], items[0]["item_key"])
        self.assertEqual(explanation["source"]["source_id"], "example-rss-feed")
        serialized = json.dumps(
            {
                "sources": sources,
                "summary": summary,
                "runs": runs,
                "items": items,
                "references": references,
                "explanation": explanation,
            },
            sort_keys=True,
        )
        self.assertNotIn("fixture-secret", serialized)
        self.assertNotIn("fixture-feed-secret", serialized)

    def test_storage_loads_toml_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("config_toml_basic")

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
                        "toml-config-fixture",
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

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("config.document")
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                        "--kind",
                        "references",
                        "--target-key",
                        "tool:python3",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("cfg2-sensitive-api-key", discover_stdout)
        self.assertNotIn("cfg2-sensitive-token", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn(
            "config.document:file%3Amcp%2Fconfig.toml",
            document_keys,
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Amcp%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Fconfig.toml:%2Ftools%2Frepomap%2Fcommand",
            path_keys,
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "config.document:file%3Amcp%2Fconfig.toml",
            define_targets,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Fconfig.toml:%2Ftools%2Frepomap%2Fpath",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        self.assertIn(
            (
                "config.path:file%3Amcp%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                "tool:python3",
            ),
            {
                (record["source_key"], record["target_key"])
                for record in reference_edges
            },
        )
        self.assertIn(
            "file:bin/tool",
            {record["target_key"] for record in reference_edges},
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {record["target_key"] for record in reference_edges},
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(explanation["edge"]["target_key"], "tool:python3")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("cfg2-sensitive-api-key", explain_stdout)
        self.assertNotIn("cfg2-sensitive-token", explain_stdout)

    def test_storage_loads_yaml_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("yaml_basic")

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
                        "yaml-config-fixture",
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

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("config.document")
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3A.github%2Fworkflows%2Fbuild.yml:%2Fjobs%2Ftest%2Fsteps%2Fcheckout%2Fuses",
                        "--kind",
                        "references",
                        "--target-key",
                        "external:github.action:actions%2Fcheckout%40v4",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("fake-actions-token", discover_stdout)
        self.assertNotIn("fake-kubernetes-password", discover_stdout)
        self.assertNotIn("fake-client-secret", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        documents = json.loads(document_stdout)
        document_keys = {record["canonical_key"] for record in documents}
        self.assertIn("config.document:file%3Aopenapi.yaml", document_keys)
        self.assertTrue(
            any(
                record["metadata"].get("profile") == "github_actions"
                for record in documents
            )
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Aopenapi.yaml:%2Fpaths%2F~1pets%2Fget%2Fresponses%2F200%2F%24ref",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Adocker-compose.yml:%2Fservices%2Fapp%2Fimage",
            path_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn("config.document:file%3Aopenapi.yaml", define_targets)

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        edge_pairs = {
            (record["source_key"], record["target_key"])
            for record in reference_edges
        }
        self.assertIn(
            (
                "config.path:file%3A.github%2Fworkflows%2Fbuild.yml:%2Fjobs%2Ftest%2Fsteps%2Fcheckout%2Fuses",
                "external:github.action:actions%2Fcheckout%40v4",
            ),
            edge_pairs,
        )
        self.assertIn(
            (
                "config.path:file%3Aopenapi.yaml:%2Fpaths%2F~1pets%2Fget%2Fresponses%2F200%2F%24ref",
                "config.path:file%3Aopenapi.yaml:%2Fcomponents%2Fresponses%2FPets",
            ),
            edge_pairs,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "external:github.action:actions%2Fcheckout%40v4",
        )
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("fake-actions-token", explain_stdout)
        self.assertNotIn("fake-kubernetes-password", explain_stdout)
        self.assertNotIn("fake-client-secret", explain_stdout)

    def test_storage_loads_openapi_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = openapi_fixture("openapi1_contracts")

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
                        "openapi-contract-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_openapi_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations
WHERE payload_json->>'kind' LIKE 'openapi.%';
"""
                )
                config_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="config.document",
                    psql_command=postgres.psql_command,
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("fake-openapi-json-password", discover_stdout)
        self.assertNotIn("fake-openapi-json-token", discover_stdout)
        self.assertNotIn("fake-openapi-json-server-secret", discover_stdout)
        self.assertNotIn("fake-openapi-yaml-secret", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
                "openapi.document",
                "openapi.info",
                "openapi.path",
                "openapi.operation",
                "openapi.response",
                "openapi.schema",
                "openapi.component",
                "openapi.reference",
                "openapi.security_scheme",
                "openapi.redaction",
                "openapi.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_openapi = json.loads(raw_openapi_payload)
        raw_payload_text = json.dumps(raw_openapi, sort_keys=True)
        raw_kinds = {record["kind"] for record in raw_openapi}
        spec_families = {
            record.get("metadata", {}).get("spec_family")
            for record in raw_openapi
            if record["kind"] == "openapi.document"
        }
        self.assertIn("openapi3", spec_families)
        self.assertIn("swagger2", spec_families)
        self.assertIn("openapi.reference", raw_kinds)
        self.assertTrue(
            any(
                record.get("metadata", {}).get("reference_scope") == "remote"
                and record.get("metadata", {}).get("not_fetched")
                for record in raw_openapi
            )
        )
        self.assertNotIn("fake-openapi-json-password", raw_payload_text)
        self.assertNotIn("fake-openapi-json-token", raw_payload_text)
        self.assertNotIn("fake-openapi-json-server-secret", raw_payload_text)
        self.assertNotIn("fake-openapi-yaml-secret", raw_payload_text)

        document_keys = {record.canonical_key for record in config_documents}
        self.assertIn("config.document:file%3Aopenapi.json", document_keys)
        self.assertIn("config.document:file%3Aservice.openapi.yaml", document_keys)
        self.assertFalse(
            any(record.kind.startswith("openapi.") for record in canonical_nodes)
        )
        self.assertLessEqual(
            {edge.edge_kind for edge in canonical_edges},
            {"defines", "references"},
        )

    def test_storage_openapi_summary_reads_contract_evidence_without_reload(self):
        require_postgres_binaries()
        fixture_root = openapi_fixture("openapi1_contracts")

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
                        "openapi2-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_count_before = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                summary = query_openapi_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "openapi-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "openapi-summary",
                        *storage_args,
                    )
                )
                raw_count_after = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                config_documents = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    kind="config.document",
                    psql_command=postgres.psql_command,
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(raw_count_before, raw_count_after)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["repository_name"], "openapi2-fixture")
        self.assertEqual(payload["openapi_documents"], 4)
        self.assertEqual(payload["spec_families"]["openapi3"], 2)
        self.assertEqual(payload["spec_families"]["swagger2"], 2)
        self.assertEqual(summary.openapi_documents, 4)
        self.assertEqual(summary.spec_families["openapi3"], 2)
        self.assertGreaterEqual(payload["openapi_observations"], 20)
        self.assertGreaterEqual(payload["openapi"]["paths"], 1)
        self.assertGreaterEqual(payload["openapi"]["operations"], 1)
        self.assertGreaterEqual(payload["openapi"]["responses"], 1)
        self.assertGreaterEqual(payload["openapi"]["schemas"], 1)
        self.assertGreaterEqual(payload["openapi"]["components"], 1)
        self.assertGreaterEqual(payload["openapi"]["security_schemes"], 1)
        self.assertGreaterEqual(payload["openapi"]["examples"], 1)
        self.assertGreaterEqual(payload["methods"]["GET"], 1)
        self.assertGreaterEqual(payload["methods"]["POST"], 1)
        self.assertGreaterEqual(payload["references"]["internal_refs"], 1)
        self.assertGreaterEqual(payload["references"]["local_file_refs"], 1)
        self.assertGreaterEqual(payload["references"]["remote_refs_not_fetched"], 1)
        self.assertGreaterEqual(
            payload["references"]["external_docs_not_fetched"],
            1,
        )
        self.assertGreaterEqual(payload["references"]["refs_not_fetched"], 1)
        self.assertGreaterEqual(payload["redactions"]["credentialed_urls"], 1)
        self.assertGreaterEqual(payload["redactions"]["text_summaries"], 1)
        self.assertGreaterEqual(payload["redactions"]["example_summaries"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["parse_errors"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["malformed_specs"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_documents"], 4)
        self.assertGreaterEqual(payload["generic_config"]["config_paths"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_references"], 1)
        self.assertGreaterEqual(payload["generic_config"]["config_parse_errors"], 1)
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["no_api_calls"])
        self.assertTrue(payload["safety"]["no_tool_execution"])
        self.assertTrue(payload["safety"]["raw_profile_only"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertIn("openapi_documents", table_stdout)
        self.assertIn("openapi3=2", table_stdout)
        self.assertIn("remote_refs_not_fetched", table_stdout)
        self.assertIn("no_fetch=true", table_stdout)

        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-openapi-json-password", readback_payload)
        self.assertNotIn("fake-openapi-json-token", readback_payload)
        self.assertNotIn("fake-openapi-json-server-secret", readback_payload)
        self.assertNotIn("fake-openapi-yaml-secret", readback_payload)
        self.assertNotIn("user:pass@", readback_payload)
        self.assertGreaterEqual(len(config_documents), 4)
        self.assertFalse(
            any(record.kind.startswith("openapi.") for record in canonical_nodes)
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )

    def test_storage_loads_plist_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("xml_plist_chrome_policy_basic")

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
                        "plist-config-fixture",
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

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "config.document"
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:managed/policy.json",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("xml1-fixture-redacted-secret", discover_stdout)
        self.assertNotIn("file:///etc/passwd", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertIn("xml.document", discovered_kinds)
        self.assertTrue(
            any(
                record["kind"] == "config.document"
                and record["path"] == "chrome-policy.plist"
                for record in discovered
            )
        )
        self.assertTrue(
            any(
                record["kind"] == "xml.document"
                and record["path"] == "generic.xml"
                for record in discovered
            )
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn(
            "config.document:file%3Achrome-policy.plist",
            document_keys,
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FManagedBookmarks%2FDocs%2Furl",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2Fapi_key",
            path_keys,
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "config.document:file%3Achrome-policy.plist",
            define_targets,
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FManagedBookmarks%2FDocs%2Furl",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn("file:managed/policy.json", reference_targets)
        self.assertIn("env:CHROME_POLICY_HOME", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fhome",
            reference_targets,
        )
        self.assertIn(
            "unknown:file:repo-escaping-config-reference",
            reference_targets,
        )
        self.assertIn(
            "external:file:absolute-config-reference",
            reference_targets,
        )
        self.assertIn(
            "dynamic:file:config-reference-expanded-from-variable",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(explanation["edge"]["target_key"], "file:managed/policy.json")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("xml1-fixture-redacted-secret", explain_stdout)

    def test_storage_loads_java_spring_maven_xml_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("xml_java_spring_maven_basic")

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
                        "xml-java-spring-maven-fixture",
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

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "xml.document"
                )
                element_exit, element_stdout, element_stderr = canonical_nodes(
                    "xml.element"
                )
                attribute_exit, attribute_stdout, attribute_stderr = canonical_nodes(
                    "xml.attribute"
                )

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean%2Fproperty%5B2%5D:value",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:src/main/resources/config/service.properties",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("xml2-fixture-maven-secret", discover_stdout)
        self.assertNotIn("xml2-fixture-spring-secret", discover_stdout)
        self.assertNotIn("file:///etc/passwd", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "xml.document",
                "xml.element",
                "xml.attribute",
                "xml.reference",
                "xml.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn("xml.document:file%3Apom.xml", document_keys)
        self.assertIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml",
            document_keys,
        )

        self.assertEqual(element_exit, 0, element_stderr)
        element_records = json.loads(element_stdout)
        element_keys = {record["canonical_key"] for record in element_records}
        self.assertIn(
            "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency",
            element_keys,
        )
        dependency_record = next(
            record
            for record in element_records
            if record["canonical_key"]
            == "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency"
        )
        self.assertEqual(
            dependency_record["metadata"]["maven_artifact_id"],
            "spring-context",
        )

        self.assertEqual(attribute_exit, 0, attribute_stderr)
        attribute_keys = {
            record["canonical_key"]
            for record in json.loads(attribute_stdout)
        }
        self.assertIn(
            "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean:class",
            attribute_keys,
        )
        self.assertIn(
            "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean%2Fproperty%5B2%5D:value",
            attribute_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn("xml.document:file%3Apom.xml", define_targets)
        self.assertIn(
            "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn(
            "external.url:https%3A%2F%2Fmaven.apache.org%2Fxsd%2Fmaven-4.0.0.xsd",
            reference_targets,
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fwww.springframework.org%2Fschema%2Fbeans%2Fspring-beans.xsd",
            reference_targets,
        )
        self.assertIn("file:src/main/resources/config/service.properties", reference_targets)
        self.assertIn("env:DB_PASSWORD", reference_targets)
        self.assertIn(
            "dynamic:xml.property-placeholder:spring-maven-property",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "file:src/main/resources/config/service.properties",
        )
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "xml.reference",
        )
        self.assertNotIn("xml2-fixture-maven-secret", explain_stdout)
        self.assertNotIn("xml2-fixture-spring-secret", explain_stdout)

    def test_storage_loads_static_html_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("html_static_basic")

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
                        "html-static-fixture",
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

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "html.document"
                )
                element_exit, element_stdout, element_stderr = canonical_nodes(
                    "html.element"
                )
                anchor_exit, anchor_stdout, anchor_stderr = canonical_nodes(
                    "html.anchor"
                )

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                external_explain_exit, external_explain_stdout, external_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D",
                        "--kind",
                        "references",
                        "--target-key",
                        "external.url:https%3A%2F%2Fexample.com%2Fdocs",
                        "--json",
                    )
                )
                asset_explain_exit, asset_explain_stdout, asset_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "html.element:file%3Aindex.html:%2Fhtml%2Fhead%2Flink",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:assets/site.css",
                        "--json",
                    )
                )
                form_explain_exit, form_explain_stdout, form_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fform",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:submit/login",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("html1-sensitive-password", discover_stdout)
        self.assertNotIn("html1-js-should-not-leak", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "html.document",
                "html.element",
                "html.heading",
                "html.link",
                "html.asset",
                "html.form",
                "html.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn("html.document:file%3Aindex.html", document_keys)
        self.assertIn("html.document:file%3Abroken.html", document_keys)

        self.assertEqual(element_exit, 0, element_stderr)
        element_keys = {record["canonical_key"] for record in json.loads(element_stdout)}
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D",
            element_keys,
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fsection%2Fp%5B2%5D",
            element_keys,
        )

        self.assertEqual(anchor_exit, 0, anchor_stderr)
        anchor_keys = {record["canonical_key"] for record in json.loads(anchor_stdout)}
        self.assertIn("html.anchor:file%3Aindex.html:welcome", anchor_keys)

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn("html.document:file%3Aindex.html", define_targets)
        self.assertIn("html.anchor:file%3Aindex.html:welcome", define_targets)

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn("html.anchor:file%3Aindex.html:welcome", reference_targets)
        self.assertIn("file:assets/site.css", reference_targets)
        self.assertIn("file:assets/app.js", reference_targets)
        self.assertIn("file:images/logo.png", reference_targets)
        self.assertIn("file:submit/login", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            reference_targets,
        )
        self.assertIn("external.url:mailto%3Adev%40example.com", reference_targets)
        self.assertIn("dynamic:url:javascript-url", reference_targets)

        self.assertEqual(external_explain_exit, 0, external_explain_stderr)
        external_explanation = json.loads(external_explain_stdout)
        self.assertEqual(external_explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            external_explanation["evidence"][0]["raw_observation"]["kind"],
            "html.link",
        )

        self.assertEqual(asset_explain_exit, 0, asset_explain_stderr)
        asset_explanation = json.loads(asset_explain_stdout)
        self.assertEqual(asset_explanation["edge"]["target_key"], "file:assets/site.css")
        self.assertEqual(
            asset_explanation["evidence"][0]["raw_observation"]["kind"],
            "html.asset",
        )

        self.assertEqual(form_explain_exit, 0, form_explain_stderr)
        form_explanation = json.loads(form_explain_stdout)
        self.assertEqual(form_explanation["edge"]["target_key"], "file:submit/login")
        self.assertEqual(
            form_explanation["evidence"][0]["raw_observation"]["kind"],
            "html.form",
        )
        self.assertNotIn("html1-sensitive-password", form_explain_stdout)

    def test_storage_loads_docs1_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("docs_text_table_basic")

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
                        "docs1-fixture",
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

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "document.file"
                )
                section_exit, section_stdout, section_stderr = canonical_nodes(
                    "document.section"
                )
                table_exit, table_stdout, table_stderr = canonical_nodes(
                    "document.table"
                )
                column_exit, column_stdout, column_stderr = canonical_nodes(
                    "document.column"
                )
                command_exit, command_stdout, command_stderr = canonical_nodes(
                    "document.latex_command"
                )

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A2",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:chapter.tex",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("docs1-sensitive-secret", discover_stdout)
        self.assertNotIn("acct-docs1-redacted", discover_stdout)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "document.text_document",
                "document.text_section",
                "document.table_document",
                "document.table_column",
                "document.latex_document",
                "document.latex_section",
                "document.latex_command",
                "document.reference",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {record["canonical_key"] for record in json.loads(document_stdout)}
        self.assertIn("document.file:file%3Anotes.txt", document_keys)
        self.assertIn("document.file:file%3Adata.csv", document_keys)
        self.assertIn("document.file:file%3Apaper.tex", document_keys)

        self.assertEqual(section_exit, 0, section_stderr)
        section_keys = {record["canonical_key"] for record in json.loads(section_stdout)}
        self.assertIn(
            "document.section:file%3Anotes.txt:%2Fsections%2Foverview",
            section_keys,
        )
        self.assertIn(
            "document.section:file%3Apaper.tex:%2Fsections%2F1-intro",
            section_keys,
        )

        self.assertEqual(table_exit, 0, table_stderr)
        table_keys = {record["canonical_key"] for record in json.loads(table_stdout)}
        self.assertIn("document.table:file%3Adata.csv:%2Ftable", table_keys)

        self.assertEqual(column_exit, 0, column_stderr)
        column_payload = json.loads(column_stdout)
        column_keys = {record["canonical_key"] for record in column_payload}
        self.assertIn(
            "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            column_keys,
        )
        self.assertTrue(
            any(record["metadata"].get("redacted") for record in column_payload)
        )

        self.assertEqual(command_exit, 0, command_stderr)
        command_keys = {record["canonical_key"] for record in json.loads(command_stdout)}
        self.assertIn(
            "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A2",
            command_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("document.file:file%3Anotes.txt", define_targets)
        self.assertIn("document.table:file%3Adata.csv:%2Ftable", define_targets)
        self.assertIn(
            "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_targets = {
            record["target_key"]
            for record in json.loads(references_stdout)
        }
        self.assertIn("file:chapter.tex", reference_targets)
        self.assertIn("file:figures/diagram.png", reference_targets)
        self.assertIn("file:references.bib", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fpaper",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "document.reference",
        )
        self.assertNotIn("docs1-sensitive-secret", explain_stdout)
        self.assertNotIn("acct-docs1-redacted", explain_stdout)

    def test_storage_loads_docs2_odf_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("docs_odf_basic")

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
                        "docs2-fixture",
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

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "document.file"
                )
                section_exit, section_stdout, section_stderr = canonical_nodes(
                    "document.section"
                )
                table_exit, table_stdout, table_stderr = canonical_nodes(
                    "document.table"
                )
                sheet_exit, sheet_stdout, sheet_stderr = canonical_nodes(
                    "document.sheet"
                )
                column_exit, column_stdout, column_stderr = canonical_nodes(
                    "document.column"
                )

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
                        "--kind",
                        "references",
                        "--target-key",
                        "external.url:https%3A%2F%2Fexample.com%2Fdocs2",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("docs2-sensitive-secret", discover_stdout)
        self.assertNotIn("docs2-cell-secret", discover_stdout)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "document.odf_document",
                "document.odf_text",
                "document.odf_table",
                "document.odf_sheet",
                "document.odf_column",
                "document.reference",
                "document.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {record["canonical_key"] for record in json.loads(document_stdout)}
        self.assertIn("document.file:file%3Anotes.odt", document_keys)
        self.assertIn("document.file:file%3Aspreadsheet.ods", document_keys)

        self.assertEqual(section_exit, 0, section_stderr)
        section_keys = {record["canonical_key"] for record in json.loads(section_stdout)}
        self.assertIn(
            "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
            section_keys,
        )

        self.assertEqual(table_exit, 0, table_stderr)
        table_keys = {record["canonical_key"] for record in json.loads(table_stdout)}
        self.assertIn("document.table:file%3Anotes.odt:%2Ftables%2Ftasks", table_keys)

        self.assertEqual(sheet_exit, 0, sheet_stderr)
        sheet_keys = {record["canonical_key"] for record in json.loads(sheet_stdout)}
        self.assertIn(
            "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            sheet_keys,
        )

        self.assertEqual(column_exit, 0, column_stderr)
        column_payload = json.loads(column_stdout)
        column_keys = {record["canonical_key"] for record in column_payload}
        self.assertIn(
            "document.column:file%3Aspreadsheet.ods:"
            "%2Fsheets%2Fbudget%2Fcolumns%2Famount",
            column_keys,
        )
        self.assertTrue(
            any(record["metadata"].get("redacted") for record in column_payload)
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("document.file:file%3Anotes.odt", define_targets)
        self.assertIn(
            "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_targets = {
            record["target_key"]
            for record in json.loads(references_stdout)
        }
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs2",
            reference_targets,
        )
        self.assertIn(
            "unknown:document.reference:odf-internal-package-part",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "document.reference",
        )
        self.assertNotIn("docs2-sensitive-secret", explain_stdout)
        self.assertNotIn("docs2-cell-secret", explain_stdout)

    def test_storage_loads_static_css_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("css_static_basic")

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
                        "css-static-fixture",
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

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "css.document"
                )
                rule_exit, rule_stdout, rule_stderr = canonical_nodes("css.rule")
                selector_exit, selector_stdout, selector_stderr = canonical_nodes(
                    "css.selector"
                )
                custom_exit, custom_stdout, custom_stderr = canonical_nodes(
                    "css.custom_property"
                )

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        (
                            "css.rule:"
                            "file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:"
                            "%2Frule%3A2"
                        ),
                        "--kind",
                        "references",
                        "--target-key",
                        "file:tools/test/assets/panel.svg",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("fixture-secret-token", discover_stdout)
        self.assertNotIn("PHNlY3JldD4=", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "css.document",
                "css.rule",
                "css.selector",
                "css.declaration",
                "css.custom_property",
                "css.reference",
                "css.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn(
            "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css",
            document_keys,
        )

        self.assertEqual(rule_exit, 0, rule_stderr)
        rule_keys = {record["canonical_key"] for record in json.loads(rule_stdout)}
        self.assertIn(
            "css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A2",
            rule_keys,
        )

        self.assertEqual(selector_exit, 0, selector_stderr)
        selector_keys = {
            record["canonical_key"]
            for record in json.loads(selector_stdout)
        }
        self.assertIn(
            (
                "css.selector:"
                "file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:"
                "%2Frule%3A3%2Fselector%3A9"
            ),
            selector_keys,
        )

        self.assertEqual(custom_exit, 0, custom_stderr)
        custom_keys = {
            record["canonical_key"]
            for record in json.loads(custom_stdout)
        }
        self.assertIn(
            "css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface",
            custom_keys,
        )
        self.assertIn(
            "css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--api-token",
            custom_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css",
            define_targets,
        )
        self.assertIn(
            "css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_targets = {
            record["target_key"]
            for record in json.loads(references_stdout)
        }
        self.assertIn("file:tools/test/report/static/reset.css", reference_targets)
        self.assertIn("file:tools/test/assets/panel.svg", reference_targets)
        self.assertIn("unknown:file:repo-escaping-css-reference", reference_targets)
        self.assertIn("dynamic:file:css-url-dynamic", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fassets%2Freport.png",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "file:tools/test/assets/panel.svg",
        )
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "css.reference",
        )
        self.assertNotIn("fixture-secret-token", explain_stdout)
        self.assertNotIn("PHNlY3JldD4=", explain_stdout)

    def test_storage_loads_css_html_selector_matches_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("css_html_matching_basic")

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
                        "css-html-matching-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "canonical-edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--json",
                    )

                styles_exit, styles_stdout, styles_stderr = canonical_edges("styles")
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        (
                            "css.selector:"
                            "file%3Astatic%2Freport.css:"
                            "%2Frule%3A1%2Fselector%3A1"
                        ),
                        "--kind",
                        "styles",
                        "--target-key",
                        (
                            "html.element:"
                            "file%3Aindex.html:"
                            "%2Fhtml%2Fbody%2Fheader%2Fspan"
                        ),
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        self.assertIn(
            "css.selector_match",
            {record["kind"] for record in discovered},
        )
        self.assertFalse(
            any(
                record["kind"] == "css.selector_match"
                and record["metadata"]["css_file"] == "static/unlinked.css"
                for record in discovered
            )
        )
        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(styles_exit, 0, styles_stderr)
        style_edges = json.loads(styles_stdout)
        style_pairs = {
            (record["source_key"], record["target_key"])
            for record in style_edges
        }
        self.assertIn(
            (
                (
                    "css.selector:"
                    "file%3Astatic%2Freport.css:"
                    "%2Frule%3A1%2Fselector%3A1"
                ),
                (
                    "html.element:"
                    "file%3Aindex.html:"
                    "%2Fhtml%2Fbody%2Fheader%2Fspan"
                ),
            ),
            style_pairs,
        )
        self.assertTrue(
            all(record["metadata"]["not_runtime_style_observed"] for record in style_edges)
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)
        self.assertEqual(explanation["edge"]["edge_kind"], "styles")
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "css.selector_match",
        )
        self.assertTrue(explanation["edge"]["metadata"]["not_runtime_style_observed"])

    def test_storage_loads_codex_mcp_config_dogfood_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("config_codex_mcp_dogfood")

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
                        "codex-mcp-config-dogfood",
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

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("config.document")
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

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
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )

                tool_explain_exit, tool_explain_stdout, tool_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                        "--kind",
                        "references",
                        "--target-key",
                        "tool:repomap-kg",
                        "--json",
                    )
                )
                file_explain_exit, file_explain_stdout, file_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fconfig_path",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:codex/config.toml",
                        "--json",
                    )
                )
                env_explain_exit, env_explain_stdout, env_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fenv%2FREPOMAP_MCP_CONFIG",
                        "--kind",
                        "references",
                        "--target-key",
                        "env:REPOMAP_MCP_CONFIG",
                        "--json",
                    )
                )

        for secret in (
            "cfg3-json-secret-token",
            "cfg3-json-secret-api-key",
            "cfg3-toml-secret-refresh-token",
            "cfg3-toml-secret-api-key",
            "cfg3-jsonl-secret-token",
            "cfg3-jsonc-secret-password",
        ):
            self.assertNotIn(secret, discover_stdout)
            self.assertNotIn(secret, document_stdout)
            self.assertNotIn(secret, path_stdout)
            self.assertNotIn(secret, references_stdout)
            self.assertNotIn(secret, tool_explain_stdout)
            self.assertNotIn(secret, file_explain_stdout)
            self.assertNotIn(secret, env_explain_stdout)

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.jsonl_record",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )
        parse_errors = [
            record
            for record in discovered
            if record["kind"] == "config.parse_error"
        ]
        self.assertEqual(
            [(record["path"], record["metadata"]["error_kind"]) for record in parse_errors],
            [("logs/events.jsonl", "malformed-jsonl-line")],
        )
        self.assertEqual(
            sum(1 for record in discovered if record["kind"] == "config.jsonl_record"),
            3,
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertEqual(
            document_keys,
            {
                "config.document:file%3Acodex%2Fconfig.toml",
                "config.document:file%3Aeditor%2Fsettings.jsonc",
                "config.document:file%3Alogs%2Fevents.jsonl",
                "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
            },
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertTrue(
            {
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fconfig_path",
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fenv%2FREPOMAP_MCP_CONFIG",
                "config.path:file%3Acodex%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                "config.path:file%3Aeditor%2Fsettings.jsonc:%2Fconfig_path",
                "config.path:file%3Alogs%2Fevents.jsonl:%2Fcommand",
            }.issubset(path_keys)
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertTrue(document_keys.issubset(define_targets))
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_pairs = {
            (record["source_key"], record["target_key"])
            for record in reference_edges
        }
        self.assertTrue(
            {
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                    "tool:repomap-kg",
                ),
                (
                    "config.path:file%3Acodex%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                    "tool:python3",
                ),
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fconfig_path",
                    "file:codex/config.toml",
                ),
                (
                    "config.path:file%3Aeditor%2Fsettings.jsonc:%2Fconfig_path",
                    "file:mcp/repo-map/config.json",
                ),
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fenv%2FREPOMAP_MCP_CONFIG",
                    "env:REPOMAP_MCP_CONFIG",
                ),
            }.issubset(reference_pairs)
        )
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn("unknown:file:repo-escaping-config-reference", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Frepo-map",
            reference_targets,
        )

        self.assertEqual(tool_explain_exit, 0, tool_explain_stderr)
        tool_explanation = json.loads(tool_explain_stdout)
        self.assertEqual(tool_explanation["edge"]["edge_kind"], "references")
        self.assertEqual(tool_explanation["edge"]["target_key"], "tool:repomap-kg")
        self.assertEqual(
            tool_explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )

        self.assertEqual(file_explain_exit, 0, file_explain_stderr)
        file_explanation = json.loads(file_explain_stdout)
        self.assertEqual(file_explanation["edge"]["target_key"], "file:codex/config.toml")
        self.assertEqual(
            file_explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )

        self.assertEqual(env_explain_exit, 0, env_explain_stderr)
        env_explanation = json.loads(env_explain_stdout)
        self.assertEqual(env_explanation["edge"]["target_key"], "env:REPOMAP_MCP_CONFIG")
        self.assertGreaterEqual(len(env_explanation["evidence"]), 1)
        self.assertTrue(
            {
                evidence["raw_observation"]["kind"]
                for evidence in env_explanation["evidence"]
            }.issubset({"config.reference"})
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
                "repomap_ingested_sources",
                "repomap_source_summary",
                "repomap_source_runs",
                "repomap_source_feed_items",
                "repomap_explain_source_feed_item",
                "repomap_source_references",
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
                "--legacy",
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
            canonical_exit_code, canonical_stdout, canonical_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "nodes",
                    "--root-path",
                    "/tmp/fixture",
                    "--kind",
                    "file",
                    "--canonical-key",
                    "file:bin/tool",
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
            direct_canonical_exit_code, direct_canonical_stdout, (
                direct_canonical_stderr
            ) = run_repo_map_in_process(
                "storage",
                "canonical-nodes",
                "--root-path",
                "/tmp/fixture",
                "--kind",
                "file",
                "--canonical-key",
                "file:bin/tool",
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
                "--legacy",
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
        self.assertEqual(canonical_exit_code, 0, canonical_stderr)
        self.assertEqual(direct_canonical_exit_code, 0, direct_canonical_stderr)
        self.assertEqual(
            json.loads(canonical_stdout),
            json.loads(direct_canonical_stdout),
            direct_canonical_stderr,
        )
        canonical_payload = json.loads(canonical_stdout)
        self.assertEqual(canonical_payload[0]["canonical_key"], "file:bin/tool")
        self.assertNotIn("node_stable_key", canonical_payload[0])
        self.assertNotIn("id", canonical_payload[0])
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
                "--legacy",
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
            canonical_exit_code, canonical_stdout, canonical_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "edges",
                    "--root-path",
                    "/tmp/fixture",
                    "--kind",
                    "executes",
                    "--source-key",
                    "file:bin/tool",
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
                    "--json",
                )
            )
            direct_canonical_exit_code, direct_canonical_stdout, (
                direct_canonical_stderr
            ) = run_repo_map_in_process(
                "storage",
                "canonical-edges",
                "--root-path",
                "/tmp/fixture",
                "--kind",
                "executes",
                "--source-key",
                "file:bin/tool",
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
                "--json",
            )
            text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                "storage",
                "edges",
                "--legacy",
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
        self.assertEqual(canonical_exit_code, 0, canonical_stderr)
        self.assertEqual(direct_canonical_exit_code, 0, direct_canonical_stderr)
        self.assertEqual(
            json.loads(canonical_stdout),
            json.loads(direct_canonical_stdout),
        )
        canonical_payload = json.loads(canonical_stdout)
        self.assertEqual(canonical_payload[0]["source_key"], "file:bin/tool")
        self.assertEqual(canonical_payload[0]["edge_kind"], "executes")
        self.assertEqual(canonical_payload[0]["target_key"], "tool:nix")
        self.assertNotIn("edge_stable_key", canonical_payload[0])
        self.assertNotIn("id", canonical_payload[0])
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


def openapi_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "openapi" / name


def terraform_hcl_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "terraform_hcl" / name


def python_ecosystem_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "python_ecosystem" / name


def python_web_fixture() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "python_web"


def source_fixture(filename: str) -> Path:
    return (
        Path(__file__).parents[3]
        / "fixtures"
        / "source_ingestion"
        / "feed_sources"
        / filename
    )


def archive_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "archive_sources" / filename


def warc_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "warc_sources" / filename


def copy_warc_fixture_root(parent: Path) -> Path:
    root = parent / "source_ingestion"
    root.mkdir()
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_artifacts",
        root / "warc_artifacts",
    )
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_sources",
        root / "warc_sources",
    )
    return root


def source_ingestion_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "source_ingestion"


def bulk_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "bulk"


def api_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "api"


def github_api_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "github_api"


def fixed_source_clock() -> datetime:
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


def run_repo_map_in_process(*args):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(list(args))
    return exit_code, stdout.getvalue(), stderr.getvalue()


class MockedGitHubRestTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def fetch(self, config, request):
        self.requests.append((config, request))
        return self.responses.pop(0)


if __name__ == "__main__":
    unittest.main()
