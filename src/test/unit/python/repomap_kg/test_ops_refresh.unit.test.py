import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.observations import RawObservation
from repomap_kg.ops_config import load_ops_config
from repomap_kg.ops_refresh import (
    OpsRefreshError,
    OpsRefreshGraphResult,
    OpsRefreshGraphStatus,
    build_refresh_status_sql,
    format_refresh_result_table,
    format_refresh_status_table,
    query_refresh_status,
    refresh_enabled_graphs,
    refresh_graph,
    refresh_result_to_jsonable,
    refresh_status_to_jsonable,
)
from repomap_kg.storage import LoadSummary, StorageSchemaError


VALID_REFRESH_CONFIG = """\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{repo_root}"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "{private_root}"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = false
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "watch"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""


class OpsRefreshUnitTests(unittest.TestCase):
    def write_config(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "repomap.local.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def config_for_roots(self, repo_root: Path, private_root: Path | None = None):
        private = private_root or repo_root / "private"
        return load_ops_config(
            self.write_config(
                VALID_REFRESH_CONFIG.format(repo_root=repo_root, private_root=private)
            )
        )

    def sample_observations(self) -> list[RawObservation]:
        return [
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="extracted",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={"language": "markdown", "role": "documentation"},
            )
        ]

    def test_refresh_graph_selects_enabled_graph_and_loads_existing_storage_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with (
                patch(
                    "repomap_kg.ops_refresh.discover_observations",
                    return_value=self.sample_observations(),
                ) as discover,
                patch(
                    "repomap_kg.ops_refresh.load_file_observations",
                    return_value=LoadSummary(repository_id=7, run_id=11, files=1),
                ) as load,
            ):
                result = refresh_graph(config, "repo-map", psql_command="/bin/psql")

        self.assertEqual(result.graph_id, "repo-map")
        self.assertEqual(result.result, "success")
        self.assertEqual(result.run_id, 11)
        self.assertEqual(result.repository_id, 7)
        self.assertEqual(result.observations, 1)
        discover.assert_called_once_with(root.resolve())
        load.assert_called_once()
        self.assertEqual(load.call_args.kwargs["repository_name"], "repo-map")
        self.assertEqual(load.call_args.kwargs["root_path"], str(root.resolve()))
        self.assertEqual(load.call_args.kwargs["psql_command"], "/bin/psql")

    def test_refresh_graph_rejects_disabled_graph_without_reading_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch("pathlib.Path.exists", side_effect=AssertionError("root read")):
                with self.assertRaises(OpsRefreshError) as caught:
                    refresh_graph(config, "codex-vc")

        self.assertIn("disabled", str(caught.exception))

    def test_refresh_graph_reports_missing_root_at_refresh_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "missing"
            config = self.config_for_roots(missing_root)

            with self.assertRaises(OpsRefreshError) as caught:
                refresh_graph(config, "repo-map")

        self.assertIn("does not exist", str(caught.exception))

    def test_refresh_graph_reports_private_warning_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            private_root = Path(tmpdir) / "private"
            root.mkdir()
            private_root.mkdir()
            config = load_ops_config(
                self.write_config(
                    VALID_REFRESH_CONFIG.format(
                        repo_root=root,
                        private_root=private_root,
                    ).replace("enabled = false\nmcp_visible = false", "enabled = true\nmcp_visible = false")
                )
            )

            with (
                patch(
                    "repomap_kg.ops_refresh.discover_observations",
                    return_value=self.sample_observations(),
                ),
                patch(
                    "repomap_kg.ops_refresh.load_file_observations",
                    return_value=LoadSummary(repository_id=8, run_id=12, files=1),
                ),
            ):
                result = refresh_graph(config, "codex-vc")

        codes = [warning["code"] for warning in result.warnings]
        self.assertIn("private-graph-refresh", codes)

    def test_refresh_enabled_filters_disabled_graphs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch("repomap_kg.ops_refresh.refresh_graph") as refresh_one:
                refresh_one.return_value.graph_id = "repo-map"
                refresh_one.return_value.result = "success"
                results = refresh_enabled_graphs(config)

        self.assertEqual([result.graph_id for result in results], ["repo-map"])
        refresh_one.assert_called_once()
        self.assertEqual(refresh_one.call_args.args[1], "repo-map")

    def test_refresh_enabled_reports_missing_enabled_root_without_private_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "missing"
            config = self.config_for_roots(missing_root)

            results = refresh_enabled_graphs(config)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].graph_id, "repo-map")
        self.assertEqual(results[0].result, "failure")
        self.assertIn("does not exist", results[0].error or "")

    def test_refresh_result_json_and_table_are_bounded_and_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with (
                patch(
                    "repomap_kg.ops_refresh.discover_observations",
                    return_value=self.sample_observations(),
                ),
                patch(
                    "repomap_kg.ops_refresh.load_file_observations",
                    return_value=LoadSummary(repository_id=7, run_id=11, files=1),
                ),
            ):
                result = refresh_graph(config, "repo-map")

        payload = refresh_result_to_jsonable(config, [result], command="refresh-graph")
        table = format_refresh_result_table(config, [result], command="refresh-graph")

        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["refreshed_graph_count"], 1)
        self.assertEqual(payload["failed_graph_count"], 0)
        self.assertTrue(payload["safety"]["source_trees_mutated"] is False)
        self.assertTrue(payload["safety"]["destructive_db_actions"] is False)
        self.assertIn("RepoMap ops refresh result", table)
        self.assertIn("repo-map | repo-map | public-dev | success", table)

    def test_refresh_result_json_reports_partial_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            payload = refresh_result_to_jsonable(
                config,
                [
                    OpsRefreshGraphResult(
                        graph_id="repo-map",
                        repository_name="repo-map",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        root_path_display=str(root),
                        root_path_expanded=str(root),
                        result="success",
                    ),
                    OpsRefreshGraphResult(
                        graph_id="codex-vc",
                        repository_name="codex-vc",
                        privacy="private-ops",
                        enabled=True,
                        mcp_visible=False,
                        root_path_display="/private",
                        root_path_expanded="/private",
                        result="failure",
                        error="password=fake-secret",
                    ),
                ],
                command="refresh-enabled",
            )

        self.assertEqual(payload["result"], "partial")
        self.assertEqual(payload["failed_graph_count"], 1)
        rendered = json.dumps(payload, sort_keys=True)
        self.assertIn("[REDACTED]", rendered)
        self.assertNotIn("fake-secret", rendered)

    def test_refresh_status_json_shape_does_not_read_roots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)
            statuses = {
                "repo-map": OpsRefreshGraphStatus(
                    graph_id="repo-map",
                    repository_name="repo-map",
                    privacy="public-dev",
                    enabled=True,
                    mcp_visible=True,
                    refresh_policy="manual",
                    root_path_display=str(root),
                    root_path_expanded=str(root),
                    db_checked=True,
                    repository_exists=True,
                    latest_run_id=11,
                    latest_run_status="complete",
                    raw_observations=3,
                    canonical_nodes=2,
                    canonical_edges=1,
                )
            }

            with patch("pathlib.Path.exists", side_effect=AssertionError("root read")):
                payload = refresh_status_to_jsonable(config, statuses)
                table = format_refresh_status_table(config, statuses)

        self.assertTrue(payload["db_checked"])
        self.assertFalse(payload["graphs"][0]["root_path_checked"])
        self.assertEqual(payload["graphs"][0]["latest_run_id"], 11)
        self.assertIn("RepoMap ops refresh status", table)
        self.assertIn("repo-map | repo-map | public-dev | complete", table)

    def test_refresh_status_json_adds_default_rows_for_missing_statuses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            payload = refresh_status_to_jsonable(config, {})

        self.assertFalse(payload["db_checked"])
        self.assertEqual(payload["graphs"][0]["latest_run_status"], None)
        self.assertFalse(payload["graphs"][0]["root_path_checked"])

    def test_refresh_status_sql_is_read_only(self):
        sql = build_refresh_status_sql([("repo-map", "repo-map")])

        self.assertIn("SELECT json_build_object", sql)
        self.assertIn("'repo-map'", sql)
        for destructive in ("DROP", "CREATE", "DELETE", "INSERT", "UPDATE", "TRUNCATE"):
            self.assertNotIn(destructive, sql.upper())

    def test_query_refresh_status_parses_storage_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch("repomap_kg.ops_refresh.run_psql") as run_psql:
                run_psql.side_effect = [
                    type("Result", (), {"stdout": '{"connected": true, "schema_available": true, "required_tables": {"repositories": true, "runs": true, "raw_observations": true, "canonical_nodes": true, "canonical_edges": true}}\n'})(),
                    type("Result", (), {"stdout": '{"graphs": [{"graph_id": "repo-map", "repository_name": "repo-map", "repository_exists": true, "latest_run_id": 11, "latest_run_status": "complete", "latest_run_started_at": "2026-07-02T00:00:00Z", "latest_run_finished_at": "2026-07-02T00:00:01Z", "raw_observations": 3, "canonical_nodes": 2, "canonical_edges": 1}]}\n'})(),
                ]
                statuses = query_refresh_status(config, psql_command="/bin/psql")

        self.assertTrue(statuses["repo-map"].db_checked)
        self.assertTrue(statuses["repo-map"].repository_exists)
        self.assertEqual(statuses["repo-map"].latest_run_id, 11)
        self.assertEqual(statuses["repo-map"].raw_observations, 3)
        self.assertEqual(run_psql.call_count, 2)

    def test_query_refresh_status_reports_schema_errors_without_root_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with (
                patch(
                    "repomap_kg.ops_refresh.run_psql",
                    side_effect=StorageSchemaError("password=fake-secret"),
                ),
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
                statuses = query_refresh_status(config, psql_command="/bin/psql")

        payload = json.dumps(statuses["repo-map"].to_jsonable(), sort_keys=True)
        self.assertTrue(statuses["repo-map"].db_checked)
        self.assertIn("[REDACTED]", payload)
        self.assertNotIn("fake-secret", payload)

    def test_refresh_status_redacts_error_payloads(self):
        status = OpsRefreshGraphStatus(
            graph_id="repo-map",
            repository_name="repo-map",
            privacy="public-dev",
            enabled=True,
            mcp_visible=True,
            refresh_policy="manual",
            root_path_display="/repo",
            root_path_expanded="/repo",
            db_checked=True,
            error="password=mcp-ops3-fake-password",
        )

        payload = json.dumps(status.to_jsonable(), sort_keys=True)

        self.assertIn("[REDACTED]", payload)
        self.assertNotIn("mcp-ops3-fake-password", payload)
