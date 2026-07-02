import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.ops_config import (
    OpsConfigError,
    OpsGraphStorageStatus,
    build_graph_storage_status_sql,
    check_ops_graph_storage_status,
    check_ops_postgres_status,
    format_ops_graph_registry_table,
    format_ops_config_status_table,
    load_ops_config,
    ops_graph_registry_status_to_jsonable,
    ops_config_status_to_jsonable,
)


VALID_CONFIG = """\
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
root_path = "/placeholder/repo-map"
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

[[sources.feed]]
id = "example-feed"
graph_id = "repo-map"
url = "https://example.invalid/feed.xml"
enabled = false

[[sources.github]]
id = "example-github"
graph_id = "repo-map"
owner = "example"
repo = "repo"
mode = "public_readonly"
enabled = false

[[sources.api]]
id = "example-api"
graph_id = "repo-map"
source_class = "api.rest"
enabled = false
"""


class OpsConfigUnitTests(unittest.TestCase):
    def write_config(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "repomap.local.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_valid_minimal_unified_toml_config_parses(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        self.assertEqual(config.schema_version, 1)
        self.assertEqual(config.service.mode, "local")
        self.assertEqual(config.postgres.host, "127.0.0.1")
        self.assertEqual(config.postgres.port, 5432)
        self.assertEqual(config.postgres.password_env, "REPOMAP_PG_PASSWORD")
        self.assertEqual([graph.id for graph in config.graphs], ["repo-map"])
        self.assertEqual(config.server_memory.mode, "read_only")
        self.assertEqual(len(config.sources.feed), 1)
        self.assertEqual(len(config.sources.github), 1)
        self.assertEqual(len(config.sources.api), 1)
        self.assertEqual(config.diagnostics, ())

    def test_committed_example_config_parses(self):
        config = load_ops_config(
            Path("examples") / "repomap.local.example.toml"
        )

        self.assertEqual(config.schema_version, 1)
        self.assertEqual(
            [graph.id for graph in config.graphs],
            ["repo-map", "codex-vc", "codex-memories", "flakes"],
        )
        self.assertFalse(config.graphs[1].enabled)
        payload = json.dumps(ops_config_status_to_jsonable(config), sort_keys=True)
        self.assertNotIn("/Users/", payload)
        self.assertNotIn("admin/admin", payload)

    def test_missing_schema_version_is_diagnostic_error(self):
        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(self.write_config(VALID_CONFIG.replace("schema_version = 1\n", "")))

        self.assertIn("schema_version is required", str(caught.exception))
        self.assertEqual(caught.exception.diagnostics[0].code, "missing-schema-version")

    def test_unsupported_schema_version_is_diagnostic_error(self):
        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(self.write_config(VALID_CONFIG.replace("schema_version = 1", "schema_version = 2")))

        self.assertIn("unsupported schema_version", str(caught.exception))
        self.assertEqual(caught.exception.diagnostics[0].code, "unsupported-schema-version")

    def test_unknown_sections_and_fields_are_warnings(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG
                + "\n[experimental]\nsecret_token = \"mcp-ops1-fake-token\"\n"
                + "\n[service.extra]\nignored = true\n"
            )
        )

        codes = [diagnostic.code for diagnostic in config.diagnostics]
        self.assertIn("unknown-top-level-section", codes)
        self.assertIn("unknown-service-field", codes)
        payload = json.dumps(ops_config_status_to_jsonable(config), sort_keys=True)
        self.assertNotIn("mcp-ops1-fake-token", payload)

    def test_service_section_validates_supported_values(self):
        for old, new, code in (
            ("mode = \"local\"", "mode = \"cloud\"", "unsupported-service-mode"),
            (
                "mcp_transport = \"stdio\"",
                "mcp_transport = \"tunnel\"",
                "unsupported-mcp-transport",
            ),
            ("log_level = \"info\"", "log_level = \"trace\"", "unsupported-log-level"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(OpsConfigError) as caught:
                    load_ops_config(self.write_config(VALID_CONFIG.replace(old, new)))
                self.assertEqual(caught.exception.diagnostics[0].code, code)

    def test_postgres_section_validates_and_redacts_literal_password(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG.replace(
                    'password_env = "REPOMAP_PG_PASSWORD"',
                    'password = "mcp-ops1-fake-password"',
                )
            )
        )

        codes = [diagnostic.code for diagnostic in config.diagnostics]
        self.assertIn("literal-postgres-password", codes)
        payload = ops_config_status_to_jsonable(config)
        self.assertEqual(payload["postgres"]["password"], "[REDACTED]")
        self.assertNotIn("mcp-ops1-fake-password", json.dumps(payload))

    def test_graph_registry_parsing_and_private_enable_warning(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG
                + """

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = true
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "manual"
"""
            )
        )

        self.assertEqual(config.graphs[1].root_path, "~/.codex/codex-vc")
        self.assertTrue(config.graphs[1].root_path_expanded.endswith(".codex/codex-vc"))
        self.assertIn(
            "private-graph-enabled",
            [diagnostic.code for diagnostic in config.diagnostics],
        )

    def test_graph_id_validation_rejects_non_slug_values(self):
        for graph_id in ("RepoMap", "repo map", "repo/map", "../repo-map"):
            with self.subTest(graph_id=graph_id):
                with self.assertRaises(OpsConfigError) as caught:
                    load_ops_config(
                        self.write_config(
                            VALID_CONFIG.replace('id = "repo-map"', f'id = "{graph_id}"', 1)
                        )
                    )
                self.assertEqual(caught.exception.diagnostics[0].code, "invalid-graph-id")

    def test_duplicate_graph_id_is_validation_error(self):
        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(
                self.write_config(
                    VALID_CONFIG
                    + """

[[graphs]]
id = "repo-map"
name = "Duplicate RepoMap"
root_path = "/placeholder/other"
repository_name = "repo-map-copy"
privacy = "public-dev"
enabled = false
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
"""
                )
            )

        self.assertEqual(caught.exception.diagnostics[0].code, "duplicate-graph-id")

    def test_graph_visibility_warnings_are_reported(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG.replace("enabled = true\nmcp_visible = true", "enabled = false\nmcp_visible = true")
                + """

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = false
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "watch"
"""
            )
        )

        codes = [diagnostic.code for diagnostic in config.diagnostics]
        self.assertIn("mcp-visible-disabled-graph", codes)
        self.assertIn("private-graph-mcp-visible", codes)
        self.assertIn("refresh-policy-deferred", codes)

    def test_graph_privacy_and_refresh_policy_validation(self):
        for old, new, code in (
            ("privacy = \"public-dev\"", "privacy = \"secret-cloud\"", "unsupported-graph-privacy"),
            ("refresh_policy = \"manual\"", "refresh_policy = \"wipe\"", "unsupported-refresh-policy"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(OpsConfigError) as caught:
                    load_ops_config(self.write_config(VALID_CONFIG.replace(old, new, 1)))
                self.assertEqual(caught.exception.diagnostics[0].code, code)

    def test_server_memory_section_is_shape_only_and_does_not_read_path(self):
        config_path = self.write_config(VALID_CONFIG)

        with patch("pathlib.Path.exists", side_effect=AssertionError("private read")):
            config = load_ops_config(config_path)

        self.assertEqual(config.server_memory.path, "~/.codex/codex-vc/mcp/server-memory")
        self.assertFalse(config.server_memory.enabled)

    def test_status_json_defaults_to_no_db_check_and_safety_markers(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))
        payload = ops_config_status_to_jsonable(config)

        self.assertTrue(payload["valid"])
        self.assertFalse(payload["postgres_status"]["db_checked"])
        self.assertIsNone(payload["postgres_status"]["schema_available"])
        self.assertTrue(payload["safety"]["local_only"])
        self.assertTrue(payload["safety"]["no_public_tunnel"])
        self.assertTrue(payload["safety"]["no_destructive_operations"])
        self.assertTrue(payload["compatibility"]["legacy_json_mcp_config_supported"])
        self.assertTrue(payload["compatibility"]["legacy_source_toml_supported"])

    def test_graph_registry_status_json_defaults_to_no_db_check(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))
        payload = ops_graph_registry_status_to_jsonable(config)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["graph_count"], 1)
        self.assertEqual(payload["enabled_graph_count"], 1)
        self.assertEqual(payload["mcp_visible_graph_count"], 1)
        self.assertEqual(payload["private_graph_count"], 0)
        self.assertFalse(payload["db_checked"])
        self.assertTrue(payload["security"]["private_roots_read"] is False)
        self.assertTrue(payload["security"]["destructive_db_actions"] is False)
        graph = payload["graphs"][0]
        self.assertEqual(graph["id"], "repo-map")
        self.assertEqual(graph["repository_name"], "repo-map")
        self.assertEqual(graph["refresh_policy_status"], "implemented")
        self.assertEqual(graph["root_path_display"], "/placeholder/repo-map")
        self.assertFalse(graph["root_path_checked"])
        self.assertIsNone(graph["storage_status"])

    def test_graph_registry_status_json_can_include_db_status(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))
        storage_status = {
            "repo-map": OpsGraphStorageStatus(
                db_checked=True,
                repository_name="repo-map",
                schema_available=True,
                repository_exists=True,
                raw_observations=3,
                canonical_nodes=2,
                canonical_edges=1,
            )
        }

        payload = ops_graph_registry_status_to_jsonable(
            config, graph_storage_status=storage_status
        )

        graph_status = payload["graphs"][0]["storage_status"]
        self.assertTrue(payload["db_checked"])
        self.assertTrue(graph_status["db_checked"])
        self.assertTrue(graph_status["repository_exists"])
        self.assertEqual(graph_status["raw_observations"], 3)
        self.assertEqual(graph_status["canonical_nodes"], 2)
        self.assertEqual(graph_status["canonical_edges"], 1)

    def test_graph_registry_table_summarizes_graphs(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        table = format_ops_graph_registry_table(config)

        self.assertIn("RepoMap ops graph registry", table)
        self.assertIn("id | repository | privacy | enabled | mcp_visible | refresh | db | warnings", table)
        self.assertIn("repo-map | repo-map | public-dev | true | true | manual/implemented | unchecked | 0", table)
        self.assertIn("security: private_roots_read=false", table)

    def test_status_table_redacts_and_summarizes_counts(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG.replace(
                    'password_env = "REPOMAP_PG_PASSWORD"',
                    'password = "mcp-ops1-fake-password"',
                )
            )
        )

        table = format_ops_config_status_table(config)

        self.assertIn("RepoMap ops config status", table)
        self.assertIn("graphs: total=1 enabled=1 private_enabled=0", table)
        self.assertIn("db_checked=false", table)
        self.assertIn("[REDACTED]", table)
        self.assertNotIn("mcp-ops1-fake-password", table)

    def test_check_db_status_uses_read_only_schema_probe(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        with patch("repomap_kg.ops_config.run_psql") as run_psql:
            run_psql.return_value.stdout = (
                '{"connected": true, "schema_available": true, '
                '"required_tables": {"repositories": true}}\n'
            )
            db_status = check_ops_postgres_status(config, psql_command="/bin/psql")

        self.assertTrue(db_status.connected)
        self.assertTrue(db_status.schema_available)
        command = run_psql.call_args.args[0]
        self.assertEqual(command[:2], ["/bin/psql", "-h"])
        self.assertIn("-qAt", command)
        self.assertIn("to_regclass", run_psql.call_args.kwargs["input_text"])
        self.assertNotIn("DROP", run_psql.call_args.kwargs["input_text"].upper())
        self.assertNotIn("CREATE", run_psql.call_args.kwargs["input_text"].upper())

    def test_graph_storage_status_sql_is_read_only(self):
        sql = build_graph_storage_status_sql(["repo-map", "codex-vc"])

        self.assertIn("SELECT json_build_object", sql)
        self.assertIn("'repo-map'", sql)
        self.assertIn("'codex-vc'", sql)
        for destructive in ("DROP", "CREATE", "DELETE", "INSERT", "UPDATE", "TRUNCATE"):
            self.assertNotIn(destructive, sql.upper())

    def test_check_graph_storage_status_uses_read_only_queries(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        with patch("repomap_kg.ops_config.run_psql") as run_psql:
            run_psql.side_effect = [
                type("Result", (), {"stdout": '{"connected": true, "schema_available": true, "required_tables": {"repositories": true, "raw_observations": true, "canonical_nodes": true, "canonical_edges": true}}\n'})(),
                type("Result", (), {"stdout": '{"graphs": [{"repository_name": "repo-map", "repository_exists": true, "raw_observations": 4, "canonical_nodes": 3, "canonical_edges": 2}]}\n'})(),
            ]
            status = check_ops_graph_storage_status(config, psql_command="/bin/psql")

        self.assertTrue(status["repo-map"].db_checked)
        self.assertTrue(status["repo-map"].repository_exists)
        self.assertEqual(status["repo-map"].raw_observations, 4)
        self.assertEqual(status["repo-map"].canonical_nodes, 3)
        self.assertEqual(status["repo-map"].canonical_edges, 2)
        self.assertEqual(run_psql.call_count, 2)
        sql = run_psql.call_args_list[1].kwargs["input_text"]
        self.assertNotIn("DROP", sql.upper())
