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
    APISummaryRecord,
    BulkSummaryRecord,
    CanonicalEdgeRecord,
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    CanonicalStorageSummaryRecord,
    EdgeRecord,
    EmailSummaryRecord,
    FileNodeRecord,
    FileNeighborhoodRecord,
    JSSummaryRecord,
    JSFrameworkSummaryRecord,
    NeighborhoodRecord,
    NodeRecord,
    OpenAPISummaryRecord,
    PythonSummaryRecord,
    RubySummaryRecord,
    StorageSummaryRecord,
    StorageSchemaError,
    TerraformSummaryRecord,
    build_api_summary_query_sql,
    build_canonical_storage_summary_query_sql,
    build_bulk_summary_query_sql,
    build_email_summary_query_sql,
    build_ingested_source_query_sql,
    build_js_summary_query_sql,
    build_js_framework_summary_query_sql,
    build_openapi_summary_query_sql,
    build_python_summary_query_sql,
    build_ruby_summary_query_sql,
    build_terraform_summary_query_sql,
    build_source_feed_item_query_sql,
    build_source_reference_query_sql,
    build_source_run_query_sql,
    build_source_summary_query_sql,
    build_file_neighborhood_query_sql,
    build_explain_canonical_edge_query_sql,
    build_canonical_edge_query_sql,
    build_canonical_node_query_sql,
    build_canonical_neighborhood_query_sql,
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
    format_api_summary_table,
    format_bulk_summary_table,
    format_email_summary_table,
    format_file_node_table,
    format_file_neighborhood_table,
    format_neighborhood_table,
    format_node_table,
    format_js_summary_table,
    format_js_framework_summary_table,
    format_openapi_summary_table,
    format_python_summary_table,
    format_ruby_summary_table,
    format_storage_summary_table,
    format_terraform_summary_table,
    file_rows_from_observations,
    query_edge_records,
    query_api_summary,
    query_bulk_summary,
    query_email_summary,
    query_file_node_records,
    query_file_records,
    query_file_neighborhood,
    query_neighborhood,
    query_node_records,
    query_js_summary,
    query_js_framework_summary,
    query_openapi_summary,
    query_python_summary,
    query_ruby_summary,
    query_storage_summary,
    query_terraform_summary,
    query_host_mutator_records,
    relationship_rows_from_observations,
    load_file_observations,
    build_canonical_ingest_sql,
    canonical_file_path_prefix,
    canonical_rows_from_result,
    identity_metadata_hash,
    raw_observation_payload_hash,
    raw_observation_rows_from_observations,
    canonical_edge_explanation_to_jsonable,
    canonical_edge_records_to_jsonable,
    canonical_edge_explanation_from_storage_payload,
    canonical_neighborhood_from_storage_payload,
    canonical_neighborhood_to_jsonable,
    canonical_node_records_to_jsonable,
    canonical_edge_record_from_storage_payload,
    canonical_node_record_from_storage_payload,
    ingested_source_record_from_storage_payload,
    source_feed_item_record_from_storage_payload,
    source_reference_record_from_storage_payload,
    source_run_record_from_storage_payload,
    source_summary_from_storage_payload,
    api_summary_from_storage_payload,
    js_summary_from_storage_payload,
    js_framework_summary_from_storage_payload,
    openapi_summary_from_storage_payload,
    python_summary_from_storage_payload,
    ruby_summary_from_storage_payload,
    terraform_summary_from_storage_payload,
    email_summary_from_storage_payload,
    format_canonical_edge_table,
    format_canonical_edge_explanation_table,
    format_canonical_neighborhood_table,
    format_canonical_node_table,
    format_canonical_storage_summary_table,
    query_canonical_neighborhood,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_canonical_storage_summary,
    query_ingested_source_records,
    api_summary_to_jsonable,
    bulk_summary_from_storage_payload,
    bulk_summary_to_jsonable,
    js_summary_to_jsonable,
    js_framework_summary_to_jsonable,
    openapi_summary_to_jsonable,
    python_summary_to_jsonable,
    ruby_summary_to_jsonable,
    terraform_summary_to_jsonable,
    email_summary_to_jsonable,
    query_source_feed_item_records,
    query_source_reference_records,
    query_source_run_records,
    query_source_summary,
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

    def test_build_canonical_node_query_sql_filters_and_orders(self):
        sql = build_canonical_node_query_sql(
            "/tmp/fixture",
            kind="file",
            canonical_key="file:bin/tool",
            path_prefix="bin/",
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_nodes", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_nodes.graph_key_version = 1", sql)
        self.assertIn("canonical_nodes.kind = 'file'", sql)
        self.assertIn("canonical_nodes.canonical_key = 'file:bin/tool'", sql)
        self.assertIn("canonical_nodes.canonical_key LIKE 'file:bin/%'", sql)
        self.assertIn("ORDER BY canonical_nodes.canonical_key", sql)
        self.assertIn("'metadata', canonical_nodes.metadata_json", sql)

    def test_canonical_file_path_prefix_uses_subtree_semantics(self):
        self.assertEqual(
            canonical_file_path_prefix("bin"),
            canonical_file_path_prefix("bin/"),
        )
        self.assertEqual(canonical_file_path_prefix("bin"), "file:bin/")

        sql = build_canonical_node_query_sql(
            "/tmp/fixture",
            kind="file",
            path_prefix="bin",
        )

        self.assertIn("canonical_nodes.canonical_key LIKE 'file:bin/%'", sql)

    def test_canonical_file_path_prefix_does_not_match_sibling_file_prefixes(self):
        prefix = canonical_file_path_prefix("bin")

        self.assertTrue("file:bin/tool".startswith(prefix))
        self.assertFalse("file:binary".startswith(prefix))

    def test_canonical_file_path_prefix_rejects_repo_escaping_prefix(self):
        with self.assertRaisesRegex(
            StorageSchemaError,
            "invalid canonical file path prefix",
        ):
            canonical_file_path_prefix("../bin")

    def test_canonical_file_path_prefix_root_matches_all_file_nodes(self):
        self.assertEqual(canonical_file_path_prefix("."), "file:")
        self.assertEqual(canonical_file_path_prefix(""), "file:")

        sql = build_canonical_node_query_sql(
            "/tmp/fixture",
            kind="file",
            path_prefix=".",
        )

        self.assertIn("canonical_nodes.canonical_key LIKE 'file:%'", sql)

    def test_build_canonical_edge_query_sql_filters_and_orders(self):
        sql = build_canonical_edge_query_sql(
            "/tmp/fixture",
            kind="executes",
            source_key="file:bin/tool",
            target_key="tool:nix",
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_edges", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_edges.graph_key_version = 1", sql)
        self.assertIn("canonical_edges.edge_kind = 'executes'", sql)
        self.assertIn("canonical_edges.source_canonical_key = 'file:bin/tool'", sql)
        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", sql)
        self.assertIn(
            "ORDER BY canonical_edges.source_canonical_key, "
            "canonical_edges.edge_kind, "
            "canonical_edges.target_canonical_key, "
            "canonical_edges.identity_metadata_hash",
            sql,
        )
        self.assertIn("'identity_metadata', canonical_edges.identity_metadata_json", sql)

    def test_build_explain_canonical_edge_query_sql_filters_by_identity(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        sql = build_explain_canonical_edge_query_sql(
            "/tmp/fixture",
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata_hash=hash_text,
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_edges", sql)
        self.assertIn("JOIN canonical_edge_evidence", sql)
        self.assertIn("JOIN canonical_evidence", sql)
        self.assertIn("LEFT JOIN raw_observations", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_edges.graph_key_version = 1", sql)
        self.assertIn("canonical_edges.source_canonical_key = 'file:bin/tool'", sql)
        self.assertIn("canonical_edges.edge_kind = 'executes'", sql)
        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", sql)
        self.assertIn(f"canonical_edges.identity_metadata_hash = '{hash_text}'", sql)

    def test_build_canonical_neighborhood_query_sql_filters_and_orders(self):
        sql = build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="both",
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_nodes", sql)
        self.assertIn("FROM canonical_edges", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_nodes.graph_key_version = 1", sql)
        self.assertIn("canonical_nodes.canonical_key = 'tool:nix'", sql)
        self.assertIn("canonical_edges.source_canonical_key = 'tool:nix'", sql)
        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", sql)
        self.assertIn("ORDER BY canonical_nodes.canonical_key", sql)
        self.assertIn(
            "ORDER BY canonical_edges.source_canonical_key, "
            "canonical_edges.edge_kind, "
            "canonical_edges.target_canonical_key, "
            "canonical_edges.identity_metadata_hash",
            sql,
        )

    def test_build_canonical_neighborhood_query_sql_honors_direction(self):
        in_sql = build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="in",
        )
        out_sql = build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="out",
        )

        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", in_sql)
        self.assertNotIn("canonical_edges.source_canonical_key = 'tool:nix'", in_sql)
        self.assertIn("canonical_edges.source_canonical_key = 'tool:nix'", out_sql)
        self.assertNotIn("canonical_edges.target_canonical_key = 'tool:nix'", out_sql)

    def test_canonical_node_record_from_storage_payload_preserves_public_fields(self):
        record = canonical_node_record_from_storage_payload(
            {
                "canonical_key": "file:bin/tool",
                "graph_key_version": 1,
                "kind": "file",
                "display_name": "bin/tool",
                "confidence": "extracted",
                "conflict": False,
                "metadata": {"role": "script"},
                "first_seen_run_id": 10,
                "last_seen_run_id": 12,
            }
        )

        self.assertEqual(
            record,
            CanonicalNodeRecord(
                canonical_key="file:bin/tool",
                graph_key_version=1,
                kind="file",
                display_name="bin/tool",
                confidence="extracted",
                conflict=False,
                metadata={"role": "script"},
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
        )
        self.assertEqual(record.to_dict()["canonical_key"], "file:bin/tool")

    def test_canonical_edge_record_from_storage_payload_preserves_public_fields(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        record = canonical_edge_record_from_storage_payload(
            {
                "source_key": "file:bin/tool",
                "edge_kind": "executes",
                "target_key": "tool:nix",
                "graph_key_version": 1,
                "identity_metadata": {},
                "identity_metadata_hash": hash_text,
                "metadata": {"commands": ["nix"]},
                "confidence": "extracted",
                "conflict": False,
                "first_seen_run_id": 10,
                "last_seen_run_id": 12,
            }
        )

        self.assertEqual(
            record,
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
        )
        self.assertEqual(record.to_dict()["target_key"], "tool:nix")

    def test_canonical_edge_explanation_from_storage_payload_preserves_public_fields(
        self,
    ):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        payload_hash = (
            "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
        )

        record = canonical_edge_explanation_from_storage_payload(
            {
                "edge": {
                    "source_key": "file:bin/tool",
                    "edge_kind": "executes",
                    "target_key": "tool:nix",
                    "graph_key_version": 1,
                    "identity_metadata": {},
                    "identity_metadata_hash": hash_text,
                    "metadata": {"commands": ["nix"]},
                    "confidence": "extracted",
                    "conflict": False,
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                },
                "evidence": [
                    {
                        "evidence_key": "evidence:bin/tool:1-1:repo-shell:nix",
                        "link_kind": "supports",
                        "raw_observation": {
                            "run_id": 10,
                            "ordinal": 0,
                            "payload_hash": payload_hash,
                            "kind": "shell.command",
                            "source_id": "bin/tool#call:nix",
                        },
                        "path": "bin/tool",
                        "start_line": 1,
                        "end_line": 1,
                        "extractor": "repo-shell",
                        "extractor_version": "0.1.0",
                        "confidence": "extracted",
                        "metadata": {"argv": ["nix", "build"]},
                    }
                ],
            }
        )

        self.assertEqual(
            record,
            CanonicalEdgeExplanationRecord(
                edge=CanonicalEdgeRecord(
                    source_key="file:bin/tool",
                    edge_kind="executes",
                    target_key="tool:nix",
                    graph_key_version=1,
                    identity_metadata={},
                    identity_metadata_hash=hash_text,
                    metadata={"commands": ["nix"]},
                    confidence="extracted",
                    conflict=False,
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
                evidence=(
                    CanonicalEdgeEvidenceRecord(
                        evidence_key="evidence:bin/tool:1-1:repo-shell:nix",
                        link_kind="supports",
                        raw_observation={
                            "run_id": 10,
                            "ordinal": 0,
                            "payload_hash": payload_hash,
                            "kind": "shell.command",
                            "source_id": "bin/tool#call:nix",
                        },
                        path="bin/tool",
                        start_line=1,
                        end_line=1,
                        extractor="repo-shell",
                        extractor_version="0.1.0",
                        confidence="extracted",
                        metadata={"argv": ["nix", "build"]},
                    ),
                ),
            ),
        )
        self.assertEqual(
            canonical_edge_explanation_to_jsonable(record)["edge"]["source_key"],
            "file:bin/tool",
        )

    def test_canonical_neighborhood_from_storage_payload_preserves_public_fields(
        self,
    ):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        record = canonical_neighborhood_from_storage_payload(
            {
                "center": {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                },
                "nodes": [
                    {
                        "canonical_key": "file:bin/tool",
                        "graph_key_version": 1,
                        "kind": "file",
                        "display_name": "bin/tool",
                        "confidence": "extracted",
                        "conflict": False,
                        "metadata": {"role": "entrypoint"},
                        "first_seen_run_id": 10,
                        "last_seen_run_id": 12,
                    }
                ],
                "edges": [
                    {
                        "source_key": "file:bin/tool",
                        "edge_kind": "executes",
                        "target_key": "tool:nix",
                        "graph_key_version": 1,
                        "identity_metadata": {},
                        "identity_metadata_hash": hash_text,
                        "metadata": {"commands": ["nix"]},
                        "confidence": "extracted",
                        "conflict": False,
                        "first_seen_run_id": 10,
                        "last_seen_run_id": 12,
                    }
                ],
            }
        )

        self.assertEqual(
            record,
            CanonicalNeighborhoodRecord(
                center=CanonicalNodeRecord(
                    canonical_key="tool:nix",
                    graph_key_version=1,
                    kind="tool",
                    display_name="nix",
                    confidence="extracted",
                    conflict=False,
                    metadata={},
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
                nodes=(
                    CanonicalNodeRecord(
                        canonical_key="file:bin/tool",
                        graph_key_version=1,
                        kind="file",
                        display_name="bin/tool",
                        confidence="extracted",
                        conflict=False,
                        metadata={"role": "entrypoint"},
                        first_seen_run_id=10,
                        last_seen_run_id=12,
                    ),
                ),
                edges=(
                    CanonicalEdgeRecord(
                        source_key="file:bin/tool",
                        edge_kind="executes",
                        target_key="tool:nix",
                        graph_key_version=1,
                        identity_metadata={},
                        identity_metadata_hash=hash_text,
                        metadata={"commands": ["nix"]},
                        confidence="extracted",
                        conflict=False,
                        first_seen_run_id=10,
                        last_seen_run_id=12,
                    ),
                ),
            ),
        )
        self.assertEqual(
            canonical_neighborhood_to_jsonable(record)["center"]["canonical_key"],
            "tool:nix",
        )

    def test_canonical_neighborhood_from_storage_payload_accepts_missing_center(
        self,
    ):
        record = canonical_neighborhood_from_storage_payload(
            {"center": None, "nodes": [], "edges": []}
        )

        self.assertEqual(
            record,
            CanonicalNeighborhoodRecord(center=None, nodes=(), edges=()),
        )
        self.assertEqual(
            canonical_neighborhood_to_jsonable(record),
            {"center": None, "nodes": [], "edges": []},
        )

    def test_canonical_edge_explanation_from_storage_payload_accepts_missing_edge(
        self,
    ):
        record = canonical_edge_explanation_from_storage_payload(
            {"edge": None, "evidence": []}
        )

        self.assertEqual(
            record,
            CanonicalEdgeExplanationRecord(edge=None, evidence=()),
        )
        self.assertEqual(
            canonical_edge_explanation_to_jsonable(record),
            {"edge": None, "evidence": []},
        )

    def test_canonical_node_record_from_storage_payload_accepts_null_run_ids(self):
        record = canonical_node_record_from_storage_payload(
            {
                "canonical_key": "tool:nix",
                "graph_key_version": 1,
                "kind": "tool",
                "display_name": "nix",
                "confidence": "extracted",
                "conflict": False,
                "metadata": {},
                "first_seen_run_id": None,
                "last_seen_run_id": None,
            }
        )

        self.assertEqual(
            record,
            CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=None,
                last_seen_run_id=None,
            ),
        )
        self.assertIsNone(record.to_dict()["first_seen_run_id"])
        self.assertIsNone(record.to_dict()["last_seen_run_id"])

    def test_canonical_edge_record_from_storage_payload_accepts_null_run_ids(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        record = canonical_edge_record_from_storage_payload(
            {
                "source_key": "file:bin/tool",
                "edge_kind": "executes",
                "target_key": "tool:nix",
                "graph_key_version": 1,
                "identity_metadata": {},
                "identity_metadata_hash": hash_text,
                "metadata": {},
                "confidence": "extracted",
                "conflict": False,
                "first_seen_run_id": None,
                "last_seen_run_id": None,
            }
        )

        self.assertEqual(
            record,
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=None,
                last_seen_run_id=None,
            ),
        )
        self.assertIsNone(record.to_dict()["first_seen_run_id"])
        self.assertIsNone(record.to_dict()["last_seen_run_id"])

    def test_canonical_node_records_to_jsonable_preserves_public_fields(self):
        records = (
            CanonicalNodeRecord(
                canonical_key="file:bin/tool",
                graph_key_version=1,
                kind="file",
                display_name="bin/tool",
                confidence="extracted",
                conflict=False,
                metadata={"role": "entrypoint"},
                first_seen_run_id=10,
                last_seen_run_id=None,
            ),
        )

        self.assertEqual(
            canonical_node_records_to_jsonable(records),
            [
                {
                    "canonical_key": "file:bin/tool",
                    "graph_key_version": 1,
                    "kind": "file",
                    "display_name": "bin/tool",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {"role": "entrypoint"},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": None,
                }
            ],
        )

    def test_canonical_edge_records_to_jsonable_preserves_public_fields(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        records = (
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
        )

        self.assertEqual(
            canonical_edge_records_to_jsonable(records),
            [
                {
                    "source_key": "file:bin/tool",
                    "edge_kind": "executes",
                    "target_key": "tool:nix",
                    "graph_key_version": 1,
                    "identity_metadata": {},
                    "identity_metadata_hash": hash_text,
                    "metadata": {"commands": ["nix"]},
                    "confidence": "extracted",
                    "conflict": False,
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                }
            ],
        )

    def test_format_canonical_node_table_uses_contract_columns(self):
        records = (
            CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="manual",
                conflict=False,
                metadata={"omitted": True},
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )

        table = format_canonical_node_table(records)

        self.assertIn("canonical_key", table)
        self.assertIn("display_name", table)
        self.assertIn("first_seen_run_id", table)
        self.assertIn("tool:nix", table)
        self.assertIn("12", table)
        self.assertNotIn("metadata", table)
        self.assertNotIn("omitted", table)

    def test_format_canonical_edge_table_uses_contract_columns(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        records = (
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"omitted": True},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )

        table = format_canonical_edge_table(records)

        self.assertIn("source_key", table)
        self.assertIn("edge_kind", table)
        self.assertIn("target_key", table)
        self.assertIn("identity_metadata_hash", table)
        self.assertIn("first_seen_run_id", table)
        self.assertIn("file:bin/tool", table)
        self.assertIn("tool:nix", table)
        self.assertIn(hash_text, table)
        self.assertIn("12", table)
        self.assertNotIn("omitted", table)

    def test_format_canonical_neighborhood_table_uses_contract_sections(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="manual",
                conflict=False,
                metadata={"omitted": True},
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
            nodes=(
                CanonicalNodeRecord(
                    canonical_key="file:bin/tool",
                    graph_key_version=1,
                    kind="file",
                    display_name="bin/tool",
                    confidence="extracted",
                    conflict=False,
                    metadata={},
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
            ),
            edges=(
                CanonicalEdgeRecord(
                    source_key="file:bin/tool",
                    edge_kind="executes",
                    target_key="tool:nix",
                    graph_key_version=1,
                    identity_metadata={},
                    identity_metadata_hash=hash_text,
                    metadata={"commands": ["nix"]},
                    confidence="extracted",
                    conflict=False,
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
            ),
        )

        table = format_canonical_neighborhood_table(record)

        self.assertIn("center: tool:nix", table)
        self.assertIn("Nodes:", table)
        self.assertIn("canonical_key", table)
        self.assertIn("file:bin/tool", table)
        self.assertIn("Edges:", table)
        self.assertIn("identity_metadata_hash", table)
        self.assertIn(hash_text, table)
        self.assertNotIn("omitted", table)
        self.assertNotIn("commands", table)

    def test_format_canonical_neighborhood_table_reports_missing_center(self):
        table = format_canonical_neighborhood_table(
            CanonicalNeighborhoodRecord(center=None, nodes=(), edges=())
        )

        self.assertIn("center: <not found>", table)
        self.assertIn("Nodes:", table)
        self.assertIn("Edges:", table)

    def test_format_canonical_edge_explanation_table_uses_contract_sections(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
            evidence=(
                CanonicalEdgeEvidenceRecord(
                    evidence_key="evidence:bin/tool:1-1:repo-shell:nix",
                    link_kind="supports",
                    raw_observation={
                        "run_id": 10,
                        "ordinal": 0,
                        "payload_hash": (
                            "abcdef0123456789abcdef0123456789"
                            "abcdef0123456789abcdef0123456789"
                        ),
                        "kind": "shell.command",
                        "source_id": "bin/tool#call:nix",
                    },
                    path="bin/tool",
                    start_line=1,
                    end_line=1,
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    confidence="extracted",
                    metadata={"argv": ["nix", "build"]},
                ),
            ),
        )

        table = format_canonical_edge_explanation_table(record)

        self.assertIn("edge:", table)
        self.assertIn("evidence:", table)
        self.assertIn("source_key", table)
        self.assertIn("identity_metadata_hash", table)
        self.assertIn(hash_text, table)
        self.assertIn("raw_observation.run_id", table)
        self.assertIn("raw_observation.ordinal", table)
        self.assertIn("raw_observation.kind", table)
        self.assertIn("raw_observation.source_id", table)
        self.assertIn("bin/tool", table)
        self.assertIn("repo-shell", table)
        self.assertNotIn("commands", table)
        self.assertNotIn("argv", table)

    def test_format_canonical_edge_explanation_table_reports_missing_edge(self):
        table = format_canonical_edge_explanation_table(
            CanonicalEdgeExplanationRecord(edge=None, evidence=())
        )

        self.assertIn("edge: <not found>", table)
        self.assertIn("evidence:", table)
        self.assertIn("raw_observation.run_id", table)

    def test_canonical_record_payload_helpers_reject_malformed_payloads(self):
        with self.assertRaisesRegex(StorageSchemaError, "canonical node record"):
            canonical_node_record_from_storage_payload({"canonical_key": ""})
        with self.assertRaisesRegex(StorageSchemaError, "canonical edge record"):
            canonical_edge_record_from_storage_payload({"source_key": ""})

    def test_query_canonical_records_parse_psql_json_arrays(self):
        node_payload = json.dumps(
            [
                {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                }
            ]
        )
        edge_hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        edge_payload = json.dumps(
            [
                {
                    "source_key": "file:bin/tool",
                    "edge_kind": "executes",
                    "target_key": "tool:nix",
                    "graph_key_version": 1,
                    "identity_metadata": {},
                    "identity_metadata_hash": edge_hash,
                    "metadata": {},
                    "confidence": "extracted",
                    "conflict": False,
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                }
            ]
        )

        with patch("repomap_kg.storage.subprocess.run") as run:
            run.side_effect = [
                subprocess.CompletedProcess(["psql"], 0, stdout=node_payload + "\n"),
                subprocess.CompletedProcess(["psql"], 0, stdout=edge_payload + "\n"),
            ]

            nodes = query_canonical_node_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                kind="tool",
            )
            edges = query_canonical_edge_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                kind="executes",
                target_key="tool:nix",
            )

        self.assertEqual(nodes[0].canonical_key, "tool:nix")
        self.assertEqual(edges[0].target_key, "tool:nix")
        self.assertIn("canonical_nodes", run.call_args_list[0].kwargs["input"])
        self.assertIn("canonical_edges", run.call_args_list[1].kwargs["input"])

    def test_query_canonical_edge_explanation_parses_psql_json_object(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        payload = json.dumps(
            {
                "edge": {
                    "source_key": "file:bin/tool",
                    "edge_kind": "executes",
                    "target_key": "tool:nix",
                    "graph_key_version": 1,
                    "identity_metadata": {},
                    "identity_metadata_hash": hash_text,
                    "metadata": {},
                    "confidence": "extracted",
                    "conflict": False,
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                },
                "evidence": [],
            }
        )

        with patch("repomap_kg.storage.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["psql"],
                0,
                stdout=payload + "\n",
            )

            record = query_canonical_edge_explanation(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_key="file:bin/tool",
                kind="executes",
                target_key="tool:nix",
                identity_metadata_hash=hash_text,
            )

        self.assertEqual(record.edge.target_key, "tool:nix")
        self.assertEqual(record.evidence, ())
        sql = run.call_args.kwargs["input"]
        self.assertIn("canonical_edges", sql)
        self.assertIn(f"canonical_edges.identity_metadata_hash = '{hash_text}'", sql)

    def test_query_canonical_neighborhood_parses_psql_json_object(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        payload = json.dumps(
            {
                "center": {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                },
                "nodes": [
                    {
                        "canonical_key": "file:bin/tool",
                        "graph_key_version": 1,
                        "kind": "file",
                        "display_name": "bin/tool",
                        "confidence": "extracted",
                        "conflict": False,
                        "metadata": {},
                        "first_seen_run_id": 10,
                        "last_seen_run_id": 12,
                    }
                ],
                "edges": [
                    {
                        "source_key": "file:bin/tool",
                        "edge_kind": "executes",
                        "target_key": "tool:nix",
                        "graph_key_version": 1,
                        "identity_metadata": {},
                        "identity_metadata_hash": hash_text,
                        "metadata": {},
                        "confidence": "extracted",
                        "conflict": False,
                        "first_seen_run_id": 10,
                        "last_seen_run_id": 12,
                    }
                ],
            }
        )

        with patch("repomap_kg.storage.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ["psql"],
                0,
                stdout=payload + "\n",
            )

            record = query_canonical_neighborhood(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                node="tool:nix",
                direction="in",
            )

        self.assertEqual(record.center.canonical_key, "tool:nix")
        self.assertEqual(record.nodes[0].canonical_key, "file:bin/tool")
        self.assertEqual(record.edges[0].target_key, "tool:nix")
        sql = run.call_args.kwargs["input"]
        self.assertIn("canonical_nodes", sql)
        self.assertIn("canonical_edges", sql)

    def test_query_canonical_neighborhood_rejects_depth_above_one(self):
        with self.assertRaisesRegex(
            StorageSchemaError,
            "canonical-neighborhood only supports depth 1",
        ):
            query_canonical_neighborhood(
                [],
                root_path="/tmp/fixture",
                node="tool:nix",
                depth=2,
            )

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

    def test_query_canonical_storage_summary_returns_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"runs":1,"files":2,'
                '"legacy_nodes":5,"legacy_edges":2,"legacy_evidence":3,'
                '"raw_observations":4,'
                '"canonical_nodes":6,'
                '"canonical_edges":7,'
                '"canonical_evidence":8}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_canonical_storage_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.legacy_nodes, 5)
        self.assertEqual(summary.raw_observations, 4)
        self.assertEqual(summary.canonical_nodes, 6)
        self.assertEqual(summary.canonical_edges, 7)
        self.assertEqual(summary.canonical_evidence, 8)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn(
            "COUNT(*) FROM canonical_nodes",
            run.call_args.kwargs["input"],
        )

    def test_query_canonical_storage_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(
                StorageSchemaError,
                "canonical storage summary",
            ):
                query_canonical_storage_summary(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                )

    def test_query_ruby_summary_returns_profile_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"ruby_files":8,'
                '"modules":2,'
                '"classes":4,'
                '"methods":9,'
                '"singleton_methods":1,'
                '"constants":3,'
                '"routes":5,'
                '"test_cases":2,'
                '"test_methods":4,'
                '"references":12,'
                '"gem_dependencies":5,'
                '"vagrant_configs":6,'
                '"rake_tasks":3,'
                '"rake_namespaces":1,'
                '"dynamic_diagnostics":4,'
                '"parse_errors":0,'
                '"profile_counts":{'
                '"gemfile":1,'
                '"gemspec":1,'
                '"hanami":2,'
                '"minitest":2,'
                '"rake":1,'
                '"sinatra":1,'
                '"vagrantfile":1'
                '},'
                '"no_execution":true}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_ruby_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.ruby_files, 8)
        self.assertEqual(summary.routes, 5)
        self.assertEqual(summary.test_methods, 4)
        self.assertEqual(summary.gem_dependencies, 5)
        self.assertEqual(summary.vagrant_configs, 6)
        self.assertEqual(summary.rake_tasks, 3)
        self.assertEqual(summary.dynamic_diagnostics, 4)
        self.assertEqual(summary.profile_counts["sinatra"], 1)
        self.assertTrue(summary.no_execution)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("canonical_nodes.kind LIKE 'ruby.%'", run.call_args.kwargs["input"])

    def test_query_ruby_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "ruby summary"):
                query_ruby_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_js_summary_returns_profile_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"js_files":12,'
                '"modules":12,'
                '"functions":6,'
                '"classes":3,'
                '"methods":2,'
                '"variables":8,'
                '"components":5,'
                '"routes":4,'
                '"test_suites":2,'
                '"test_cases":4,'
                '"references":19,'
                '"imports":10,'
                '"exports":9,'
                '"hooks":3,'
                '"test_expectations":4,'
                '"source_map_references":1,'
                '"frontend_asset_files":2,'
                '"saved_page_asset_files":1,'
                '"test_report_asset_files":1,'
                '"dynamic_diagnostics":6,'
                '"parse_errors":0,'
                '"profile_counts":{'
                '"angular":2,'
                '"generic_javascript":3,'
                '"jest":2,'
                '"react":3,'
                '"test_report_asset":1,'
                '"vue":1'
                '},'
                '"no_execution":true}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_js_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.js_files, 12)
        self.assertEqual(summary.components, 5)
        self.assertEqual(summary.test_cases, 4)
        self.assertEqual(summary.source_map_references, 1)
        self.assertEqual(summary.frontend_asset_files, 2)
        self.assertEqual(summary.test_report_asset_files, 1)
        self.assertEqual(summary.dynamic_diagnostics, 6)
        self.assertEqual(summary.profile_counts["react"], 3)
        self.assertTrue(summary.no_execution)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("canonical_nodes.kind LIKE 'js.%'", run.call_args.kwargs["input"])

    def test_query_js_framework_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"framework_observations":42,'
                '"framework_profiles":{'
                '"node":5,"express":8,"nest":6,"next":7,"jest":9,"jquery":7,'
                '"generic_js":4},'
                '"node":{"entrypoints":2,"requires":4,"exports":3,'
                '"env_references":2},'
                '"express":{"apps":1,"routers":1,"routes":6,"middleware":3,'
                '"error_handlers":1,"dynamic_routes":1},'
                '"nest":{"modules":1,"controllers":2,"providers":3,'
                '"routes":5,"decorators":12},'
                '"next":{"pages":3,"api_routes":1,"app_routes":2,'
                '"components":2,"route_handlers":1},'
                '"jest":{"suites":2,"tests":4,"expectations":6,"mocks":2},'
                '"jquery":{"selectors":4,"events":3,"ajax_references":2,'
                '"plugin_references":1},'
                '"generic_js":{"canonical_routes":6,"canonical_test_suites":2,'
                '"canonical_test_cases":4,"canonical_components":2},'
                '"diagnostics":{"framework_observation_limit":1,'
                '"framework_selector_limit":1},'
                '"safety":{"no_execution":true,"no_fetch":true,'
                '"raw_profile_only":true,"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_js_framework_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.framework_observations, 42)
        self.assertEqual(summary.framework_profiles["express"], 8)
        self.assertEqual(summary.node["entrypoints"], 2)
        self.assertEqual(summary.express["dynamic_routes"], 1)
        self.assertEqual(summary.nest["decorators"], 12)
        self.assertEqual(summary.next["route_handlers"], 1)
        self.assertEqual(summary.jest["mocks"], 2)
        self.assertEqual(summary.jquery["ajax_references"], 2)
        self.assertEqual(summary.generic_js["canonical_routes"], 6)
        self.assertEqual(summary.diagnostics["framework_selector_limit"], 1)
        self.assertTrue(summary.safety["no_execution"])
        self.assertTrue(summary.safety["raw_profile_only"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("node.entrypoint", run.call_args.kwargs["input"])
        self.assertIn("js.framework_reference", run.call_args.kwargs["input"])
        self.assertIn("js.route", run.call_args.kwargs["input"])

    def test_query_js_framework_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "js framework summary"):
                query_js_framework_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_js_framework_summary_empty_payload_keeps_safety_markers(self):
        summary = js_framework_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "framework_observations": 0,
                "framework_profiles": {
                    "node": 0,
                    "express": 0,
                    "nest": 0,
                    "next": 0,
                    "jest": 0,
                    "jquery": 0,
                    "generic_js": 0,
                },
                "node": {
                    "entrypoints": 0,
                    "requires": 0,
                    "exports": 0,
                    "env_references": 0,
                },
                "express": {
                    "apps": 0,
                    "routers": 0,
                    "routes": 0,
                    "middleware": 0,
                    "error_handlers": 0,
                    "dynamic_routes": 0,
                },
                "nest": {
                    "modules": 0,
                    "controllers": 0,
                    "providers": 0,
                    "routes": 0,
                    "decorators": 0,
                },
                "next": {
                    "pages": 0,
                    "api_routes": 0,
                    "app_routes": 0,
                    "components": 0,
                    "route_handlers": 0,
                },
                "jest": {
                    "suites": 0,
                    "tests": 0,
                    "expectations": 0,
                    "mocks": 0,
                },
                "jquery": {
                    "selectors": 0,
                    "events": 0,
                    "ajax_references": 0,
                    "plugin_references": 0,
                },
                "generic_js": {
                    "canonical_routes": 0,
                    "canonical_test_suites": 0,
                    "canonical_test_cases": 0,
                    "canonical_components": 0,
                },
                "diagnostics": {
                    "framework_observation_limit": 0,
                    "framework_selector_limit": 0,
                },
                "safety": {
                    "no_execution": True,
                    "no_fetch": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            }
        )

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.framework_observations, 0)
        self.assertEqual(summary.framework_profiles["node"], 0)
        self.assertEqual(summary.generic_js["canonical_routes"], 0)
        self.assertTrue(summary.safety["no_execution"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])

    def test_query_openapi_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"openapi_observations":64,'
                '"openapi_documents":3,'
                '"spec_families":{"openapi3":2,"swagger2":1},'
                '"openapi":{"info":3,"servers":2,"paths":12,"operations":24,'
                '"parameters":18,"request_bodies":6,"responses":40,'
                '"schemas":15,"components":20,"security_schemes":2,'
                '"tags":5,"examples":4},'
                '"methods":{"GET":10,"POST":5,"PUT":2,"PATCH":1,'
                '"DELETE":2,"OPTIONS":1,"HEAD":1,"TRACE":0},'
                '"references":{"internal_refs":12,"local_file_refs":2,'
                '"remote_refs_not_fetched":3,"external_docs_not_fetched":1,'
                '"refs_not_fetched":4},'
                '"redactions":{"credentialed_urls":1,'
                '"openapi_ref_summaries":2,"text_summaries":3,'
                '"example_summaries":4,"secret_prone_fields":5},'
                '"diagnostics":{"parse_errors":1,"unsupported_specs":1,'
                '"limit_overflows":2,"local_ref_errors":1,'
                '"malformed_specs":1},'
                '"generic_config":{"config_documents":3,"config_paths":120,'
                '"config_references":18,"config_parse_errors":1},'
                '"safety":{"no_fetch":true,"no_api_calls":true,'
                '"no_tool_execution":true,"raw_profile_only":true,'
                '"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_openapi_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.openapi_observations, 64)
        self.assertEqual(summary.openapi_documents, 3)
        self.assertEqual(summary.spec_families["openapi3"], 2)
        self.assertEqual(summary.openapi["operations"], 24)
        self.assertEqual(summary.methods["GET"], 10)
        self.assertEqual(summary.references["remote_refs_not_fetched"], 3)
        self.assertEqual(summary.redactions["secret_prone_fields"], 5)
        self.assertEqual(summary.diagnostics["limit_overflows"], 2)
        self.assertEqual(summary.generic_config["config_paths"], 120)
        self.assertTrue(summary.safety["no_fetch"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("openapi.document", run.call_args.kwargs["input"])
        self.assertIn("openapi.reference", run.call_args.kwargs["input"])
        self.assertIn("config.document", run.call_args.kwargs["input"])

    def test_query_openapi_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "openapi summary"):
                query_openapi_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_openapi_summary_empty_payload_keeps_safety_markers(self):
        summary = openapi_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "openapi_observations": 0,
                "openapi_documents": 0,
                "spec_families": {"openapi3": 0, "swagger2": 0},
                "openapi": {
                    "info": 0,
                    "servers": 0,
                    "paths": 0,
                    "operations": 0,
                    "parameters": 0,
                    "request_bodies": 0,
                    "responses": 0,
                    "schemas": 0,
                    "components": 0,
                    "security_schemes": 0,
                    "tags": 0,
                    "examples": 0,
                },
                "methods": {
                    "GET": 0,
                    "POST": 0,
                    "PUT": 0,
                    "PATCH": 0,
                    "DELETE": 0,
                    "OPTIONS": 0,
                    "HEAD": 0,
                    "TRACE": 0,
                },
                "references": {
                    "internal_refs": 0,
                    "local_file_refs": 0,
                    "remote_refs_not_fetched": 0,
                    "external_docs_not_fetched": 0,
                    "refs_not_fetched": 0,
                },
                "redactions": {
                    "credentialed_urls": 0,
                    "openapi_ref_summaries": 0,
                    "text_summaries": 0,
                    "example_summaries": 0,
                    "secret_prone_fields": 0,
                },
                "diagnostics": {
                    "parse_errors": 0,
                    "unsupported_specs": 0,
                    "limit_overflows": 0,
                    "local_ref_errors": 0,
                    "malformed_specs": 0,
                },
                "generic_config": {
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                    "config_parse_errors": 0,
                },
                "safety": {
                    "no_fetch": True,
                    "no_api_calls": True,
                    "no_tool_execution": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            }
        )

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.openapi_documents, 0)
        self.assertEqual(summary.spec_families["swagger2"], 0)
        self.assertEqual(summary.openapi["responses"], 0)
        self.assertEqual(summary.generic_config["config_references"], 0)
        self.assertTrue(summary.safety["no_fetch"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertEqual(
            openapi_summary_to_jsonable(summary)["safety"]["no_api_calls"],
            True,
        )

    def test_query_terraform_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"terraform_observations":120,'
                '"terraform_files":8,'
                '"file_families":{"tf":5,"tfvars":1,'
                '"terraform.tfvars":1,"auto.tfvars":1},'
                '"terraform":{"blocks":35,"providers":2,'
                '"required_providers":2,"required_versions":1,'
                '"backends":1,"resources":12,"data_sources":2,'
                '"modules":3,"variables":10,"outputs":4,"locals":5,'
                '"moved":1,"imports":1,"checks":1,"removed":1},'
                '"references":{"total":20,"provider_sources":2,'
                '"version_constraints":3,"module_sources":3,'
                '"local_module_refs":1,"remote_refs_not_fetched":2,'
                '"depends_on":4,"provider_aliases":1,'
                '"repo_escape_diagnostics":1},'
                '"tfvars":{"files":3,"variables":8,'
                '"literal_values_exposed":false},'
                '"redactions":{"tfvars_values":8,"secret_like_fields":3,'
                '"credentialed_urls":1,"import_ids":1,"backend_values":1},'
                '"diagnostics":{"parse_errors":1,"limit_overflows":1,'
                '"malformed_hcl":1},'
                '"generic_config":{"config_documents":0,"config_paths":0,'
                '"config_references":0,"file_nodes":8},'
                '"safety":{"no_execution":true,"no_fetch":true,'
                '"no_terraform_cli":true,"no_provider_download":true,'
                '"no_module_download":true,"no_state_access":true,'
                '"tfvars_redacted":true,"raw_profile_only":true,'
                '"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_terraform_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.terraform_observations, 120)
        self.assertEqual(summary.terraform_files, 8)
        self.assertEqual(summary.file_families["tf"], 5)
        self.assertEqual(summary.file_families["auto.tfvars"], 1)
        self.assertEqual(summary.terraform["resources"], 12)
        self.assertEqual(summary.terraform["required_versions"], 1)
        self.assertEqual(summary.references["remote_refs_not_fetched"], 2)
        self.assertEqual(summary.references["repo_escape_diagnostics"], 1)
        self.assertEqual(summary.tfvars["variables"], 8)
        self.assertFalse(summary.tfvars["literal_values_exposed"])
        self.assertEqual(summary.redactions["tfvars_values"], 8)
        self.assertEqual(summary.diagnostics["malformed_hcl"], 1)
        self.assertEqual(summary.generic_config["file_nodes"], 8)
        self.assertTrue(summary.safety["no_terraform_cli"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("terraform.file", run.call_args.kwargs["input"])
        self.assertIn("terraform.reference", run.call_args.kwargs["input"])
        self.assertIn("literal_values_exposed", run.call_args.kwargs["input"])

    def test_query_terraform_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "terraform summary"):
                query_terraform_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_terraform_summary_empty_payload_keeps_safety_markers(self):
        summary = terraform_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "terraform_observations": 0,
                "terraform_files": 0,
                "file_families": {
                    "tf": 0,
                    "tfvars": 0,
                    "terraform.tfvars": 0,
                    "auto.tfvars": 0,
                },
                "terraform": {
                    "blocks": 0,
                    "providers": 0,
                    "required_providers": 0,
                    "required_versions": 0,
                    "backends": 0,
                    "resources": 0,
                    "data_sources": 0,
                    "modules": 0,
                    "variables": 0,
                    "outputs": 0,
                    "locals": 0,
                    "moved": 0,
                    "imports": 0,
                    "checks": 0,
                    "removed": 0,
                },
                "references": {
                    "total": 0,
                    "provider_sources": 0,
                    "version_constraints": 0,
                    "module_sources": 0,
                    "local_module_refs": 0,
                    "remote_refs_not_fetched": 0,
                    "depends_on": 0,
                    "provider_aliases": 0,
                    "repo_escape_diagnostics": 0,
                },
                "tfvars": {
                    "files": 0,
                    "variables": 0,
                    "literal_values_exposed": False,
                },
                "redactions": {
                    "tfvars_values": 0,
                    "secret_like_fields": 0,
                    "credentialed_urls": 0,
                    "import_ids": 0,
                    "backend_values": 0,
                },
                "diagnostics": {
                    "parse_errors": 0,
                    "limit_overflows": 0,
                    "malformed_hcl": 0,
                },
                "generic_config": {
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                    "file_nodes": 0,
                },
                "safety": {
                    "no_execution": True,
                    "no_fetch": True,
                    "no_terraform_cli": True,
                    "no_provider_download": True,
                    "no_module_download": True,
                    "no_state_access": True,
                    "tfvars_redacted": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            }
        )

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.terraform_files, 0)
        self.assertEqual(summary.file_families["terraform.tfvars"], 0)
        self.assertEqual(summary.terraform["resources"], 0)
        self.assertEqual(summary.references["remote_refs_not_fetched"], 0)
        self.assertFalse(summary.tfvars["literal_values_exposed"])
        self.assertTrue(summary.safety["tfvars_redacted"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertEqual(
            terraform_summary_to_jsonable(summary)["safety"]["no_terraform_cli"],
            True,
        )

    def test_query_python_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"python_observations":250,'
                '"package_files":{"requirements":3,"pyproject":1},'
                '"packaging":{"requirements":20,"dependency_groups":4,'
                '"build_systems":1,"entry_points":3,"tool_configs":8},'
                '"tests":{"test_files":12,"unittest_cases":3,'
                '"pytest_tests":20,"test_functions":18,"test_methods":5,'
                '"fixtures":6,"parametrize":2,"assertions":80},'
                '"frameworks":{"flask_apps":1,"flask_blueprints":2,'
                '"flask_routes":8,"fastapi_apps":1,"fastapi_routers":2,'
                '"fastapi_routes":10,"fastapi_dependencies":5,'
                '"django_projects":1,"django_apps":2,'
                '"django_urlpatterns":12,"django_views":10,'
                '"django_models":4,"django_setting_references":8},'
                '"references":{"total":35,"package_refs":15,'
                '"local_file_refs":4,"direct_urls_not_fetched":2,'
                '"index_urls_not_fetched":2,"framework_refs":12},'
                '"redactions":{"credentialed_urls":1,"private_indexes":1,'
                '"secret_like_config":2,"framework_settings":1},'
                '"diagnostics":{"parse_errors":2,"limit_overflows":1,'
                '"dynamic_constructs":3},'
                '"generic_python":{"modules":20,"classes":30,'
                '"functions":80,"methods":60,"imports":40},'
                '"generic_config":{"config_documents":1,"config_paths":60,'
                '"config_references":5},'
                '"dogfooding":{"repo_map_profile_observed":true,'
                '"bounded":true,"generated_report_committed":false},'
                '"safety":{"no_execution":true,"no_imports":true,'
                '"no_test_execution":true,"no_framework_startup":true,'
                '"no_fetch":true,"no_package_install":true,'
                '"no_openapi_fetch":true,"raw_profile_only":true,'
                '"no_new_canonical_namespaces":true}}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_python_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.python_observations, 250)
        self.assertEqual(summary.package_files["requirements"], 3)
        self.assertEqual(summary.packaging["requirements"], 20)
        self.assertEqual(summary.tests["assertions"], 80)
        self.assertEqual(summary.frameworks["fastapi_routes"], 10)
        self.assertEqual(summary.references["direct_urls_not_fetched"], 2)
        self.assertEqual(summary.redactions["credentialed_urls"], 1)
        self.assertEqual(summary.diagnostics["dynamic_constructs"], 3)
        self.assertEqual(summary.generic_python["modules"], 20)
        self.assertEqual(summary.generic_config["config_paths"], 60)
        self.assertTrue(summary.dogfooding["repo_map_profile_observed"])
        self.assertFalse(summary.dogfooding["generated_report_committed"])
        self.assertTrue(summary.safety["no_imports"])
        self.assertTrue(summary.safety["no_new_canonical_namespaces"])
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("python.requirement", run.call_args.kwargs["input"])
        self.assertIn("python.fastapi_route", run.call_args.kwargs["input"])
        self.assertIn("raw_profile_only", run.call_args.kwargs["input"])

    def test_query_python_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "python summary"):
                query_python_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_python_summary_empty_payload_keeps_safety_markers(self):
        summary = python_summary_from_storage_payload(
            {
                "root_path": "/tmp/empty",
                "repository_name": None,
                "python_observations": 0,
                "package_files": {"requirements": 0, "pyproject": 0},
                "packaging": {
                    "requirements": 0,
                    "dependency_groups": 0,
                    "build_systems": 0,
                    "entry_points": 0,
                    "tool_configs": 0,
                },
                "tests": {
                    "test_files": 0,
                    "unittest_cases": 0,
                    "pytest_tests": 0,
                    "test_functions": 0,
                    "test_methods": 0,
                    "fixtures": 0,
                    "parametrize": 0,
                    "assertions": 0,
                },
                "frameworks": {
                    "flask_apps": 0,
                    "flask_blueprints": 0,
                    "flask_routes": 0,
                    "fastapi_apps": 0,
                    "fastapi_routers": 0,
                    "fastapi_routes": 0,
                    "fastapi_dependencies": 0,
                    "django_projects": 0,
                    "django_apps": 0,
                    "django_urlpatterns": 0,
                    "django_views": 0,
                    "django_models": 0,
                    "django_setting_references": 0,
                },
                "references": {
                    "total": 0,
                    "package_refs": 0,
                    "local_file_refs": 0,
                    "direct_urls_not_fetched": 0,
                    "index_urls_not_fetched": 0,
                    "framework_refs": 0,
                },
                "redactions": {
                    "credentialed_urls": 0,
                    "private_indexes": 0,
                    "secret_like_config": 0,
                    "framework_settings": 0,
                },
                "diagnostics": {
                    "parse_errors": 0,
                    "limit_overflows": 0,
                    "dynamic_constructs": 0,
                },
                "generic_python": {
                    "modules": 0,
                    "classes": 0,
                    "functions": 0,
                    "methods": 0,
                    "imports": 0,
                },
                "generic_config": {
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                },
                "dogfooding": {
                    "repo_map_profile_observed": False,
                    "bounded": True,
                    "generated_report_committed": False,
                },
                "safety": {
                    "no_execution": True,
                    "no_imports": True,
                    "no_test_execution": True,
                    "no_framework_startup": True,
                    "no_fetch": True,
                    "no_package_install": True,
                    "no_openapi_fetch": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            }
        )

        self.assertEqual(summary.repository_name, None)
        self.assertEqual(summary.python_observations, 0)
        self.assertEqual(summary.package_files["requirements"], 0)
        self.assertEqual(summary.tests["pytest_tests"], 0)
        self.assertEqual(summary.frameworks["django_models"], 0)
        self.assertEqual(summary.references["direct_urls_not_fetched"], 0)
        self.assertFalse(summary.dogfooding["repo_map_profile_observed"])
        self.assertTrue(summary.dogfooding["bounded"])
        self.assertTrue(summary.safety["no_execution"])
        self.assertTrue(summary.safety["no_imports"])
        self.assertEqual(
            python_summary_to_jsonable(summary)["safety"]["no_package_install"],
            True,
        )

    def test_query_js_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "js summary"):
                query_js_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_email_summary_returns_safe_counts(self):
        completed = SimpleNamespace(
            stdout=(
                '{"root_path":"/tmp/fixture",'
                '"repository_name":"fixture",'
                '"mailboxes":1,'
                '"messages":10,'
                '"eml_messages":8,'
                '"mbox_messages":2,'
                '"addresses":6,'
                '"address_observations":12,'
                '"address_domains":1,'
                '"mime_parts":22,'
                '"text_plain_parts":9,'
                '"text_html_parts":4,'
                '"attachment_stubs":3,'
                '"inline_attachments":1,'
                '"content_id_parts":1,'
                '"thread_hints":5,'
                '"message_references":4,'
                '"external_url_references":1,'
                '"list_unsubscribe_references":1,'
                '"parse_errors":2,'
                '"malformed_or_oversized_diagnostics":2,'
                '"message_id_present":9,'
                '"message_id_missing_or_invalid":1,'
                '"messages_with_attachments":2,'
                '"messages_with_html":4,'
                '"messages_with_plain":9,'
                '"mailbox_limits":1,'
                '"no_provider_api":true,'
                '"no_mutation":true,'
                '"no_body_text":true,'
                '"no_attachment_content":true}\n'
            )
        )

        with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
            summary = query_email_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                psql_command="/bin/psql",
            )

        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.mailboxes, 1)
        self.assertEqual(summary.messages, 10)
        self.assertEqual(summary.eml_messages, 8)
        self.assertEqual(summary.mbox_messages, 2)
        self.assertEqual(summary.address_domains, 1)
        self.assertEqual(summary.text_html_parts, 4)
        self.assertEqual(summary.attachment_stubs, 3)
        self.assertEqual(summary.message_references, 4)
        self.assertEqual(summary.list_unsubscribe_references, 1)
        self.assertEqual(summary.message_id_missing_or_invalid, 1)
        self.assertEqual(summary.mailbox_limits, 1)
        self.assertTrue(summary.no_provider_api)
        self.assertTrue(summary.no_mutation)
        self.assertTrue(summary.no_body_text)
        self.assertTrue(summary.no_attachment_content)
        self.assertIn("-qAt", run.call_args.args[0])
        self.assertIn("canonical_nodes.kind LIKE 'email.%'", run.call_args.kwargs["input"])

    def test_query_email_summary_rejects_malformed_json(self):
        completed = SimpleNamespace(stdout='{"root_path": "/tmp/fixture"}\n')

        with patch("repomap_kg.storage.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(StorageSchemaError, "email summary"):
                query_email_summary(["-d", "postgres"], root_path="/tmp/fixture")

    def test_query_bulk_summary_combines_manifests_and_bulk_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / ".repomap" / "bulk-runs" / "source-one" / "run-one"
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "bulk_run_id": "run-one",
                        "source_id": "source-one",
                        "source_type": "local.directory",
                        "corpus_kind": "mixed_corpus",
                        "policy_status": "allowed_with_limits",
                        "file_count_included": 3,
                        "file_count_skipped": 2,
                        "total_bytes_included": 123,
                        "limit_hit": True,
                        "limit_reason": "max_files_exceeded",
                        "extractor_counts": {"eml": 1, "javascript": 1},
                        "diagnostic_counts": {"extractor_error": 1},
                        "redaction_counts": {"raw_observations": 2},
                        "skipped_files": [
                            {"relative_path": ".hidden/a.eml", "reason": "hidden_excluded"},
                            {"relative_path": "archive/export.zip", "reason": "archive_deferred"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            completed = SimpleNamespace(
                stdout=(
                    '{"repository_name":"fixture",'
                    '"observations_with_bulk_provenance":7,'
                    '"redacted_observations":2}\n'
                )
            )

            with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
                summary = query_bulk_summary(
                    ["-d", "postgres"],
                    root_path=str(root),
                    psql_command="/bin/psql",
                )

        self.assertEqual(summary.root_path_summary, ".")
        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.bulk_runs, 1)
        self.assertEqual(summary.sources, 1)
        self.assertEqual(summary.source_ids, ("source-one",))
        self.assertEqual(summary.corpus_kinds["mixed_corpus"], 1)
        self.assertEqual(summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(summary.file_count_included, 3)
        self.assertEqual(summary.file_count_skipped, 2)
        self.assertEqual(summary.extractor_counts["eml"], 1)
        self.assertEqual(summary.skip_reasons["archive_deferred"], 1)
        self.assertEqual(summary.archive_deferred, 1)
        self.assertEqual(summary.limit_hit_count, 1)
        self.assertEqual(summary.max_files_hit_count, 1)
        self.assertEqual(summary.observations_with_bulk_provenance, 7)
        self.assertEqual(summary.redaction_counts["raw_observations"], 2)
        self.assertTrue(summary.no_provider_api)
        self.assertTrue(summary.no_external_fetch)
        self.assertTrue(summary.no_source_mutation)
        self.assertTrue(summary.no_archive_decompression)
        self.assertIn("payload_json->'metadata' ? 'bulk_run_id'", run.call_args.kwargs["input"])

    def test_query_bulk_summary_empty_repo_returns_zero_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = SimpleNamespace(
                stdout=(
                    '{"repository_name":null,'
                    '"observations_with_bulk_provenance":0,'
                    '"redacted_observations":0}\n'
                )
            )

            with patch("repomap_kg.storage.subprocess.run", return_value=completed):
                summary = query_bulk_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.bulk_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.file_count_included, 0)
        self.assertEqual(summary.file_count_skipped, 0)
        self.assertEqual(summary.extractor_counts, {})
        self.assertEqual(summary.skip_reasons, {})
        self.assertEqual(summary.observations_with_bulk_provenance, 0)
        self.assertTrue(summary.no_provider_api)

    def test_query_bulk_summary_rejects_escaped_manifest_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as escaped_tmpdir:
                root = Path(tmpdir)
                escaped_root = Path(escaped_tmpdir) / "bulk-runs"
                escaped_root.mkdir()
                (root / ".repomap").mkdir()
                (root / ".repomap" / "bulk-runs").symlink_to(
                    escaped_root,
                    target_is_directory=True,
                )
                completed = SimpleNamespace(
                    stdout=(
                        '{"repository_name":null,'
                        '"observations_with_bulk_provenance":0,'
                        '"redacted_observations":0}\n'
                    )
                )

                with patch("repomap_kg.storage.subprocess.run", return_value=completed):
                    summary = query_bulk_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.bulk_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.diagnostic_counts["manifest_parse_error"], 1)
        self.assertTrue(summary.no_provider_api)

    def test_query_bulk_summary_rejects_malformed_storage_json(self):
        completed = SimpleNamespace(stdout='{"repository_name": "fixture"}\n')

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("repomap_kg.storage.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(StorageSchemaError, "bulk summary"):
                    query_bulk_summary(["-d", "postgres"], root_path=tmpdir)

    def test_query_api_summary_combines_manifests_and_api_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / ".repomap" / "api-runs" / "source-one" / "run-one"
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "api_run_id": "run-one",
                        "source_id": "source-one",
                        "source_type": "api.rest",
                        "api_source_class": "api.custom_documented_api",
                        "provider_name": "Fixture Provider",
                        "provider_product": "Fixture API",
                        "policy_status": "allowed_with_limits",
                        "requests": [
                            {
                                "endpoint_name": "items",
                                "method": "GET",
                                "path": "/v1/items",
                                "response_type": "application/json",
                                "downstream_route": "config",
                            }
                        ],
                        "responses": [
                            {
                                "endpoint_name": "items",
                                "method": "GET",
                                "path_template": "/v1/items",
                                "response_type": "application/json",
                                "response_byte_count": 512,
                                "redacted": True,
                                "downstream_route": "config",
                                "artifact_path": "artifacts/items.json",
                            }
                        ],
                        "no_network": True,
                        "no_mutation": True,
                        "no_credentials_resolved": True,
                        "no_scheduler": True,
                    }
                ),
                encoding="utf-8",
            )
            completed = SimpleNamespace(
                stdout=(
                    '{"repository_name":"fixture",'
                    '"observations_with_api_provenance":7,'
                    '"config_documents_from_api":1}\n'
                )
            )

            with patch("repomap_kg.storage.subprocess.run", return_value=completed) as run:
                summary = query_api_summary(
                    ["-d", "postgres"],
                    root_path=str(root),
                    psql_command="/bin/psql",
                )

        self.assertEqual(summary.root_path_summary, ".")
        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.api_runs, 1)
        self.assertEqual(summary.sources, 1)
        self.assertEqual(summary.source_ids, ("source-one",))
        self.assertEqual(summary.source_types["api.rest"], 1)
        self.assertEqual(summary.api_source_classes["api.custom_documented_api"], 1)
        self.assertEqual(summary.provider_names["Fixture Provider"], 1)
        self.assertEqual(summary.provider_products["Fixture API"], 1)
        self.assertEqual(summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.responses, 1)
        self.assertEqual(summary.endpoints, 1)
        self.assertEqual(summary.endpoint_names, ("items",))
        self.assertEqual(summary.methods["GET"], 1)
        self.assertEqual(summary.downstream_routes["config"], 1)
        self.assertEqual(summary.response_types["application/json"], 1)
        self.assertEqual(summary.response_byte_count, 512)
        self.assertEqual(summary.redacted_responses, 1)
        self.assertEqual(summary.routed_artifacts, 1)
        self.assertEqual(summary.observations_with_api_provenance, 7)
        self.assertEqual(summary.config_documents_from_api, 1)
        self.assertTrue(summary.no_network)
        self.assertTrue(summary.no_mutation)
        self.assertTrue(summary.no_credentials_resolved)
        self.assertTrue(summary.no_scheduler)
        self.assertTrue(summary.no_provider_specific_behavior)
        self.assertIn("payload_json->'metadata' ? 'api_run_id'", run.call_args.kwargs["input"])

    def test_query_api_summary_empty_repo_returns_zero_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = SimpleNamespace(
                stdout=(
                    '{"repository_name":null,'
                    '"observations_with_api_provenance":0,'
                    '"config_documents_from_api":0}\n'
                )
            )

            with patch("repomap_kg.storage.subprocess.run", return_value=completed):
                summary = query_api_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.api_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.requests, 0)
        self.assertEqual(summary.responses, 0)
        self.assertEqual(summary.observations_with_api_provenance, 0)
        self.assertEqual(summary.config_documents_from_api, 0)
        self.assertTrue(summary.no_network)
        self.assertTrue(summary.no_mutation)

    def test_query_api_summary_rejects_escaped_manifest_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as escaped_tmpdir:
                root = Path(tmpdir)
                escaped_root = Path(escaped_tmpdir) / "api-runs"
                escaped_root.mkdir()
                (root / ".repomap").mkdir()
                (root / ".repomap" / "api-runs").symlink_to(
                    escaped_root,
                    target_is_directory=True,
                )
                completed = SimpleNamespace(
                    stdout=(
                        '{"repository_name":null,'
                        '"observations_with_api_provenance":0,'
                        '"config_documents_from_api":0}\n'
                    )
                )

                with patch("repomap_kg.storage.subprocess.run", return_value=completed):
                    summary = query_api_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.api_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.diagnostic_counts["manifest_parse_error"], 1)
        self.assertTrue(summary.no_network)

    def test_query_api_summary_rejects_malformed_storage_json(self):
        completed = SimpleNamespace(stdout='{"repository_name": "fixture"}\n')

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("repomap_kg.storage.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(StorageSchemaError, "api summary"):
                    query_api_summary(["-d", "postgres"], root_path=tmpdir)

    def test_email_summary_payload_parser_preserves_safe_counts(self):
        summary = email_summary_from_storage_payload(
            {
                "root_path": "/tmp/fixture",
                "repository_name": "fixture",
                "mailboxes": 1,
                "messages": 10,
                "eml_messages": 8,
                "mbox_messages": 2,
                "addresses": 6,
                "address_observations": 12,
                "address_domains": 1,
                "mime_parts": 22,
                "text_plain_parts": 9,
                "text_html_parts": 4,
                "attachment_stubs": 3,
                "inline_attachments": 1,
                "content_id_parts": 1,
                "thread_hints": 5,
                "message_references": 4,
                "external_url_references": 1,
                "list_unsubscribe_references": 1,
                "parse_errors": 2,
                "malformed_or_oversized_diagnostics": 2,
                "message_id_present": 9,
                "message_id_missing_or_invalid": 1,
                "messages_with_attachments": 2,
                "messages_with_html": 4,
                "messages_with_plain": 9,
                "mailbox_limits": 1,
                "no_provider_api": True,
                "no_mutation": True,
                "no_body_text": True,
                "no_attachment_content": True,
            }
        )

        self.assertEqual(summary.root_path, "/tmp/fixture")
        self.assertEqual(summary.mailboxes, 1)
        self.assertEqual(summary.messages, 10)
        self.assertEqual(summary.address_observations, 12)
        self.assertEqual(summary.content_id_parts, 1)
        self.assertEqual(summary.malformed_or_oversized_diagnostics, 2)
        self.assertTrue(summary.no_body_text)
        self.assertEqual(email_summary_to_jsonable(summary), summary.to_dict())

    def test_bulk_summary_payload_parser_preserves_safe_counts(self):
        summary = bulk_summary_from_storage_payload(
            {
                "root_path_summary": ".",
                "repository_name": "fixture",
                "bulk_runs": 2,
                "sources": 2,
                "source_ids": ["email-export", "mixed-corpus"],
                "corpus_kinds": {"email_export": 1, "mixed_corpus": 1},
                "policy_statuses": {"allowed_with_limits": 2},
                "file_count_included": 12,
                "file_count_skipped": 5,
                "total_bytes_included": 4096,
                "extractor_counts": {"eml": 3, "javascript": 1},
                "skip_reasons": {"archive_deferred": 1, "hidden_excluded": 1},
                "diagnostic_counts": {"extractor_error": 1},
                "redaction_counts": {"raw_observations": 2},
                "limit_hit_count": 1,
                "max_files_hit_count": 1,
                "max_total_bytes_hit_count": 0,
                "max_file_bytes_hit_count": 0,
                "max_depth_hit_count": 0,
                "archive_deferred": 1,
                "warc_deferred": 0,
                "email_export_runs": 1,
                "mixed_corpus_runs": 1,
                "observations_with_bulk_provenance": 42,
                "no_provider_api": True,
                "no_external_fetch": True,
                "no_source_mutation": True,
                "no_archive_decompression": True,
            }
        )

        self.assertEqual(summary.source_ids, ("email-export", "mixed-corpus"))
        self.assertEqual(summary.corpus_kinds["mixed_corpus"], 1)
        self.assertEqual(summary.extractor_counts["eml"], 3)
        self.assertEqual(summary.skip_reasons["archive_deferred"], 1)
        self.assertEqual(summary.observations_with_bulk_provenance, 42)
        self.assertTrue(summary.no_archive_decompression)
        self.assertEqual(bulk_summary_to_jsonable(summary), summary.to_dict())

    def test_api_summary_payload_parser_preserves_safe_counts(self):
        summary = api_summary_from_storage_payload(
            {
                "root_path_summary": ".",
                "repository_name": "fixture",
                "api_runs": 1,
                "sources": 1,
                "source_ids": ["fixture-readonly-api"],
                "source_types": {"api.rest": 1},
                "api_source_classes": {"api.custom_documented_api": 1},
                "provider_names": {"Fixture Provider": 1},
                "provider_products": {"Fixture API": 1},
                "policy_statuses": {"allowed_with_limits": 1},
                "requests": 1,
                "responses": 1,
                "endpoints": 1,
                "endpoint_names": ["items"],
                "methods": {"GET": 1},
                "downstream_routes": {"config": 1},
                "response_types": {"application/json": 1},
                "response_byte_count": 512,
                "redacted_responses": 1,
                "diagnostic_counts": {},
                "routed_artifacts": 1,
                "observations_with_api_provenance": 7,
                "config_documents_from_api": 1,
                "no_network": True,
                "no_mutation": True,
                "no_credentials_resolved": True,
                "no_scheduler": True,
                "no_provider_specific_behavior": True,
            }
        )

        self.assertEqual(summary.source_ids, ("fixture-readonly-api",))
        self.assertEqual(summary.provider_names["Fixture Provider"], 1)
        self.assertEqual(summary.endpoint_names, ("items",))
        self.assertEqual(summary.methods["GET"], 1)
        self.assertEqual(summary.observations_with_api_provenance, 7)
        self.assertTrue(summary.no_credentials_resolved)
        self.assertEqual(api_summary_to_jsonable(summary), summary.to_dict())

    def test_js_summary_payload_parser_preserves_safe_counts(self):
        summary = js_summary_from_storage_payload(
            {
                "root_path": "/tmp/fixture",
                "repository_name": "fixture",
                "js_files": 5,
                "modules": 5,
                "functions": 2,
                "classes": 1,
                "methods": 1,
                "variables": 4,
                "components": 3,
                "routes": 2,
                "test_suites": 1,
                "test_cases": 2,
                "references": 8,
                "imports": 4,
                "exports": 3,
                "hooks": 2,
                "test_expectations": 2,
                "source_map_references": 1,
                "frontend_asset_files": 1,
                "saved_page_asset_files": 0,
                "test_report_asset_files": 1,
                "dynamic_diagnostics": 3,
                "parse_errors": 0,
                "profile_counts": {"jest": 1, "react": 2},
                "no_execution": True,
            }
        )

        self.assertEqual(summary.root_path, "/tmp/fixture")
        self.assertEqual(summary.profile_counts, {"jest": 1, "react": 2})
        self.assertEqual(summary.components, 3)
        self.assertEqual(summary.source_map_references, 1)
        self.assertTrue(summary.no_execution)
        self.assertEqual(js_summary_to_jsonable(summary), summary.to_dict())

    def test_ruby_summary_payload_parser_preserves_safe_counts(self):
        summary = ruby_summary_from_storage_payload(
            {
                "root_path": "/tmp/fixture",
                "repository_name": "fixture",
                "ruby_files": 3,
                "modules": 1,
                "classes": 2,
                "methods": 4,
                "singleton_methods": 1,
                "constants": 2,
                "routes": 3,
                "test_cases": 1,
                "test_methods": 2,
                "references": 5,
                "gem_dependencies": 4,
                "vagrant_configs": 3,
                "rake_tasks": 2,
                "rake_namespaces": 1,
                "dynamic_diagnostics": 2,
                "parse_errors": 0,
                "profile_counts": {"minitest": 1, "sinatra": 1},
                "no_execution": True,
            }
        )

        self.assertEqual(summary.root_path, "/tmp/fixture")
        self.assertEqual(summary.profile_counts, {"minitest": 1, "sinatra": 1})
        self.assertEqual(summary.test_methods, 2)
        self.assertTrue(summary.no_execution)
        self.assertEqual(ruby_summary_to_jsonable(summary), summary.to_dict())

    def test_build_source_feed_queries_use_read_only_metadata_filters(self):
        sources_sql = build_ingested_source_query_sql(
            "/tmp/fixture",
            source_type="feed.rss",
            policy_status="allowed_with_limits",
            limit=10,
        )
        self.assertIn("raw_observations", sources_sql)
        self.assertIn("source_id_configured", sources_sql)
        self.assertIn("source_type = 'feed.rss'", sources_sql)
        self.assertIn("source_policy_status = 'allowed_with_limits'", sources_sql)
        self.assertIn("LIMIT 10", sources_sql)
        self.assertNotIn("INSERT ", sources_sql.upper())
        self.assertNotIn("UPDATE ", sources_sql.upper())

        summary_sql = build_source_summary_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
        )
        self.assertIn("canonical_nodes.kind = 'feed.item'", summary_sql)
        self.assertIn("source_id_configured = 'example-news-feed'", summary_sql)

        runs_sql = build_source_run_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
            limit=5,
        )
        self.assertIn("source_run_id", runs_sql)
        self.assertIn("ORDER BY source_acquired_at DESC", runs_sql)

        items_sql = build_source_feed_item_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
            source_run_id="20260630T120000Z",
            limit=25,
        )
        self.assertIn("feed.item", items_sql)
        self.assertIn("source_run_id = '20260630T120000Z'", items_sql)
        self.assertIn("canonical_nodes.canonical_key", items_sql)
        self.assertIn("LIMIT 25) item_rows", items_sql)

        references_sql = build_source_reference_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
            target_kind="external.url",
            limit=25,
        )
        self.assertIn("canonical_edges.edge_kind = 'references'", references_sql)
        self.assertIn("external.url", references_sql)
        self.assertIn("LIMIT 25) reference_rows", references_sql)

    def test_source_feed_payload_parsers_preserve_safe_summary_fields(self):
        source = ingested_source_record_from_storage_payload(
            {
                "source_id": "example-news-feed",
                "source_type": "feed.rss",
                "display_name": "Example News Feed",
                "policy_status": "allowed_with_limits",
                "latest_source_run_id": "20260630T120000Z",
                "latest_artifact_id": "abc123",
                "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                "latest_acquired_at": "2026-06-30T12:00:00Z",
                "feed_observation_count": 8,
                "canonical_feed_item_count": 2,
            }
        )
        self.assertEqual(source.source_id, "example-news-feed")
        self.assertEqual(source.canonical_feed_item_count, 2)

        summary = source_summary_from_storage_payload(
            {
                "source_id": "example-news-feed",
                "source_type": "feed.rss",
                "display_name": "Example News Feed",
                "policy_status": "allowed_with_limits",
                "configured_url_summary": "https://example.invalid/feed.xml",
                "latest_source_run_id": "20260630T120000Z",
                "latest_artifact_id": "abc123",
                "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                "latest_acquired_at": "2026-06-30T12:00:00Z",
                "feed_documents": 1,
                "feed_channels": 1,
                "feed_items": 2,
                "feed_authors": 1,
                "feed_categories": 2,
                "link_references": 2,
                "enclosure_references": 1,
                "parse_errors": 0,
                "known_limitations": ["source metadata is inferred from RSS2 evidence"],
            }
        )
        self.assertEqual(summary.feed_items, 2)
        self.assertEqual(
            summary.known_limitations[0],
            "source metadata is inferred from RSS2 evidence",
        )

        run = source_run_record_from_storage_payload(
            {
                "source_run_id": "20260630T120000Z",
                "acquired_at": "2026-06-30T12:00:00Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                "artifact_byte_length": 512,
                "artifact_sha256": "0" * 64,
                "http_status": 200,
                "content_type": "application/rss+xml",
                "observation_count": 8,
                "status_summary": "ok",
            }
        )
        self.assertEqual(run.artifact_byte_length, 512)

        item_key = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
        )
        item = source_feed_item_record_from_storage_payload(
            {
                "item_key": item_key,
                "title": "Release note",
                "published_at": "2026-06-30T12:00:00Z",
                "updated_at": None,
                "identity_source": "guid",
                "identity_strength": "strong",
                "duplicate_identity": False,
                "link_targets": ["external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1"],
                "authors": ["Example Author"],
                "categories": ["release"],
                "source_run_id": "20260630T120000Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
            }
        )
        self.assertEqual(item.identity_strength, "strong")
        self.assertEqual(
            item.link_targets,
            ("external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",),
        )

        reference = source_reference_record_from_storage_payload(
            {
                "source_item_key": item.item_key,
                "relation": "references",
                "target_key": "external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",
                "target_display": "https://example.invalid/items/1",
                "not_fetched": True,
                "media_type": "text/html",
                "source_run_id": "20260630T120000Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
            }
        )
        self.assertTrue(reference.not_fetched)

    def test_query_source_feed_helpers_parse_psql_json(self):
        item_key = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
        )
        payloads = [
            json.dumps(
                [
                    {
                        "source_id": "example-news-feed",
                        "source_type": "feed.rss",
                        "display_name": "Example News Feed",
                        "policy_status": "allowed_with_limits",
                        "latest_source_run_id": "20260630T120000Z",
                        "latest_artifact_id": "abc123",
                        "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                        "latest_acquired_at": "2026-06-30T12:00:00Z",
                        "feed_observation_count": 8,
                        "canonical_feed_item_count": 2,
                    }
                ]
            ),
            json.dumps(
                {
                    "source_id": "example-news-feed",
                    "source_type": "feed.rss",
                    "display_name": "Example News Feed",
                    "policy_status": "allowed_with_limits",
                    "configured_url_summary": "https://example.invalid/feed.xml",
                    "latest_source_run_id": "20260630T120000Z",
                    "latest_artifact_id": "abc123",
                    "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                    "latest_acquired_at": "2026-06-30T12:00:00Z",
                    "feed_documents": 1,
                    "feed_channels": 1,
                    "feed_items": 2,
                    "feed_authors": 0,
                    "feed_categories": 0,
                    "link_references": 1,
                    "enclosure_references": 0,
                    "parse_errors": 0,
                    "known_limitations": [],
                }
            ),
            json.dumps(
                [
                    {
                        "source_run_id": "20260630T120000Z",
                        "acquired_at": "2026-06-30T12:00:00Z",
                        "artifact_id": "abc123",
                        "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                        "artifact_byte_length": 512,
                        "artifact_sha256": "0" * 64,
                        "http_status": 200,
                        "content_type": "application/rss+xml",
                        "observation_count": 8,
                        "status_summary": "ok",
                    }
                ]
            ),
            json.dumps(
                [
                    {
                        "item_key": item_key,
                        "title": "Release note",
                        "published_at": "2026-06-30T12:00:00Z",
                        "updated_at": None,
                        "identity_source": "guid",
                        "identity_strength": "strong",
                        "duplicate_identity": False,
                        "link_targets": [],
                        "authors": [],
                        "categories": [],
                        "source_run_id": "20260630T120000Z",
                        "artifact_id": "abc123",
                        "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                    }
                ]
            ),
            json.dumps(
                [
                    {
                        "source_item_key": item_key,
                        "relation": "references",
                        "target_key": "external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",
                        "target_display": "https://example.invalid/items/1",
                        "not_fetched": True,
                        "media_type": None,
                        "source_run_id": "20260630T120000Z",
                        "artifact_id": "abc123",
                        "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                    }
                ]
            ),
        ]
        with patch("repomap_kg.storage.subprocess.run") as run:
            run.side_effect = [
                subprocess.CompletedProcess(["psql"], 0, stdout=f"{payload}\n")
                for payload in payloads
            ]
            sources = query_ingested_source_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )
            summary = query_source_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )
            runs = query_source_run_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )
            items = query_source_feed_item_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )
            references = query_source_reference_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )

        self.assertEqual(sources[0].source_id, "example-news-feed")
        self.assertEqual(summary.feed_items, 2)
        self.assertEqual(runs[0].source_run_id, "20260630T120000Z")
        self.assertEqual(items[0].item_key, item_key)
        self.assertEqual(references[0].relation, "references")
        for call in run.call_args_list:
            sql = call.kwargs["input"]
            self.assertNotIn("INSERT ", sql.upper())
            self.assertNotIn("UPDATE ", sql.upper())

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

    def test_build_canonical_storage_summary_query_sql_counts_canonical_tables(self):
        sql = build_canonical_storage_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("COUNT(*) FROM runs", sql)
        self.assertIn("COUNT(*) FROM files", sql)
        self.assertIn("COUNT(*) FROM nodes", sql)
        self.assertIn("COUNT(*) FROM edges", sql)
        self.assertIn("COUNT(*) FROM evidence", sql)
        self.assertIn("COUNT(*) FROM raw_observations", sql)
        self.assertIn("COUNT(*) FROM canonical_nodes", sql)
        self.assertIn("COUNT(*) FROM canonical_edges", sql)
        self.assertIn("COUNT(*) FROM canonical_evidence", sql)

    def test_build_ruby_summary_query_sql_counts_ruby_profiles_and_evidence(self):
        sql = build_ruby_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'ruby.file')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'ruby.route')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'ruby.test_method')", sql)
        self.assertIn("canonical_edges.edge_kind = 'references'", sql)
        self.assertIn("raw_observations.kind = 'ruby.gem_dependency'", sql)
        self.assertIn("raw_observations.kind = 'ruby.vagrant_config'", sql)
        self.assertIn("raw_observations.kind = 'ruby.dsl'", sql)
        self.assertIn("raw_observations.kind = 'ruby.parse_error'", sql)
        self.assertIn("profile_counts", sql)
        self.assertIn("'no_execution', true", sql)

    def test_build_js_summary_query_sql_counts_js_profiles_and_evidence(self):
        sql = build_js_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'js.file')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'js.component')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'js.test_case')", sql)
        self.assertIn("canonical_edges.edge_kind = 'references'", sql)
        self.assertIn("raw_observations.kind = 'js.import'", sql)
        self.assertIn("raw_observations.kind = 'js.export'", sql)
        self.assertIn("raw_observations.kind = 'js.hook'", sql)
        self.assertIn("raw_observations.kind = 'js.test_expectation'", sql)
        self.assertIn("raw_observations.kind = 'js.parse_error'", sql)
        self.assertIn("source_map_references", sql)
        self.assertIn("frontend_asset_files", sql)
        self.assertIn("test_report_asset_files", sql)
        self.assertIn("profile_counts", sql)
        self.assertIn("'no_execution', true", sql)

    def test_build_email_summary_query_sql_counts_safe_email_facts(self):
        sql = build_email_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("canonical_nodes.kind LIKE 'email.%'", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'email.mailbox')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'email.message')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'email.address')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'email.part')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'email.attachment_stub')", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'email.thread_hint')", sql)
        self.assertIn("canonical_edges.edge_kind = 'references'", sql)
        self.assertIn("raw_observations.kind = 'email.address'", sql)
        self.assertIn("raw_observations.kind = 'email.reference'", sql)
        self.assertIn("raw_observations.kind = 'email.parse_error'", sql)
        self.assertIn("list_unsubscribe_references", sql)
        self.assertIn("mailbox_limits", sql)
        self.assertIn("'no_provider_api', true", sql)
        self.assertIn("'no_mutation', true", sql)
        self.assertIn("'no_body_text', true", sql)
        self.assertIn("'no_attachment_content', true", sql)

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

    def test_format_canonical_storage_summary_table_uses_count_columns(self):
        table = format_canonical_storage_summary_table(
            CanonicalStorageSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                runs=1,
                files=2,
                legacy_nodes=5,
                legacy_edges=2,
                legacy_evidence=3,
                raw_observations=4,
                canonical_nodes=6,
                canonical_edges=7,
                canonical_evidence=8,
            )
        )

        self.assertIn("root_path", table)
        self.assertIn("legacy_nodes", table)
        self.assertIn("canonical_nodes", table)
        self.assertIn("canonical_edges", table)
        self.assertIn("/tmp/fixture", table)

    def test_format_ruby_summary_table_uses_profile_and_readback_columns(self):
        table = format_ruby_summary_table(
            RubySummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                ruby_files=8,
                modules=2,
                classes=4,
                methods=9,
                singleton_methods=1,
                constants=3,
                routes=5,
                test_cases=2,
                test_methods=4,
                references=12,
                gem_dependencies=5,
                vagrant_configs=6,
                rake_tasks=3,
                rake_namespaces=1,
                dynamic_diagnostics=4,
                parse_errors=0,
                profile_counts={"minitest": 2, "sinatra": 1},
                no_execution=True,
            )
        )

        self.assertIn("ruby_files", table)
        self.assertIn("routes", table)
        self.assertIn("test_methods", table)
        self.assertIn("gem_dependencies", table)
        self.assertIn("profile_counts", table)
        self.assertIn("minitest=2", table)
        self.assertIn("no_execution", table)

    def test_format_js_summary_table_uses_profile_and_readback_columns(self):
        table = format_js_summary_table(
            JSSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                js_files=12,
                modules=12,
                functions=6,
                classes=3,
                methods=2,
                variables=8,
                components=5,
                routes=4,
                test_suites=2,
                test_cases=4,
                references=19,
                imports=10,
                exports=9,
                hooks=3,
                test_expectations=4,
                source_map_references=1,
                frontend_asset_files=2,
                saved_page_asset_files=1,
                test_report_asset_files=1,
                dynamic_diagnostics=6,
                parse_errors=0,
                profile_counts={"jest": 2, "react": 3},
                no_execution=True,
            )
        )

        self.assertIn("js_files", table)
        self.assertIn("components", table)
        self.assertIn("test_cases", table)
        self.assertIn("source_map_references", table)
        self.assertIn("frontend_asset_files", table)
        self.assertIn("profile_counts", table)
        self.assertIn("react=3", table)
        self.assertIn("no_execution", table)

    def test_format_js_framework_summary_table_uses_framework_columns(self):
        table = format_js_framework_summary_table(
            JSFrameworkSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                framework_observations=42,
                framework_profiles={
                    "node": 5,
                    "express": 8,
                    "nest": 6,
                    "next": 7,
                    "jest": 9,
                    "jquery": 7,
                    "generic_js": 4,
                },
                node={
                    "entrypoints": 2,
                    "requires": 4,
                    "exports": 3,
                    "env_references": 2,
                },
                express={
                    "apps": 1,
                    "routers": 1,
                    "routes": 6,
                    "middleware": 3,
                    "error_handlers": 1,
                    "dynamic_routes": 1,
                },
                nest={
                    "modules": 1,
                    "controllers": 2,
                    "providers": 3,
                    "routes": 5,
                    "decorators": 12,
                },
                next={
                    "pages": 3,
                    "api_routes": 1,
                    "app_routes": 2,
                    "components": 2,
                    "route_handlers": 1,
                },
                jest={
                    "suites": 2,
                    "tests": 4,
                    "expectations": 6,
                    "mocks": 2,
                },
                jquery={
                    "selectors": 4,
                    "events": 3,
                    "ajax_references": 2,
                    "plugin_references": 1,
                },
                generic_js={
                    "canonical_routes": 6,
                    "canonical_test_suites": 2,
                    "canonical_test_cases": 4,
                    "canonical_components": 2,
                },
                diagnostics={
                    "framework_observation_limit": 1,
                    "framework_selector_limit": 1,
                },
                safety={
                    "no_execution": True,
                    "no_fetch": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            )
        )

        self.assertIn("framework_observations", table)
        self.assertIn("node", table)
        self.assertIn("entrypoints=2", table)
        self.assertIn("express", table)
        self.assertIn("dynamic_routes=1", table)
        self.assertIn("jquery", table)
        self.assertIn("ajax_references=2", table)
        self.assertIn("diagnostics", table)
        self.assertIn("no_new_canonical_namespaces=true", table)

    def test_format_openapi_summary_table_uses_contract_columns(self):
        table = format_openapi_summary_table(
            OpenAPISummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                openapi_observations=64,
                openapi_documents=3,
                spec_families={"openapi3": 2, "swagger2": 1},
                openapi={
                    "info": 3,
                    "servers": 2,
                    "paths": 12,
                    "operations": 24,
                    "parameters": 18,
                    "request_bodies": 6,
                    "responses": 40,
                    "schemas": 15,
                    "components": 20,
                    "security_schemes": 2,
                    "tags": 5,
                    "examples": 4,
                },
                methods={
                    "GET": 10,
                    "POST": 5,
                    "PUT": 2,
                    "PATCH": 1,
                    "DELETE": 2,
                    "OPTIONS": 1,
                    "HEAD": 1,
                    "TRACE": 0,
                },
                references={
                    "internal_refs": 12,
                    "local_file_refs": 2,
                    "remote_refs_not_fetched": 3,
                    "external_docs_not_fetched": 1,
                    "refs_not_fetched": 4,
                },
                redactions={
                    "credentialed_urls": 1,
                    "openapi_ref_summaries": 2,
                    "text_summaries": 3,
                    "example_summaries": 4,
                    "secret_prone_fields": 5,
                },
                diagnostics={
                    "parse_errors": 1,
                    "unsupported_specs": 1,
                    "limit_overflows": 2,
                    "local_ref_errors": 1,
                    "malformed_specs": 1,
                },
                generic_config={
                    "config_documents": 3,
                    "config_paths": 120,
                    "config_references": 18,
                    "config_parse_errors": 1,
                },
                safety={
                    "no_fetch": True,
                    "no_api_calls": True,
                    "no_tool_execution": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            )
        )

        self.assertIn("openapi_documents", table)
        self.assertIn("spec_families", table)
        self.assertIn("openapi3=2", table)
        self.assertIn("operations=24", table)
        self.assertIn("GET=10", table)
        self.assertIn("remote_refs_not_fetched=3", table)
        self.assertIn("secret_prone_fields=5", table)
        self.assertIn("config_paths=120", table)
        self.assertIn("no_fetch=true", table)

    def test_format_terraform_summary_table_uses_hcl_columns(self):
        table = format_terraform_summary_table(
            TerraformSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                terraform_observations=120,
                terraform_files=8,
                file_families={
                    "tf": 5,
                    "tfvars": 1,
                    "terraform.tfvars": 1,
                    "auto.tfvars": 1,
                },
                terraform={
                    "blocks": 35,
                    "providers": 2,
                    "required_providers": 2,
                    "required_versions": 1,
                    "backends": 1,
                    "resources": 12,
                    "data_sources": 2,
                    "modules": 3,
                    "variables": 10,
                    "outputs": 4,
                    "locals": 5,
                    "moved": 1,
                    "imports": 1,
                    "checks": 1,
                    "removed": 1,
                },
                references={
                    "total": 20,
                    "provider_sources": 2,
                    "version_constraints": 3,
                    "module_sources": 3,
                    "local_module_refs": 1,
                    "remote_refs_not_fetched": 2,
                    "depends_on": 4,
                    "provider_aliases": 1,
                    "repo_escape_diagnostics": 1,
                },
                tfvars={
                    "files": 3,
                    "variables": 8,
                    "literal_values_exposed": False,
                },
                redactions={
                    "tfvars_values": 8,
                    "secret_like_fields": 3,
                    "credentialed_urls": 1,
                    "import_ids": 1,
                    "backend_values": 1,
                },
                diagnostics={
                    "parse_errors": 1,
                    "limit_overflows": 1,
                    "malformed_hcl": 1,
                },
                generic_config={
                    "config_documents": 0,
                    "config_paths": 0,
                    "config_references": 0,
                    "file_nodes": 8,
                },
                safety={
                    "no_execution": True,
                    "no_fetch": True,
                    "no_terraform_cli": True,
                    "no_provider_download": True,
                    "no_module_download": True,
                    "no_state_access": True,
                    "tfvars_redacted": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            )
        )

        self.assertIn("terraform_observations", table)
        self.assertIn("file_families", table)
        self.assertIn("terraform.tfvars=1", table)
        self.assertIn("resources=12", table)
        self.assertIn("remote_refs_not_fetched=2", table)
        self.assertIn("literal_values_exposed=false", table)
        self.assertIn("tfvars_values=8", table)
        self.assertIn("malformed_hcl=1", table)
        self.assertIn("no_terraform_cli=true", table)

    def test_format_python_summary_table_uses_python_columns(self):
        table = format_python_summary_table(
            PythonSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                python_observations=250,
                package_files={"requirements": 3, "pyproject": 1},
                packaging={
                    "requirements": 20,
                    "dependency_groups": 4,
                    "build_systems": 1,
                    "entry_points": 3,
                    "tool_configs": 8,
                },
                tests={
                    "test_files": 12,
                    "unittest_cases": 3,
                    "pytest_tests": 20,
                    "test_functions": 18,
                    "test_methods": 5,
                    "fixtures": 6,
                    "parametrize": 2,
                    "assertions": 80,
                },
                frameworks={
                    "flask_apps": 1,
                    "flask_blueprints": 2,
                    "flask_routes": 8,
                    "fastapi_apps": 1,
                    "fastapi_routers": 2,
                    "fastapi_routes": 10,
                    "fastapi_dependencies": 5,
                    "django_projects": 1,
                    "django_apps": 2,
                    "django_urlpatterns": 12,
                    "django_views": 10,
                    "django_models": 4,
                    "django_setting_references": 8,
                },
                references={
                    "total": 35,
                    "package_refs": 15,
                    "local_file_refs": 4,
                    "direct_urls_not_fetched": 2,
                    "index_urls_not_fetched": 2,
                    "framework_refs": 12,
                },
                redactions={
                    "credentialed_urls": 1,
                    "private_indexes": 1,
                    "secret_like_config": 2,
                    "framework_settings": 1,
                },
                diagnostics={
                    "parse_errors": 2,
                    "limit_overflows": 1,
                    "dynamic_constructs": 3,
                },
                generic_python={
                    "modules": 20,
                    "classes": 30,
                    "functions": 80,
                    "methods": 60,
                    "imports": 40,
                },
                generic_config={
                    "config_documents": 1,
                    "config_paths": 60,
                    "config_references": 5,
                },
                dogfooding={
                    "repo_map_profile_observed": True,
                    "bounded": True,
                    "generated_report_committed": False,
                },
                safety={
                    "no_execution": True,
                    "no_imports": True,
                    "no_test_execution": True,
                    "no_framework_startup": True,
                    "no_fetch": True,
                    "no_package_install": True,
                    "no_openapi_fetch": True,
                    "raw_profile_only": True,
                    "no_new_canonical_namespaces": True,
                },
            )
        )

        self.assertIn("python_observations", table)
        self.assertIn("requirements=3", table)
        self.assertIn("pytest_tests=20", table)
        self.assertIn("fastapi_routes=10", table)
        self.assertIn("direct_urls_not_fetched=2", table)
        self.assertIn("secret_like_config=2", table)
        self.assertIn("modules=20", table)
        self.assertIn("repo_map_profile_observed=true", table)
        self.assertIn("no_imports=true", table)

    def test_format_email_summary_table_uses_privacy_and_readback_columns(self):
        table = format_email_summary_table(
            EmailSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                mailboxes=1,
                messages=10,
                eml_messages=8,
                mbox_messages=2,
                addresses=6,
                address_observations=12,
                address_domains=1,
                mime_parts=22,
                text_plain_parts=9,
                text_html_parts=4,
                attachment_stubs=3,
                inline_attachments=1,
                content_id_parts=1,
                thread_hints=5,
                message_references=4,
                external_url_references=1,
                list_unsubscribe_references=1,
                parse_errors=2,
                malformed_or_oversized_diagnostics=2,
                message_id_present=9,
                message_id_missing_or_invalid=1,
                messages_with_attachments=2,
                messages_with_html=4,
                messages_with_plain=9,
                mailbox_limits=1,
                no_provider_api=True,
                no_mutation=True,
                no_body_text=True,
                no_attachment_content=True,
            )
        )

        self.assertIn("mailboxes", table)
        self.assertIn("messages", table)
        self.assertIn("mbox_messages", table)
        self.assertIn("attachment_stubs", table)
        self.assertIn("list_unsubscribe_references", table)
        self.assertIn("no_provider_api", table)
        self.assertIn("no_attachment_content", table)

    def test_format_bulk_summary_table_uses_manifest_and_safety_columns(self):
        table = format_bulk_summary_table(
            BulkSummaryRecord(
                root_path_summary=".",
                repository_name="fixture",
                bulk_runs=2,
                sources=2,
                source_ids=("email-export", "mixed-corpus"),
                corpus_kinds={"email_export": 1, "mixed_corpus": 1},
                policy_statuses={"allowed_with_limits": 2},
                file_count_included=12,
                file_count_skipped=5,
                total_bytes_included=4096,
                extractor_counts={"eml": 3, "javascript": 1},
                skip_reasons={"archive_deferred": 1, "hidden_excluded": 1},
                diagnostic_counts={"extractor_error": 1},
                redaction_counts={"raw_observations": 2},
                limit_hit_count=1,
                max_files_hit_count=1,
                max_total_bytes_hit_count=0,
                max_file_bytes_hit_count=0,
                max_depth_hit_count=0,
                archive_deferred=1,
                warc_deferred=0,
                email_export_runs=1,
                mixed_corpus_runs=1,
                observations_with_bulk_provenance=42,
                no_provider_api=True,
                no_external_fetch=True,
                no_source_mutation=True,
                no_archive_decompression=True,
            )
        )

        self.assertIn("bulk_runs", table)
        self.assertIn("source_ids", table)
        self.assertIn("mixed_corpus=1", table)
        self.assertIn("archive_deferred=1", table)
        self.assertIn("observations_with_bulk_provenance", table)
        self.assertIn("no_archive_decompression", table)

    def test_format_api_summary_table_uses_manifest_and_safety_columns(self):
        table = format_api_summary_table(
            APISummaryRecord(
                root_path_summary=".",
                repository_name="fixture",
                api_runs=1,
                sources=1,
                source_ids=("fixture-readonly-api",),
                source_types={"api.rest": 1},
                api_source_classes={"api.custom_documented_api": 1},
                provider_names={"Fixture Provider": 1},
                provider_products={"Fixture API": 1},
                policy_statuses={"allowed_with_limits": 1},
                requests=1,
                responses=1,
                endpoints=1,
                endpoint_names=("items",),
                methods={"GET": 1},
                downstream_routes={"config": 1},
                response_types={"application/json": 1},
                response_byte_count=512,
                redacted_responses=1,
                diagnostic_counts={},
                routed_artifacts=1,
                observations_with_api_provenance=7,
                config_documents_from_api=1,
                no_network=True,
                no_mutation=True,
                no_credentials_resolved=True,
                no_scheduler=True,
                no_provider_specific_behavior=True,
            )
        )

        self.assertIn("api_runs", table)
        self.assertIn("source_ids", table)
        self.assertIn("api.rest=1", table)
        self.assertIn("Fixture Provider=1", table)
        self.assertIn("GET=1", table)
        self.assertIn("observations_with_api_provenance", table)
        self.assertIn("no_provider_specific_behavior", table)

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
