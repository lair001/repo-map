import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
    discover_migrations,
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


if __name__ == "__main__":
    unittest.main()
