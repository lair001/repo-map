import subprocess
import tempfile
import unittest
import hashlib
import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    EdgeRecord,
    FileNodeRecord,
    FileNeighborhoodRecord,
    NeighborhoodRecord,
    NodeRecord,
    StorageSummaryRecord,
    StorageSchemaError,
    build_file_neighborhood_query_sql,
    build_neighborhood_query_sql,
    build_node_query_sql,
    build_storage_summary_query_sql,
    build_host_mutator_query_sql,
    build_edge_query_sql,
    apply_migrations,
    build_file_ingest_sql,
    build_file_node_query_sql,
    build_file_query_sql,
    default_rdbms_root,
    discover_migrations,
    format_edge_table,
    format_file_node_table,
    format_file_neighborhood_table,
    format_neighborhood_table,
    format_node_table,
    format_storage_summary_table,
    file_rows_from_observations,
    query_edge_records,
    query_file_node_records,
    query_file_records,
    query_file_neighborhood,
    query_neighborhood,
    query_node_records,
    query_storage_summary,
    query_host_mutator_records,
    relationship_rows_from_observations,
    load_file_observations,
    build_canonical_ingest_sql,
    canonical_rows_from_result,
    identity_metadata_hash,
    raw_observation_payload_hash,
    raw_observation_rows_from_observations,
)


class StorageUnitTests(unittest.TestCase):
    def test_default_rdbms_root_points_to_main_resources(self):
        root = default_rdbms_root()

        self.assertEqual(root.name, "rdbms")
        self.assertEqual(root.parent.name, "resources")

    def test_discover_migrations_reads_include_all_and_changesets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )
            migration.write_text(
                """
--liquibase formatted sql
--changeset slair:2026_06_28-001-core-create_graph_tables
CREATE TABLE repositories(id BIGSERIAL PRIMARY KEY);
"""
            )

            migrations = discover_migrations(root)

        self.assertEqual(len(migrations), 1)
        self.assertEqual(migrations[0].path, migration)
        self.assertEqual(
            migrations[0].changeset_id,
            "slair:2026_06_28-001-core-create_graph_tables",
        )

    def test_discover_migrations_rejects_unformatted_sql(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )
            migration.write_text("CREATE TABLE repositories(id BIGINT);\n")

            with self.assertRaisesRegex(StorageSchemaError, "formatted sql"):
                discover_migrations(root)

    def test_discover_migrations_rejects_missing_include_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            root.mkdir()
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )

            with self.assertRaisesRegex(StorageSchemaError, "missing includeAll"):
                discover_migrations(root)

    def test_discover_migrations_rejects_missing_changeset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )
            migration.write_text("--liquibase formatted sql\nSELECT 1;\n")

            with self.assertRaisesRegex(StorageSchemaError, "missing a changeset"):
                discover_migrations(root)

    def test_apply_migrations_runs_psql_for_discovered_sql_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: "2026"
      relativeToChangelogFile: true
"""
            )
            migration.write_text(
                """
