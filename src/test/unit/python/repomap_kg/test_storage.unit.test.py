import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    build_file_ingest_sql,
    build_file_query_sql,
    default_rdbms_root,
    discover_migrations,
    file_rows_from_observations,
    query_file_records,
    load_file_observations,
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

    def test_build_file_query_sql_quotes_root_path(self):
        sql = build_file_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("ORDER BY files.path", sql)


if __name__ == "__main__":
    unittest.main()