--liquibase formatted sql
--changeset slair:2026_06_28-001-core-create_graph_tables
SELECT 1;
"""
            )

            with patch("repomap_kg.storage.subprocess.run") as run:
                migrations = apply_migrations(
                    root, ["-d", "postgres"], psql_command="/bin/psql"
                )

        self.assertEqual(migrations[0].path, migration)
        run.assert_called_once_with(
            [
                "/bin/psql",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                str(migration),
            ],
            check=True,
            stdout=-1,
            stderr=-1,
            text=True,
        )

    def test_apply_migrations_wraps_psql_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: "2026"
      relativeToChangelogFile: true
"""
            )
            migration.write_text(
                """
--liquibase formatted sql
--changeset slair:2026_06_28-001-core-create_graph_tables
SELECT 1;
"""
            )
            error = subprocess.CalledProcessError(
                2,
                ["/bin/psql"],
                output="",
                stderr="relation already exists\n",
            )

            with patch("repomap_kg.storage.subprocess.run", side_effect=error):
                with self.assertRaisesRegex(
                    StorageSchemaError,
                    "relation already exists",
                ):
                    apply_migrations(root, ["-d", "postgres"], psql_command="/bin/psql")

    def test_file_rows_from_observations_preserves_file_metadata(self):
        observation = RawObservation(
            kind="file",
            source_id="src/app.py",
            path="src/app.py",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "python",
                "role": "source",
                "content_hash": "a" * 64,
                "generated": False,
                "executable": False,
            },
        )
        non_file = RawObservation(
            kind="shell.command",
            source_id="scripts/build.sh#call:echo",
            path="scripts/build.sh",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            target="tool:echo",
        )

        rows = file_rows_from_observations([non_file, observation])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].path, "src/app.py")
        self.assertEqual(rows[0].content_hash, "a" * 64)
        self.assertEqual(rows[0].metadata_json["confidence"], "manual")
        self.assertEqual(rows[0].metadata_json["raw_source_id"], "src/app.py")

    def test_relationship_rows_from_observations_preserves_edge_metadata(self):
        observation = RawObservation(
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
        )

        rows = relationship_rows_from_observations([observation])

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0].src_node_stable_key,
            "node:bin/tool:shell.command:bin/tool#call:nix-build",
        )
        self.assertEqual(rows[0].dst_node_stable_key, "tool:nix")
        self.assertEqual(
            rows[0].edge_stable_key,
            "edge:node:bin/tool:shell.command:bin/tool#call:nix-build:"
            "shell.command:tool:nix",
        )
        self.assertEqual(
            rows[0].evidence_stable_key,
            "evidence:bin/tool:2-2:fixture-shell:bin/tool#call:nix-build",
        )

    def test_raw_observation_payload_hash_uses_canonical_json(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"role": "documentation", "language": "markdown"},
        )

        digest = raw_observation_payload_hash(observation)

        expected = hashlib.sha256(
            json.dumps(
                observation.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest, expected)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_identity_metadata_hash_is_stable_for_key_order(self):
        left = {"b": ["two", "values"], "a": {"nested": True}}
        right = {"a": {"nested": True}, "b": ["two", "values"]}

        self.assertEqual(identity_metadata_hash(left), identity_metadata_hash(right))
        self.assertRegex(identity_metadata_hash(left), r"^[0-9a-f]{64}$")

    def test_canonical_rows_from_result_resolves_edge_links_by_identity(self):
        observations = [
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
                metadata={"command": "nix", "argv": ["nix", "build"]},
            )
        ]
        result = canonicalize_observations(observations)

        rows = canonical_rows_from_result(result)

        self.assertEqual(len(rows.nodes), 2)
        self.assertEqual(len(rows.edges), 1)
        self.assertEqual(rows.edges[0].source_key, "file:bin/tool")
        self.assertEqual(rows.edges[0].edge_kind, "executes")
        self.assertEqual(rows.edges[0].target_key, "tool:nix")
        self.assertEqual(rows.edge_evidence_links[0].source_key, "file:bin/tool")
        self.assertEqual(rows.edge_evidence_links[0].edge_kind, "executes")
        self.assertEqual(rows.edge_evidence_links[0].target_key, "tool:nix")
        self.assertEqual(
            rows.edge_evidence_links[0].identity_metadata_hash,
            rows.edges[0].identity_metadata_hash,
        )

    def test_build_canonical_ingest_sql_uses_raw_and_canonical_tables(self):
        observations = [
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
                metadata={"command": "nix", "argv": ["nix", "build"]},
            )
        ]
        raw_rows = raw_observation_rows_from_observations(observations)
        canonical_rows = canonical_rows_from_result(canonicalize_observations(observations))

        sql = build_canonical_ingest_sql(
            raw_rows,
            canonical_rows,
            repository_name="fixture",
            root_path="/tmp/fixture",
            git_commit="abc123",
        )

        self.assertIn("INSERT INTO raw_observations(", sql)
        self.assertIn("raw observation payload hash mismatch", sql)
        self.assertIn("INSERT INTO canonical_nodes(", sql)
        self.assertIn("INSERT INTO canonical_edges(", sql)
        self.assertIn("INSERT INTO canonical_evidence(", sql)
        self.assertIn("INSERT INTO canonical_edge_evidence(", sql)
        self.assertIn("source_canonical_key = 'file:bin/tool'", sql)
        self.assertNotIn("canonical_edge_id = 'canonical-edge:", sql)

    def test_build_file_ingest_sql_quotes_values_and_sets_run(self):
        rows = file_rows_from_observations(
            [
                RawObservation(
                    kind="file",
                    source_id="docs/it's.md",
                    path="docs/it's.md",
                    confidence="manual",
                    extractor="fixture-discovery",
                    extractor_version="0.1.0",
                    metadata={
                        "language": "markdown",
                        "role": "documentation",
                        "content_hash": None,
                        "generated": False,
                        "executable": False,
                    },
                )
            ]
        )

        sql = build_file_ingest_sql(
            rows,
            repository_name="fixture's repo",
            root_path="/tmp/fixture",
            git_commit="abc123",
        )

        self.assertIn("fixture''s repo", sql)
        self.assertIn("docs/it''s.md", sql)
        self.assertIn("last_seen_run_id", sql)
        self.assertIn('"confidence": "manual"', sql)
        self.assertIn("INSERT INTO nodes(", sql)
        self.assertIn("node:docs/it''s.md:file:docs/it''s.md", sql)
        self.assertIn("INSERT INTO evidence(", sql)
        self.assertIn(
            "evidence:docs/it''s.md:0-0:fixture-discovery:docs/it''s.md",
            sql,
        )

    def test_load_file_observations_builds_relationship_edge_sql(self):
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
                    "content_hash": "a" * 64,
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
        completed = SimpleNamespace(
            stdout='{"repository_id": 7, "run_id": 11, "files": 1}\n'
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            load_file_observations(
                ["-d", "postgres"],
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        sql = run.call_args.kwargs["input"]
        self.assertEqual(sql.count("BEGIN;"), 1)
        self.assertEqual(sql.count("COMMIT;"), 1)
        self.assertIn("INSERT INTO edges(", sql)
        self.assertIn("edge:node:bin/tool:shell.command:bin/tool#call:nix-build", sql)
        self.assertIn("tool:nix", sql)
        self.assertIn("INSERT INTO raw_observations(", sql)
        self.assertIn("INSERT INTO canonical_nodes(", sql)
        self.assertIn("INSERT INTO canonical_edges(", sql)
        self.assertIn("INSERT INTO canonical_evidence(", sql)
        self.assertIn("INSERT INTO canonical_node_evidence(", sql)
        self.assertIn("INSERT INTO canonical_edge_evidence(", sql)
        self.assertIn("'files', 1", sql)
        self.assertNotIn("'canonical_nodes',", sql)

    def test_load_file_observations_returns_psql_summary(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="extracted",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": False,
            },
        )
        completed = SimpleNamespace(
            stdout='{"repository_id": 7, "run_id": 11, "files": 1}\n'
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = load_file_observations(
                ["-d", "postgres"],
                [observation],
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_id, 7)
        self.assertEqual(summary.run_id, 11)
        self.assertEqual(summary.files, 1)
        self.assertIn("-qAt", run.call_args.args[0])

    def test_load_file_observations_rejects_canonicalization_errors_before_psql(self):
        observation = RawObservation(
            kind="file",
            source_id="../outside",
            path="../outside",
            confidence="extracted",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "text",
                "role": "documentation",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": False,
            },
        )

        with patch("repomap_kg.storage.subprocess.run") as run:
            with self.assertRaisesRegex(StorageSchemaError, "canonicalization failed"):
                load_file_observations(
                    ["-d", "postgres"],
                    [observation],
                    repository_name="fixture",
                    root_path="/tmp/fixture",
                )

        run.assert_not_called()

    def test_load_file_observations_wraps_psql_failures(self):
        error = subprocess.CalledProcessError(
            2,
            ["/bin/psql"],
            output="",
            stderr="database does not exist\n",
        )

        with patch("repomap_kg.storage.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(StorageSchemaError, "database does not exist"):
                load_file_observations(
                    ["-d", "missing"],
                    [],
                    repository_name="fixture",
                    root_path="/tmp/fixture",
                )

    def test_load_file_observations_rejects_invalid_summary_json(self):
        completed = SimpleNamespace(stdout="{bad json}\n")

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "load summary"):
                load_file_observations(
                    ["-d", "postgres"],
                    [],
                    repository_name="fixture",
                    root_path="/tmp/fixture",
                )

    def test_load_file_observations_rejects_malformed_summary_json(self):
        completed = SimpleNamespace(stdout='{"repository_id": 7}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "malformed load summary"):
                load_file_observations(
                    ["-d", "postgres"],
                    [],
                    repository_name="fixture",
                    root_path="/tmp/fixture",
                )

    def test_query_file_records_returns_file_records(self):
        completed = SimpleNamespace(
            stdout=(
                "["
                '{"path":"README.md","language":"markdown",'
                '"role":"documentation","confidence":"manual",'
                '"generated":false,"executable":false},'
                '{"path":"bin/tool","language":"shell",'
                '"role":"entrypoint","confidence":"extracted",'
                '"generated":false,"executable":true}'
                "]\n"
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_file_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual([record.path for record in records], ["README.md", "bin/tool"])
        self.assertEqual(records[0].role, "documentation")
        self.assertTrue(records[1].executable)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "repositories.root_path = '/tmp/fixture'",
            run.call_args.kwargs["input"],
        )

    def test_query_file_records_wraps_psql_failures(self):
        error = subprocess.CalledProcessError(
            2,
            ["/bin/psql"],
            output="",
            stderr="connection refused\n",
        )

        with patch("repomap_kg.storage.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(StorageSchemaError, "connection refused"):
                query_file_records(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_file_records_rejects_non_array_json(self):
        completed = SimpleNamespace(stdout='{"path": "README.md"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "file records"):
                query_file_records(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_file_records_rejects_invalid_json(self):
        completed = SimpleNamespace(stdout="{bad json}\n")

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "file records as JSON"):
                query_file_records(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_file_node_records_returns_records(self):
        completed = SimpleNamespace(
            stdout=(
                "["
                '{"path":"bin/tool","node_kind":"file",'
                '"node_name":"bin/tool","node_stable_key":"node:bin/tool:file:bin/tool",'
                '"evidence_stable_key":"evidence:bin/tool:0-0:fixture:bin/tool",'
                '"extractor":"fixture","extractor_version":"0.1.0",'
                '"raw_source_id":"bin/tool"}'
                "]\n"
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_file_node_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].path, "bin/tool")
        self.assertEqual(records[0].node_kind, "file")
        self.assertEqual(records[0].node_stable_key, "node:bin/tool:file:bin/tool")
        self.assertEqual(records[0].raw_source_id, "bin/tool")
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "repositories.root_path = '/tmp/fixture'",
            run.call_args.kwargs["input"],
        )

    def test_query_file_node_records_can_filter_by_path(self):
        completed = SimpleNamespace(stdout="[]\n")

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_file_node_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                path="bin/tool",
                psql_command="/bin/psql",
            )

        self.assertEqual(records, ())
        self.assertIn("AND files.path = 'bin/tool'", run.call_args.kwargs["input"])

    def test_query_file_node_records_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"path": "bin/tool"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "file node records"):
                query_file_node_records(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_node_records_returns_records(self):
        completed = SimpleNamespace(
            stdout=(
                "["
                '{"path":"bin/tool","node_kind":"shell.command",'
                '"node_name":"nix build",'
                '"node_stable_key":"node:bin/tool:shell.command:bin/tool#call:nix-build",'
                '"start_line":2,"end_line":2},'
                '{"path":"","node_kind":"tool","node_name":"nix",'
                '"node_stable_key":"tool:nix",'
                '"start_line":null,"end_line":null}'
                "]\n"
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_node_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].path, "bin/tool")
        self.assertEqual(records[0].node_kind, "shell.command")
        self.assertEqual(records[0].start_line, 2)
        self.assertEqual(records[1].path, "")
        self.assertEqual(records[1].node_stable_key, "tool:nix")
        self.assertIsNone(records[1].start_line)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "repositories.root_path = '/tmp/fixture'",
            run.call_args.kwargs["input"],
        )

    def test_query_node_records_can_filter_by_kind_path_and_stable_key(self):
        completed = SimpleNamespace(stdout="[]\n")

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_node_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                kind="shell.command",
                path="bin/tool",
                stable_key="node:bin/tool:shell.command:x",
                psql_command="/bin/psql",
            )

        self.assertEqual(records, ())
        self.assertIn(
            "AND nodes.kind = 'shell.command'",
            run.call_args.kwargs["input"],
        )
        self.assertIn("AND files.path = 'bin/tool'", run.call_args.kwargs["input"])
        self.assertIn(
            "AND nodes.stable_key = 'node:bin/tool:shell.command:x'",
            run.call_args.kwargs["input"],
        )

    def test_query_node_records_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"path": "bin/tool"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "node records"):
                query_node_records(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_neighborhood_returns_center_nodes_and_edges(self):
        completed = SimpleNamespace(
            stdout=(
                "{"
                '"center":{"path":"","node_kind":"tool","node_name":"nix",'
                '"node_stable_key":"tool:nix","start_line":null,"end_line":null},'
                '"nodes":['
                '{"path":"","node_kind":"tool","node_name":"nix",'
                '"node_stable_key":"tool:nix","start_line":null,"end_line":null},'
                '{"path":"bin/tool","node_kind":"shell.command",'
                '"node_name":"nix build",'
                '"node_stable_key":"node:bin/tool:shell.command:x",'
                '"start_line":2,"end_line":2}'
                "],"
                '"edges":['
                '{"path":"bin/tool","edge_kind":"shell.command",'
                '"edge_stable_key":"edge:node:bin/tool:shell.command:x",'
                '"confidence":"heuristic","src_node_kind":"shell.command",'
                '"src_node_name":"nix build",'
                '"src_node_stable_key":"node:bin/tool:shell.command:x",'
                '"dst_node_kind":"tool","dst_node_name":"nix",'
                '"dst_node_stable_key":"tool:nix",'
                '"evidence_stable_key":"evidence:bin/tool:2-2:fixture-shell:x",'
                '"extractor":"fixture-shell"}'
                "]"
                "}\n"
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            record = query_neighborhood(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                node="tool:nix",
                direction="in",
                psql_command="/bin/psql",
            )

        self.assertEqual(record.center.node_stable_key, "tool:nix")
        self.assertEqual([node.node_stable_key for node in record.nodes][0], "tool:nix")
        self.assertEqual(record.edges[0].dst_node_stable_key, "tool:nix")
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "repositories.root_path = '/tmp/fixture'",
            run.call_args.kwargs["input"],
        )
        self.assertIn(
            "JOIN center ON dst.id = center.id",
            run.call_args.kwargs["input"],
        )

    def test_query_neighborhood_rejects_depth_above_one(self):
        with patch("repomap_kg.storage.subprocess.run") as run:
            with self.assertRaisesRegex(StorageSchemaError, "depth 1"):
                query_neighborhood(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    node="tool:nix",
                    depth=2,
                )

        run.assert_not_called()

    def test_query_neighborhood_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"center": null}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "neighborhood"):
                query_neighborhood(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    node="tool:nix",
                )

    def test_query_file_neighborhood_returns_centers_nodes_and_edges(self):
        completed = SimpleNamespace(
            stdout=(
                "{"
                '"path":"bin/tool",'
                '"centers":['
                '{"path":"bin/tool","node_kind":"shell.command",'
                '"node_name":"nix build",'
                '"node_stable_key":"node:bin/tool:shell.command:x",'
                '"start_line":2,"end_line":2}'
                "],"
                '"nodes":['
                '{"path":"bin/tool","node_kind":"shell.command",'
                '"node_name":"nix build",'
                '"node_stable_key":"node:bin/tool:shell.command:x",'
                '"start_line":2,"end_line":2},'
                '{"path":"","node_kind":"tool","node_name":"nix",'
                '"node_stable_key":"tool:nix","start_line":null,"end_line":null}'
                "],"
                '"edges":['
                '{"path":"bin/tool","edge_kind":"shell.command",'
                '"edge_stable_key":"edge:node:bin/tool:shell.command:x",'
                '"confidence":"heuristic","src_node_kind":"shell.command",'
                '"src_node_name":"nix build",'
                '"src_node_stable_key":"node:bin/tool:shell.command:x",'
                '"dst_node_kind":"tool","dst_node_name":"nix",'
                '"dst_node_stable_key":"tool:nix",'
                '"evidence_stable_key":"evidence:bin/tool:2-2:fixture-shell:x",'
                '"extractor":"fixture-shell"}'
                "]"
                "}\n"
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            record = query_file_neighborhood(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                path="bin/tool",
                direction="out",
                psql_command="/bin/psql",
            )

        self.assertEqual(record.path, "bin/tool")
        self.assertEqual(record.centers[0].node_kind, "shell.command")
        self.assertEqual(record.nodes[-1].node_stable_key, "tool:nix")
        self.assertEqual(
            record.edges[0].src_node_stable_key,
            "node:bin/tool:shell.command:x",
        )
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("files.path = 'bin/tool'", run.call_args.kwargs["input"])
        self.assertIn(
            "JOIN center_nodes ON src.id = center_nodes.id",
            run.call_args.kwargs["input"],
        )

    def test_query_file_neighborhood_rejects_depth_above_one(self):
        with patch("repomap_kg.storage.subprocess.run") as run:
            with self.assertRaisesRegex(StorageSchemaError, "depth 1"):
                query_file_neighborhood(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    path="bin/tool",
                    depth=2,
                )

        run.assert_not_called()

    def test_query_file_neighborhood_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"path": "bin/tool"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "file neighborhood"):
                query_file_neighborhood(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    path="bin/tool",
                )

    def test_query_edge_records_returns_records(self):
        completed = SimpleNamespace(
            stdout=(
                "["
                '{"path":"bin/tool","edge_kind":"shell.command",'
                '"edge_stable_key":"edge:node:bin/tool:shell.command:bin/tool#call:nix-build:shell.command:tool:nix",'
                '"confidence":"heuristic","src_node_kind":"shell.command",'
                '"src_node_name":"nix build",'
                '"src_node_stable_key":"node:bin/tool:shell.command:bin/tool#call:nix-build",'
                '"dst_node_kind":"tool","dst_node_name":"nix",'
                '"dst_node_stable_key":"tool:nix",'
                '"evidence_stable_key":"evidence:bin/tool:2-2:fixture-shell:bin/tool#call:nix-build",'
                '"extractor":"fixture-shell"}'
                "]\n"
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_edge_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].path, "bin/tool")
        self.assertEqual(records[0].edge_kind, "shell.command")
        self.assertEqual(records[0].dst_node_stable_key, "tool:nix")
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "repositories.root_path = '/tmp/fixture'",
            run.call_args.kwargs["input"],
        )

    def test_query_edge_records_can_filter_by_kind(self):
        completed = SimpleNamespace(stdout="[]\n")

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_edge_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                kind="shell.command",
                psql_command="/bin/psql",
            )

        self.assertEqual(records, ())
        self.assertIn(
            "AND edges.kind = 'shell.command'",
            run.call_args.kwargs["input"],
        )

    def test_query_edge_records_can_filter_by_source_and_target_nodes(self):
        completed = SimpleNamespace(stdout="[]\n")

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_edge_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_node="node:bin/tool:shell.command:x",
                target_node="tool:nix",
                psql_command="/bin/psql",
            )

        self.assertEqual(records, ())
        self.assertIn(
            "AND src.stable_key = 'node:bin/tool:shell.command:x'",
            run.call_args.kwargs["input"],
        )
        self.assertIn(
            "AND dst.stable_key = 'tool:nix'",
            run.call_args.kwargs["input"],
        )

    def test_query_edge_records_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"path": "bin/tool"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "edge records"):
                query_edge_records(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_host_mutator_records_returns_records(self):
        completed = SimpleNamespace(
            stdout=(
                "["
                '{"path":"scripts/maintain.sh","line":2,"name":"rm",'
                '"target":"host:filesystem-mutation",'
                '"category":"filesystem-mutation","tool":"rm",'
                '"privileged":true,"confidence":"heuristic",'
                '"reason":"rm host filesystem path",'
                '"argv":["sudo","rm","-rf","/Library/Caches/example"],'
                '"effective_argv":["rm","-rf","/Library/Caches/example"]}'
                "]\n"
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            records = query_host_mutator_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                category="filesystem-mutation",
                tool="rm",
                psql_command="/bin/psql",
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].path, "scripts/maintain.sh")
        self.assertEqual(records[0].category, "filesystem-mutation")
        self.assertTrue(records[0].privileged)
        self.assertEqual(records[0].effective_argv, (
            "rm",
            "-rf",
            "/Library/Caches/example",
        ))
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "repositories.root_path = '/tmp/fixture'",
            run.call_args.kwargs["input"],
        )
        self.assertIn(
            "nodes.kind = 'shell.host_mutation'",
            run.call_args.kwargs["input"],
        )
        self.assertIn(
            "nodes.metadata_json->>'category' = 'filesystem-mutation'",
            run.call_args.kwargs["input"],
        )
        self.assertIn(
            "nodes.metadata_json->>'tool' = 'rm'",
            run.call_args.kwargs["input"],
        )

    def test_query_host_mutator_records_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"path": "scripts/maintain.sh"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "host-mutator records"):
                query_host_mutator_records(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                )

    def test_build_host_mutator_query_sql_quotes_root_path(self):
        sql = build_host_mutator_query_sql(
            "/tmp/fixture's repo",
            category="service-management",
            tool="launchctl",
        )

        self.assertIn(
            "repositories.root_path = '/tmp/fixture''s repo'",
            sql,
        )
        self.assertIn("nodes.kind = 'shell.host_mutation'", sql)
        self.assertIn(
            "nodes.metadata_json->>'category' = 'service-management'",
            sql,
        )
        self.assertIn("nodes.metadata_json->>'tool' = 'launchctl'", sql)

    def test_query_storage_summary_returns_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture","repository_id":7,'
                '"repository_name":"fixture","latest_run_id":11,'
                '"runs":1,"files":2,"nodes":5,"edges":2,"evidence":3}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_storage_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_id, 7)
        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.latest_run_id, 11)
        self.assertEqual(summary.files, 2)
        self.assertEqual(summary.nodes, 5)
        self.assertEqual(summary.edges, 2)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "repositories.root_path = '/tmp/fixture'",
            run.call_args.kwargs["input"],
        )

    def test_query_storage_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "storage summary"):
                query_storage_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_build_node_query_sql_quotes_root_path_and_orders_nodes(self):
        sql = build_node_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("JOIN repositories ON repositories.id = nodes.repository_id", sql)
        self.assertIn("LEFT JOIN files ON files.id = nodes.file_id", sql)
        self.assertIn(
            "ORDER BY COALESCE(files.path, ''), nodes.kind, nodes.stable_key",
            sql,
        )

    def test_build_node_query_sql_can_filter_by_kind_path_and_stable_key(self):
        sql = build_node_query_sql(
            "/tmp/fixture",
            kind="shell.command",
            path="bin/tool",
            stable_key="node:bin/tool:shell.command:x",
        )

        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("AND nodes.kind = 'shell.command'", sql)
        self.assertIn("AND files.path = 'bin/tool'", sql)
        self.assertIn("AND nodes.stable_key = 'node:bin/tool:shell.command:x'", sql)

    def test_build_neighborhood_query_sql_filters_by_direction(self):
        inbound = build_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="in",
        )
        outbound = build_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="out",
        )
        both = build_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="both",
        )

        self.assertIn("repositories.root_path = '/tmp/fixture'", inbound)
        self.assertIn("nodes.stable_key = 'tool:nix'", inbound)
        self.assertIn("JOIN center ON dst.id = center.id", inbound)
        self.assertIn("JOIN center ON src.id = center.id", outbound)
        self.assertIn(
            "JOIN center ON (src.id = center.id OR dst.id = center.id)",
            both,
        )

    def test_build_neighborhood_query_sql_rejects_unknown_direction(self):
        with self.assertRaisesRegex(StorageSchemaError, "direction"):
            build_neighborhood_query_sql(
                "/tmp/fixture",
                node="tool:nix",
                direction="sideways",
            )

    def test_build_file_neighborhood_query_sql_filters_by_path_and_direction(self):
        inbound = build_file_neighborhood_query_sql(
            "/tmp/fixture",
            path="bin/tool",
            direction="in",
        )
        outbound = build_file_neighborhood_query_sql(
            "/tmp/fixture",
            path="bin/tool",
            direction="out",
        )
        both = build_file_neighborhood_query_sql(
            "/tmp/fixture",
            path="bin/tool",
            direction="both",
        )

        self.assertIn("repositories.root_path = '/tmp/fixture'", inbound)
        self.assertIn("files.path = 'bin/tool'", inbound)
        self.assertIn("JOIN center_nodes ON dst.id = center_nodes.id", inbound)
        self.assertIn("JOIN center_nodes ON src.id = center_nodes.id", outbound)
        self.assertIn(
            "JOIN center_nodes ON "
            "(src.id = center_nodes.id OR dst.id = center_nodes.id)",
            both,
        )

    def test_build_file_neighborhood_query_sql_rejects_unknown_direction(self):
        with self.assertRaisesRegex(StorageSchemaError, "direction"):
            build_file_neighborhood_query_sql(
                "/tmp/fixture",
                path="bin/tool",
                direction="sideways",
            )

    def test_build_edge_query_sql_quotes_root_path_and_orders_edges(self):
        sql = build_edge_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("JOIN nodes src ON src.id = edges.src_node_id", sql)
        self.assertIn("JOIN nodes dst ON dst.id = edges.dst_node_id", sql)
        self.assertIn("ORDER BY edges.kind, edges.stable_key", sql)

    def test_build_edge_query_sql_can_filter_by_kind(self):
        sql = build_edge_query_sql("/tmp/fixture's repo", kind="shell.command")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("AND edges.kind = 'shell.command'", sql)

    def test_build_edge_query_sql_can_filter_by_source_and_target_nodes(self):
        sql = build_edge_query_sql(
            "/tmp/fixture's repo",
            source_node="node:bin/tool:shell.command:x",
            target_node="tool:nix",
        )

        self.assertIn("fixture''s repo", sql)
        self.assertIn("AND src.stable_key = 'node:bin/tool:shell.command:x'", sql)
        self.assertIn("AND dst.stable_key = 'tool:nix'", sql)

    def test_build_storage_summary_query_sql_quotes_root_path_and_counts_tables(self):
        sql = build_storage_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("COUNT(*) FROM runs", sql)
        self.assertIn("COUNT(*) FROM files", sql)
        self.assertIn("COUNT(*) FROM nodes", sql)
        self.assertIn("COUNT(*) FROM edges", sql)
        self.assertIn("COUNT(*) FROM evidence", sql)

    def test_format_edge_table_uses_edge_columns(self):
        table = format_edge_table(
            [
                EdgeRecord(
                    path="bin/tool",
                    edge_kind="shell.command",
                    edge_stable_key="edge:node:bin/tool:shell.command:x",
                    confidence="heuristic",
                    src_node_kind="shell.command",
                    src_node_name="nix build",
                    src_node_stable_key="node:bin/tool:shell.command:x",
                    dst_node_kind="tool",
                    dst_node_name="nix",
                    dst_node_stable_key="tool:nix",
                    evidence_stable_key="evidence:bin/tool:2-2:fixture-shell:x",
                    extractor="fixture-shell",
                )
            ]
        )

        self.assertIn("edge_kind", table)
        self.assertIn("edge_stable_key", table)
        self.assertIn("src_node_stable_key", table)
        self.assertIn("dst_node_stable_key", table)
        self.assertIn("tool:nix", table)

    def test_format_storage_summary_table_uses_count_columns(self):
        table = format_storage_summary_table(
            StorageSummaryRecord(
                root_path="/tmp/fixture",
                repository_id=7,
                repository_name="fixture",
                latest_run_id=11,
                runs=1,
                files=2,
                nodes=5,
                edges=2,
                evidence=3,
            )
        )

        self.assertIn("root_path", table)
        self.assertIn("latest_run_id", table)
        self.assertIn("files", table)
        self.assertIn("edges", table)
        self.assertIn("/tmp/fixture", table)

    def test_format_node_table_uses_node_columns(self):
        table = format_node_table(
            [
                NodeRecord(
                    path="bin/tool",
                    node_kind="shell.command",
                    node_name="nix build",
                    node_stable_key="node:bin/tool:shell.command:x",
                    start_line=2,
                    end_line=2,
                )
            ]
        )

        self.assertIn("path", table)
        self.assertIn("node_kind", table)
        self.assertIn("node_stable_key", table)
        self.assertIn("start_line", table)
        self.assertIn("node:bin/tool:shell.command:x", table)

    def test_format_neighborhood_table_prints_center_and_edges(self):
        table = format_neighborhood_table(
            NeighborhoodRecord(
                center=NodeRecord(
                    path="",
                    node_kind="tool",
                    node_name="nix",
                    node_stable_key="tool:nix",
                    start_line=None,
                    end_line=None,
                ),
                nodes=(
                    NodeRecord(
                        path="",
                        node_kind="tool",
                        node_name="nix",
                        node_stable_key="tool:nix",
                        start_line=None,
                        end_line=None,
                    ),
                ),
                edges=(
                    EdgeRecord(
                        path="bin/tool",
                        edge_kind="shell.command",
                        edge_stable_key="edge:node:bin/tool:shell.command:x",
                        confidence="heuristic",
                        src_node_kind="shell.command",
                        src_node_name="nix build",
                        src_node_stable_key="node:bin/tool:shell.command:x",
                        dst_node_kind="tool",
                        dst_node_name="nix",
                        dst_node_stable_key="tool:nix",
                        evidence_stable_key="evidence:bin/tool:2-2:fixture-shell:x",
                        extractor="fixture-shell",
                    ),
                ),
            )
        )

        self.assertIn("center_node_stable_key: tool:nix", table)
        self.assertIn("edge_kind", table)
        self.assertIn("dst_node_stable_key", table)
        self.assertIn("tool:nix", table)

    def test_format_file_neighborhood_table_prints_path_and_edges(self):
        table = format_file_neighborhood_table(
            FileNeighborhoodRecord(
                path="bin/tool",
                centers=(
                    NodeRecord(
                        path="bin/tool",
                        node_kind="shell.command",
                        node_name="nix build",
                        node_stable_key="node:bin/tool:shell.command:x",
                        start_line=2,
                        end_line=2,
                    ),
                ),
                nodes=(
                    NodeRecord(
                        path="bin/tool",
                        node_kind="shell.command",
                        node_name="nix build",
                        node_stable_key="node:bin/tool:shell.command:x",
                        start_line=2,
                        end_line=2,
                    ),
                ),
                edges=(
                    EdgeRecord(
                        path="bin/tool",
                        edge_kind="shell.command",
                        edge_stable_key="edge:node:bin/tool:shell.command:x",
                        confidence="heuristic",
                        src_node_kind="shell.command",
                        src_node_name="nix build",
                        src_node_stable_key="node:bin/tool:shell.command:x",
                        dst_node_kind="tool",
                        dst_node_name="nix",
                        dst_node_stable_key="tool:nix",
                        evidence_stable_key="evidence:bin/tool:2-2:fixture-shell:x",
                        extractor="fixture-shell",
                    ),
                ),
            )
        )

        self.assertIn("file_path: bin/tool", table)
        self.assertIn("center_nodes: 1", table)
        self.assertIn("edge_kind", table)
        self.assertIn("tool:nix", table)

    def test_build_file_node_query_sql_quotes_root_path_and_orders_graph_records(self):
        sql = build_file_node_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("JOIN nodes ON nodes.file_id = files.id", sql)
        self.assertIn("JOIN evidence ON evidence.file_id = files.id", sql)
        self.assertIn("ORDER BY files.path, nodes.stable_key, evidence.stable_key", sql)

    def test_build_file_node_query_sql_can_filter_by_path(self):
        sql = build_file_node_query_sql("/tmp/fixture", path="bin/tool")

        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("AND files.path = 'bin/tool'", sql)

    def test_format_file_node_table_uses_graph_columns(self):
        table = format_file_node_table(
            [
                FileNodeRecord(
                    path="bin/tool",
                    node_kind="file",
                    node_name="bin/tool",
                    node_stable_key="node:bin/tool:file:bin/tool",
                    evidence_stable_key="evidence:bin/tool:0-0:fixture:bin/tool",
                    extractor="fixture",
                    extractor_version="0.1.0",
                    raw_source_id="bin/tool",
                )
            ]
        )

        self.assertIn("path", table)
        self.assertIn("node_kind", table)
        self.assertIn("evidence_stable_key", table)
        self.assertIn("bin/tool", table)

    def test_build_file_query_sql_quotes_root_path(self):
        sql = build_file_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("ORDER BY files.path", sql)


if __name__ == "__main__":
    unittest.main()
