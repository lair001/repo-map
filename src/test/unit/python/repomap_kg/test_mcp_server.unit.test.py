import json
from io import StringIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    JSFrameworkSummaryRecord,
    IngestedSourceRecord,
    OpenAPISummaryRecord,
    PythonSummaryRecord,
    SourceFeedItemRecord,
    SourceReferenceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
    StorageSummaryRecord,
    StorageSchemaError,
    TerraformSummaryRecord,
    identity_metadata_hash,
)


class McpServerUnitTests(unittest.TestCase):
    def write_mcp_config(self, payload):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "config.json"
        config_path.write_text(json.dumps(payload))
        return config_path

    def write_ops_config(self, body: str):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "repomap.local.toml"
        config_path.write_text(body, encoding="utf-8")
        return config_path

    def visible_ops_config(self) -> str:
        return """
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "repo_map"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/tmp/fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "private-visible"
name = "Private Visible"
root_path = "~/private-visible"
repository_name = "private-visible"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private"
refresh_policy = "manual"

[[graphs]]
id = "disabled"
name = "Disabled"
root_path = "~/disabled"
repository_name = "disabled"
privacy = "private-memory"
enabled = false
mcp_visible = true
extractor_profile = "private"
refresh_policy = "manual"

[[graphs]]
id = "hidden"
name = "Hidden"
root_path = "~/hidden"
repository_name = "hidden"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""

    def test_load_mcp_config_reads_environment_override(self):
        from repomap_kg.mcp_server import load_mcp_config

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                        "pg_host": "/tmp/pg",
                        "pg_port": "55432",
                        "pg_user": "repo_map",
                    },
                    "codex-vc": {
                        "root_path": "/Users/slair/.codex/codex-vc",
                        "pg_database": "repomap_codex_vc",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            config = load_mcp_config()

        self.assertEqual(config.default_project, "repo-map")
        self.assertFalse(config.allow_project_overrides)
        self.assertEqual(
            config.projects["repo-map"].root_path,
            "/Users/slair/projs/repo-map",
        )
        self.assertEqual(config.projects["repo-map"].pg_database, "repomap_repo_map")
        self.assertEqual(config.projects["repo-map"].pg_host, "/tmp/pg")
        self.assertEqual(config.projects["repo-map"].pg_port, "55432")
        self.assertEqual(config.projects["repo-map"].pg_user, "repo_map")

    def test_repomap_projects_lists_configured_projects(self):
        from repomap_kg.mcp_server import repomap_projects

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                    "codex-vc": {
                        "root_path": "/Users/slair/.codex/codex-vc",
                        "pg_database": "repomap_codex_vc",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            payload = repomap_projects()

        self.assertEqual(payload["default_project"], "repo-map")
        self.assertEqual(
            [(project["name"], project["default"]) for project in payload["projects"]],
            [("codex-vc", False), ("repo-map", True)],
        )
        self.assertEqual(
            payload["projects"][1]["root_path"],
            "/Users/slair/projs/repo-map",
        )
        self.assertEqual(
            payload["projects"][1]["pg_database"],
            "repomap_repo_map",
        )

    def test_ops_mcp_list_graphs_exposes_only_enabled_visible_graphs(self):
        from repomap_kg.mcp_server import repomap_list_graphs

        config_path = self.write_ops_config(self.visible_ops_config())

        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            payload = repomap_list_graphs()

        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["graph_count"], 2)
        self.assertEqual(payload["hidden_graph_count"], 2)
        self.assertEqual(
            [graph["graph_id"] for graph in payload["graphs"]],
            ["repo-map", "private-visible"],
        )
        self.assertEqual(payload["graphs"][0]["privacy"], "public-dev")
        self.assertFalse(payload["graphs"][0]["private"])
        self.assertTrue(payload["graphs"][1]["private"])
        self.assertTrue(payload["graphs"][1]["warnings"])
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("~/.codex/codex-vc/mcp/server-memory", serialized)

    def test_ops_mcp_graph_selection_rejects_disabled_or_hidden_graphs(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_project_summary

        config_path = self.write_ops_config(self.visible_ops_config())

        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            with patch("repomap_kg.mcp_ops.query_storage_summary") as query:
                with self.assertRaisesRegex(RepoMapMcpError, "not enabled"):
                    repomap_project_summary(graph_id="disabled")
                with self.assertRaisesRegex(RepoMapMcpError, "not MCP-visible"):
                    repomap_project_summary(graph_id="hidden")

        query.assert_not_called()

    def test_ops_mcp_project_summary_uses_unified_toml_storage_profile(self):
        from repomap_kg.mcp_server import repomap_project_summary

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict(
            "os.environ",
            {
                "REPOMAP_OPS_CONFIG": str(config_path),
                "REPOMAP_PSQL_COMMAND": "/usr/local/bin/psql",
            },
        ):
            with patch(
                "repomap_kg.mcp_ops.query_storage_summary",
                return_value=StorageSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_id=10,
                    repository_name="fixture",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    nodes=5,
                    edges=7,
                    evidence=11,
                ),
            ) as query:
                payload = repomap_project_summary(graph_id="repo-map")

        self.assertEqual(payload["graph"]["graph_id"], "repo-map")
        self.assertEqual(payload["graph"]["repository_name"], "fixture")
        self.assertEqual(payload["summary"]["counts"]["nodes"], 5)
        self.assertTrue(payload["safety"]["read_only"])
        self.assertEqual(
            query.call_args.args[0],
            ["-h", "127.0.0.1", "-p", "5432", "-U", "repo_map", "-d", "repomap"],
        )
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["psql_command"], "/usr/local/bin/psql")

    def test_ops_mcp_searches_are_bounded_and_redacted(self):
        from repomap_kg.mcp_server import (
            repomap_search_files,
            repomap_search_nodes,
            repomap_search_observations,
        )

        config_path = self.write_ops_config(self.visible_ops_config())
        node_payload = {
            "results": [
                {
                    "canonical_key": "python.module:pkg.app",
                    "kind": "python.module",
                    "display_name": "pkg.app",
                    "metadata": {"token": "mcp-ops4-fake-token"},
                }
            ],
            "total": 1,
        }
        observation_payload = {
            "results": [
                {
                    "ordinal": 1,
                    "kind": "python.import",
                    "path": "pkg/app.py",
                    "source_id": "pkg/app.py#python-import:1",
                    "metadata": {"secret": "mcp-ops4-fake-secret"},
                    "payload": {"metadata": {"secret": "mcp-ops4-fake-secret"}},
                }
            ],
            "total": 1,
        }
        files_payload = {
            "results": [{"path": "pkg/app.py", "language": "python"}],
            "total": 1,
        }

        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_ops.query_mcp_search",
                side_effect=[node_payload, observation_payload, files_payload],
            ) as query:
                nodes = repomap_search_nodes(
                    graph_id="repo-map",
                    query="pkg",
                    limit=500,
                    offset=0,
                )
                observations = repomap_search_observations(
                    graph_id="repo-map",
                    query="python.import",
                    include_raw=True,
                )
                files = repomap_search_files(graph_id="repo-map", query="app")

        self.assertEqual(nodes["limit"], 100)
        self.assertTrue(nodes["has_more"] is False)
        self.assertEqual(nodes["results"][0]["canonical_key"], "python.module:pkg.app")
        self.assertNotIn("mcp-ops4-fake-token", json.dumps(nodes, sort_keys=True))
        self.assertNotIn("mcp-ops4-fake-secret", json.dumps(observations, sort_keys=True))
        self.assertEqual(files["results"][0]["path"], "pkg/app.py")
        self.assertEqual(
            [call.kwargs["target"] for call in query.call_args_list],
            ["nodes", "observations", "files"],
        )
        self.assertTrue(all(call.kwargs["limit"] <= 100 for call in query.call_args_list))

    def test_ops_mcp_summary_wrappers_include_graph_context(self):
        from repomap_kg.mcp_server import (
            repomap_js_framework_summary,
            repomap_openapi_summary,
            repomap_python_summary,
            repomap_terraform_summary,
        )

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_ops.query_python_summary",
                return_value=PythonSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    python_observations=3,
                    package_files={"requirements": 1, "pyproject": 1},
                    packaging={},
                    tests={},
                    frameworks={},
                    references={},
                    redactions={},
                    diagnostics={},
                    generic_python={},
                    generic_config={},
                    dogfooding={},
                    safety={"no_execution": True},
                ),
            ):
                python_payload = repomap_python_summary(graph_id="repo-map")
            with patch(
                "repomap_kg.mcp_ops.query_terraform_summary",
                return_value=TerraformSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    terraform_observations=4,
                    terraform_files=2,
                    file_families={},
                    terraform={},
                    references={},
                    tfvars={"literal_values_exposed": False},
                    redactions={},
                    diagnostics={},
                    generic_config={},
                    safety={"no_execution": True},
                ),
            ):
                terraform_payload = repomap_terraform_summary(graph_id="repo-map")
            with patch(
                "repomap_kg.mcp_ops.query_openapi_summary",
                return_value=OpenAPISummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    openapi_observations=5,
                    openapi_documents=1,
                    spec_families={"openapi3": 1},
                    openapi={},
                    methods={},
                    references={},
                    redactions={},
                    diagnostics={},
                    generic_config={},
                    safety={"no_fetch": True},
                ),
            ):
                openapi_payload = repomap_openapi_summary(graph_id="repo-map")
            with patch(
                "repomap_kg.mcp_ops.query_js_framework_summary",
                return_value=JSFrameworkSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    framework_observations=6,
                    framework_profiles={"node": 1},
                    node={},
                    express={},
                    nest={},
                    next={},
                    jest={},
                    jquery={},
                    generic_js={},
                    diagnostics={},
                    safety={"no_execution": True},
                ),
            ):
                js_payload = repomap_js_framework_summary(graph_id="repo-map")

        self.assertEqual(python_payload["summary"]["python_observations"], 3)
        self.assertEqual(terraform_payload["summary"]["terraform_observations"], 4)
        self.assertEqual(openapi_payload["summary"]["openapi_observations"], 5)
        self.assertEqual(js_payload["summary"]["framework_observations"], 6)
        self.assertEqual(js_payload["graph"]["privacy"], "public-dev")

    def test_ops_mcp_refresh_status_reads_existing_storage_only(self):
        from repomap_kg.mcp_server import repomap_refresh_status
        from repomap_kg.ops_refresh import OpsRefreshGraphStatus

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_ops.query_refresh_status",
                return_value={
                    "repo-map": OpsRefreshGraphStatus(
                        graph_id="repo-map",
                        repository_name="fixture",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        refresh_policy="manual",
                        root_path_display="/tmp/fixture",
                        root_path_expanded="/tmp/fixture",
                        repository_exists=True,
                        latest_run_id=12,
                        latest_run_status="success",
                        raw_observations=9,
                        canonical_nodes=8,
                        canonical_edges=7,
                    ),
                    "disabled": OpsRefreshGraphStatus(
                        graph_id="disabled",
                        repository_name="disabled",
                        privacy="private-memory",
                        enabled=False,
                        mcp_visible=True,
                        refresh_policy="manual",
                        root_path_display="~/disabled",
                        root_path_expanded="/Users/example/disabled",
                        repository_exists=False,
                    ),
                },
            ) as query:
                payload = repomap_refresh_status()

        self.assertEqual(payload["graph_count"], 1)
        self.assertEqual(payload["graphs"][0]["graph_id"], "repo-map")
        self.assertEqual(payload["graphs"][0]["raw_observations"], 9)
        self.assertTrue(payload["safety"]["no_refresh"])
        query.assert_called_once()

    def test_ops_mcp_graph_status_and_neighborhood_use_stored_readback(self):
        from repomap_kg.mcp_server import repomap_graph_status, repomap_neighborhood
        from repomap_kg.ops_refresh import OpsRefreshGraphStatus

        config_path = self.write_ops_config(self.visible_ops_config())
        neighborhood = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:pkg.app",
                graph_key_version=1,
                kind="python.module",
                display_name="pkg.app",
                confidence="extracted",
                conflict=False,
                metadata={"api_key": "mcp-ops4-fake-token"},
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            nodes=(),
            edges=(),
        )
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_ops.query_refresh_status",
                return_value={
                    "repo-map": OpsRefreshGraphStatus(
                        graph_id="repo-map",
                        repository_name="fixture",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        refresh_policy="manual",
                        root_path_display="/tmp/fixture",
                        root_path_expanded="/tmp/fixture",
                        repository_exists=True,
                        raw_observations=4,
                        canonical_nodes=3,
                        canonical_edges=2,
                    )
                },
            ):
                status = repomap_graph_status(graph_id="repo-map")
            with patch(
                "repomap_kg.mcp_ops.query_canonical_neighborhood",
                return_value=neighborhood,
            ) as query:
                payload = repomap_neighborhood(
                    graph_id="repo-map",
                    node="python.module:pkg.app",
                    direction="both",
                    depth=1,
                )

        self.assertEqual(status["storage"]["raw_observations"], 4)
        self.assertEqual(
            payload["result"]["center"]["canonical_key"],
            "python.module:pkg.app",
        )
        self.assertNotIn("mcp-ops4-fake-token", json.dumps(payload, sort_keys=True))
        self.assertEqual(query.call_args.kwargs["node"], "python.module:pkg.app")

    def test_ops_mcp_helper_validation_and_sql_are_bounded(self):
        from repomap_kg.mcp_ops import (
            McpOpsError,
            build_mcp_search_sql,
            like_escape,
            psql_command_from_environment,
            validate_limit,
            validate_offset,
            validate_query,
        )

        self.assertEqual(validate_limit(500), 100)
        self.assertEqual(validate_offset("3"), 3)
        self.assertEqual(validate_query("  pkg  "), "pkg")
        self.assertEqual(like_escape(r"%pkg_app"), r"\%pkg\_app")
        with self.assertRaisesRegex(McpOpsError, "query is required"):
            validate_query("")
        with self.assertRaisesRegex(McpOpsError, "positive integer"):
            validate_limit(0)
        with self.assertRaisesRegex(McpOpsError, "non-negative"):
            validate_offset(-1)
        with patch.dict("os.environ", {"REPOMAP_PSQL_COMMAND": "bad psql"}):
            with self.assertRaisesRegex(McpOpsError, "whitespace"):
                psql_command_from_environment()
        with patch.dict("os.environ", {"REPOMAP_PSQL_COMMAND": "/bin/echo"}):
            with self.assertRaisesRegex(McpOpsError, "psql executable"):
                psql_command_from_environment()

        nodes_sql = build_mcp_search_sql(
            root_path="/tmp/fixture",
            target="nodes",
            query="pkg",
            kind="python.module",
            path=None,
            limit=20,
            offset=0,
            include_raw=False,
        )
        observations_sql = build_mcp_search_sql(
            root_path="/tmp/fixture",
            target="observations",
            query="python.import",
            kind="python.import",
            path="pkg/app.py",
            limit=20,
            offset=2,
            include_raw=True,
        )
        files_sql = build_mcp_search_sql(
            root_path="/tmp/fixture",
            target="files",
            query="README",
            kind=None,
            path="README.md",
            limit=5,
            offset=0,
            include_raw=False,
        )
        self.assertIn("FROM canonical_nodes", nodes_sql)
        self.assertIn("canonical_nodes.kind = 'python.module'", nodes_sql)
        self.assertIn("raw_observations.payload_json AS payload", observations_sql)
        self.assertIn("raw_observations.path = 'pkg/app.py'", observations_sql)
        self.assertIn("FROM files", files_sql)
        with self.assertRaisesRegex(McpOpsError, "search target"):
            build_mcp_search_sql(
                root_path="/tmp/fixture",
                target="edges",
                query="pkg",
                kind=None,
                path=None,
                limit=1,
                offset=0,
                include_raw=False,
            )

    def test_ops_mcp_missing_config_unknown_graph_and_search_parse_are_safe(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_list_graphs
        from repomap_kg.mcp_ops import query_mcp_search

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RepoMapMcpError, "REPOMAP_OPS_CONFIG"):
                repomap_list_graphs()

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            from repomap_kg.mcp_server import repomap_project_summary

            with self.assertRaisesRegex(RepoMapMcpError, "unknown graph_id"):
                repomap_project_summary(graph_id="missing")

        with patch(
            "repomap_kg.mcp_ops.run_psql",
            return_value=SimpleNamespace(stdout='[{"path":"one"},{"path":"two"}]'),
        ) as run:
            payload = query_mcp_search(
                ["-d", "repomap"],
                root_path="/tmp/fixture",
                target="files",
                query="path",
                limit=1,
                offset=5,
                psql_command="/usr/bin/psql",
            )

        self.assertEqual(payload["results"], [{"path": "one"}])
        self.assertEqual(payload["total"], 6)
        self.assertTrue(payload["has_more"])
        self.assertEqual(run.call_args.args[0][0], "/usr/bin/psql")

        with patch(
            "repomap_kg.mcp_ops.run_psql",
            return_value=SimpleNamespace(stdout='{"not":"rows"}'),
        ):
            with self.assertRaises(StorageSchemaError):
                query_mcp_search(
                    ["-d", "repomap"],
                    root_path="/tmp/fixture",
                    target="files",
                    query="path",
                    limit=1,
                    psql_command="psql",
                )

    def test_status_uses_default_project_from_config(self):
        from repomap_kg.mcp_server import repomap_status

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                        "pg_host": "/tmp/pg",
                        "pg_port": "55432",
                        "pg_user": "repo_map",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_server.query_storage_summary",
                return_value=StorageSummaryRecord(
                    root_path="/Users/slair/projs/repo-map",
                    repository_id=10,
                    repository_name="repo-map",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    nodes=5,
                    edges=7,
                    evidence=11,
                ),
            ) as query:
                payload = repomap_status()

        self.assertEqual(payload["project"], "repo-map")
        self.assertEqual(payload["repository_name"], "repo-map")
        self.assertEqual(
            query.call_args.args[0],
            ["-h", "/tmp/pg", "-p", "55432", "-U", "repo_map", "-d", "repomap_repo_map"],
        )
        self.assertEqual(query.call_args.kwargs["root_path"], "/Users/slair/projs/repo-map")

    def test_canonical_nodes_resolves_named_project_config(self):
        from repomap_kg.mcp_server import repomap_canonical_nodes

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )
        record = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli",
            graph_key_version=1,
            kind="python.module",
            display_name="repomap_kg.cli",
            confidence="extracted",
            conflict=False,
            metadata={},
            first_seen_run_id=1,
            last_seen_run_id=2,
        )
        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_server.query_canonical_node_records",
                return_value=(record,),
            ) as query:
                payload = repomap_canonical_nodes(
                    project="repo-map",
                    kind="python.module",
                )

        self.assertEqual(payload[0]["canonical_key"], "python.module:repomap_kg.cli")
        self.assertEqual(query.call_args.args[0], ["-d", "repomap_repo_map"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/Users/slair/projs/repo-map")

    def test_missing_project_and_default_are_rejected_before_query(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_status

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch("repomap_kg.mcp_server.query_storage_summary") as query:
                with self.assertRaisesRegex(RepoMapMcpError, "unknown project"):
                    repomap_status(project="missing")
                with self.assertRaisesRegex(RepoMapMcpError, "root_path is required"):
                    repomap_status()

        query.assert_not_called()

    def test_project_and_explicit_overrides_are_rejected_unless_allowed(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_status

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch("repomap_kg.mcp_server.query_storage_summary") as query:
                with self.assertRaisesRegex(
                    RepoMapMcpError,
                    "project cannot be combined with explicit",
                ):
                    repomap_status(
                        project="repo-map",
                        root_path="/tmp/other",
                    )
                with self.assertRaisesRegex(
                    RepoMapMcpError,
                    "project cannot be combined with explicit",
                ):
                    repomap_status(
                        project="repo-map",
                        pg_database="other",
                    )

        query.assert_not_called()

        allowed_config_path = self.write_mcp_config(
            {
                "allow_project_overrides": True,
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )
        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(allowed_config_path)}):
            with patch(
                "repomap_kg.mcp_server.query_storage_summary",
                return_value=StorageSummaryRecord(
                    root_path="/tmp/other",
                    repository_id=10,
                    repository_name="other",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    nodes=5,
                    edges=7,
                    evidence=11,
                ),
            ) as query:
                payload = repomap_status(
                    project="repo-map",
                    root_path="/tmp/other",
                    pg_database="other_db",
                )

        self.assertEqual(payload["root_path"], "/tmp/other")
        self.assertEqual(query.call_args.args[0], ["-d", "other_db"])

    def test_explicit_mode_wins_over_default_project_for_development(self):
        from repomap_kg.mcp_server import repomap_status

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_server.query_storage_summary",
                return_value=StorageSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_id=10,
                    repository_name="fixture",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    nodes=5,
                    edges=7,
                    evidence=11,
                ),
            ) as query:
                payload = repomap_status(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                )

        self.assertNotIn("project", payload)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_status_requires_explicit_root_path_and_database(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_status

        with self.assertRaisesRegex(RepoMapMcpError, "root_path is required"):
            repomap_status(root_path="", pg_database="postgres")

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RepoMapMcpError, "pg_database is required"):
                repomap_status(root_path="/tmp/fixture")

    def test_status_rejects_non_psql_command_names(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_status

        with self.assertRaisesRegex(
            RepoMapMcpError,
            "psql_command must name a psql executable",
        ):
            repomap_status(
                root_path="/tmp/fixture",
                pg_database="postgres",
                psql_command="/usr/bin/not-psql",
            )

        with self.assertRaisesRegex(
            RepoMapMcpError,
            "psql_command must not contain whitespace",
        ):
            repomap_status(
                root_path="/tmp/fixture",
                pg_database="postgres",
                psql_command="psql --echo-all",
            )

    def test_status_reads_postgres_connection_defaults_from_environment(self):
        from repomap_kg.mcp_server import repomap_status

        with patch.dict(
            "os.environ",
            {
                "REPOMAP_PG_HOST": "/tmp/pg",
                "REPOMAP_PG_PORT": "5433",
                "REPOMAP_PG_USER": "slair",
                "REPOMAP_PG_DATABASE": "repomap",
                "REPOMAP_PSQL_COMMAND": "/opt/postgres/bin/psql",
            },
            clear=False,
        ):
            with patch(
                "repomap_kg.mcp_server.query_storage_summary",
                return_value=StorageSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_id=10,
                    repository_name="fixture",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    nodes=5,
                    edges=7,
                    evidence=11,
                ),
            ) as query:
                payload = repomap_status(root_path="/tmp/fixture")

        self.assertEqual(payload["repository_name"], "fixture")
        self.assertEqual(
            query.call_args.args[0],
            ["-h", "/tmp/pg", "-p", "5433", "-U", "slair", "-d", "repomap"],
        )
        self.assertEqual(
            query.call_args.kwargs["psql_command"],
            "/opt/postgres/bin/psql",
        )

    def test_status_returns_read_only_summary_without_database_ids(self):
        from repomap_kg.mcp_server import repomap_status

        with patch(
            "repomap_kg.mcp_server.query_storage_summary",
            return_value=StorageSummaryRecord(
                root_path="/tmp/fixture",
                repository_id=10,
                repository_name="fixture",
                latest_run_id=22,
                runs=2,
                files=3,
                nodes=5,
                edges=7,
                evidence=11,
            ),
        ) as query:
            payload = repomap_status(
                root_path="/tmp/fixture",
                pg_host="/tmp/pg",
                pg_port="5432",
                pg_user="slair",
                pg_database="postgres",
                psql_command="/usr/bin/psql",
            )

        self.assertEqual(
            query.call_args.args[0],
            ["-h", "/tmp/pg", "-p", "5432", "-U", "slair", "-d", "postgres"],
        )
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["psql_command"], "/usr/bin/psql")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["graph_key_version"], 1)
        self.assertEqual(payload["repository_name"], "fixture")
        self.assertEqual(payload["counts"]["edges"], 7)
        self.assertNotIn("repository_id", payload)
        self.assertNotIn("latest_run_id", payload)

    def test_canonical_nodes_validates_args_and_calls_storage_helper(self):
        from repomap_kg.mcp_server import repomap_canonical_nodes

        record = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli",
            graph_key_version=1,
            kind="python.module",
            display_name="repomap_kg.cli",
            confidence="extracted",
            conflict=False,
            metadata={"path": "src/main/python/repomap_kg/cli.py"},
            first_seen_run_id=1,
            last_seen_run_id=2,
        )
        with patch(
            "repomap_kg.mcp_server.query_canonical_node_records",
            return_value=(record,),
        ) as query:
            payload = repomap_canonical_nodes(
                root_path="/tmp/fixture",
                pg_database="postgres",
                kind="python.module",
                canonical_key="python.module:repomap_kg.cli",
            )

        self.assertEqual(payload[0]["canonical_key"], "python.module:repomap_kg.cli")
        self.assertIn("metadata", payload[0])
        self.assertEqual(query.call_args.kwargs["kind"], "python.module")
        self.assertEqual(
            query.call_args.kwargs["canonical_key"],
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)

    def test_canonical_nodes_rejects_invalid_key_before_query(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_canonical_nodes

        with patch("repomap_kg.mcp_server.query_canonical_node_records") as query:
            with self.assertRaisesRegex(RepoMapMcpError, "invalid canonical key"):
                repomap_canonical_nodes(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    canonical_key="python.module:bad#line",
                )

        query.assert_not_called()

    def test_canonical_nodes_rejects_path_prefix_for_non_file_kind(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_canonical_nodes

        with patch("repomap_kg.mcp_server.query_canonical_node_records") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "path-prefix only applies to file canonical nodes",
            ):
                repomap_canonical_nodes(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    kind="python.module",
                    path_prefix="src/main/python",
                )

        query.assert_not_called()

    def test_canonical_edges_rejects_unsupported_kind_before_query(self):
        from repomap_kg.mcp_server import RepoMapMcpError, repomap_canonical_edges

        with patch("repomap_kg.mcp_server.query_canonical_edge_records") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "unsupported canonical edge kind",
            ):
                repomap_canonical_edges(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    kind="invokes",
                )

        query.assert_not_called()

    def test_canonical_edges_returns_existing_cli_json_shape(self):
        from repomap_kg.mcp_server import repomap_canonical_edges

        hash_text = identity_metadata_hash({})
        record = CanonicalEdgeRecord(
            source_key="python.module:repomap_kg.cli",
            edge_kind="imports",
            target_key="python.module:repomap_kg.storage",
            graph_key_version=1,
            identity_metadata={},
            identity_metadata_hash=hash_text,
            metadata={},
            confidence="extracted",
            conflict=False,
            first_seen_run_id=1,
            last_seen_run_id=2,
        )
        with patch(
            "repomap_kg.mcp_server.query_canonical_edge_records",
            return_value=(record,),
        ) as query:
            payload = repomap_canonical_edges(
                root_path="/tmp/fixture",
                pg_database="postgres",
                kind="imports",
                source_key="python.module:repomap_kg.cli",
                target_key="python.module:repomap_kg.storage",
            )

        self.assertEqual(payload[0]["edge_kind"], "imports")
        self.assertEqual(payload[0]["identity_metadata_hash"], hash_text)
        self.assertEqual(query.call_args.kwargs["source_key"], "python.module:repomap_kg.cli")
        self.assertEqual(query.call_args.kwargs["target_key"], "python.module:repomap_kg.storage")

    def test_explain_canonical_edge_hashes_identity_metadata(self):
        from repomap_kg.mcp_server import repomap_explain_canonical_edge

        metadata = {"scope": "fixture", "order": [2, 1]}
        hash_text = identity_metadata_hash(metadata)
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="python.module:repomap_kg.cli",
                edge_kind="imports",
                target_key="python.module:repomap_kg.storage",
                graph_key_version=1,
                identity_metadata=metadata,
                identity_metadata_hash=hash_text,
                metadata={},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            evidence=(
                CanonicalEdgeEvidenceRecord(
                    evidence_key="evidence:1",
                    link_kind="supports",
                    raw_observation={
                        "run_id": 1,
                        "ordinal": 0,
                        "payload_hash": "0" * 64,
                        "kind": "python.import",
                        "source_id": "src/main/python/repomap_kg/cli.py#import:storage",
                    },
                    path="src/main/python/repomap_kg/cli.py",
                    start_line=20,
                    end_line=20,
                    extractor="repo-python-ast",
                    extractor_version="0.1.0",
                    confidence="extracted",
                    metadata={},
                ),
            ),
        )
        with patch(
            "repomap_kg.mcp_server.query_canonical_edge_explanation",
            return_value=record,
        ) as query:
            payload = repomap_explain_canonical_edge(
                root_path="/tmp/fixture",
                pg_database="postgres",
                source_key="python.module:repomap_kg.cli",
                kind="imports",
                target_key="python.module:repomap_kg.storage",
                identity_metadata=metadata,
            )

        self.assertEqual(payload["edge"]["identity_metadata_hash"], hash_text)
        self.assertEqual(payload["evidence"][0]["path"], "src/main/python/repomap_kg/cli.py")
        self.assertEqual(query.call_args.kwargs["identity_metadata_hash"], hash_text)

    def test_explain_canonical_edge_rejects_non_object_identity_metadata(self):
        from repomap_kg.mcp_server import (
            RepoMapMcpError,
            repomap_explain_canonical_edge,
        )

        with patch("repomap_kg.mcp_server.query_canonical_edge_explanation") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "identity_metadata must be a JSON object",
            ):
                repomap_explain_canonical_edge(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    source_key="python.module:repomap_kg.cli",
                    kind="imports",
                    target_key="python.module:repomap_kg.storage",
                    identity_metadata=[],
                )

        query.assert_not_called()

    def test_canonical_neighborhood_validates_args_and_returns_json_shape(self):
        from repomap_kg.mcp_server import repomap_canonical_neighborhood

        hash_text = identity_metadata_hash({})
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:repomap_kg.cli",
                graph_key_version=1,
                kind="python.module",
                display_name="repomap_kg.cli",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            nodes=(
                CanonicalNodeRecord(
                    canonical_key="python.module:repomap_kg.storage",
                    graph_key_version=1,
                    kind="python.module",
                    display_name="repomap_kg.storage",
                    confidence="extracted",
                    conflict=False,
                    metadata={},
                    first_seen_run_id=1,
                    last_seen_run_id=2,
                ),
            ),
            edges=(
                CanonicalEdgeRecord(
                    source_key="python.module:repomap_kg.cli",
                    edge_kind="imports",
                    target_key="python.module:repomap_kg.storage",
                    graph_key_version=1,
                    identity_metadata={},
                    identity_metadata_hash=hash_text,
                    metadata={},
                    confidence="extracted",
                    conflict=False,
                    first_seen_run_id=1,
                    last_seen_run_id=2,
                ),
            ),
        )
        with patch(
            "repomap_kg.mcp_server.query_canonical_neighborhood",
            return_value=record,
        ) as query:
            payload = repomap_canonical_neighborhood(
                root_path="/tmp/fixture",
                pg_database="postgres",
                node="python.module:repomap_kg.cli",
                direction="out",
            )

        self.assertEqual(payload["center"]["canonical_key"], "python.module:repomap_kg.cli")
        self.assertEqual(payload["nodes"][0]["canonical_key"], "python.module:repomap_kg.storage")
        self.assertEqual(payload["edges"][0]["edge_kind"], "imports")
        self.assertEqual(query.call_args.kwargs["direction"], "out")
        self.assertEqual(query.call_args.kwargs["depth"], 1)

    def test_canonical_neighborhood_rejects_depth_and_direction_before_query(self):
        from repomap_kg.mcp_server import (
            RepoMapMcpError,
            repomap_canonical_neighborhood,
        )

        with patch("repomap_kg.mcp_server.query_canonical_neighborhood") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "canonical-neighborhood only supports depth 1",
            ):
                repomap_canonical_neighborhood(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    node="python.module:repomap_kg.cli",
                    depth=2,
                )

            with self.assertRaisesRegex(
                RepoMapMcpError,
                "direction must be one of both, in, out",
            ):
                repomap_canonical_neighborhood(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    node="python.module:repomap_kg.cli",
                    direction="sideways",
                )

        query.assert_not_called()

    def test_source_feed_mcp_tools_are_read_only_and_project_scoped(self):
        from repomap_kg.mcp_server import (
            repomap_explain_source_feed_item,
            repomap_ingested_sources,
            repomap_source_feed_items,
            repomap_source_references,
            repomap_source_runs,
            repomap_source_summary,
        )

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/Users/slair/projs/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )
        item_key = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
        )
        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.mcp_server.query_ingested_source_records",
                return_value=(
                    IngestedSourceRecord(
                        source_id="example-news-feed",
                        source_type="feed.rss",
                        display_name="Example News Feed",
                        policy_status="allowed_with_limits",
                        latest_source_run_id="20260630T120000Z",
                        latest_artifact_id="abc123",
                        latest_artifact_path=".repomap/source-artifacts/example/rss.xml",
                        latest_acquired_at="2026-06-30T12:00:00Z",
                        feed_observation_count=8,
                        canonical_feed_item_count=2,
                    ),
                ),
            ) as sources_query:
                sources_payload = repomap_ingested_sources(source_type="feed.rss")
            with patch(
                "repomap_kg.mcp_server.query_source_summary",
                return_value=SourceSummaryRecord(
                    source_id="example-news-feed",
                    source_type="feed.rss",
                    display_name="Example News Feed",
                    policy_status="allowed_with_limits",
                    configured_url_summary="https://example.invalid/feed.xml",
                    latest_source_run_id="20260630T120000Z",
                    latest_artifact_id="abc123",
                    latest_artifact_path=".repomap/source-artifacts/example/rss.xml",
                    latest_acquired_at="2026-06-30T12:00:00Z",
                    feed_documents=1,
                    feed_channels=1,
                    feed_items=2,
                    feed_authors=1,
                    feed_categories=2,
                    link_references=2,
                    enclosure_references=1,
                    parse_errors=0,
                    known_limitations=("source metadata is inferred from RSS2 evidence",),
                ),
            ) as summary_query:
                summary_payload = repomap_source_summary(
                    source_id="example-news-feed",
                )
            with patch(
                "repomap_kg.mcp_server.query_source_run_records",
                return_value=(
                    SourceRunRecord(
                        source_run_id="20260630T120000Z",
                        acquired_at="2026-06-30T12:00:00Z",
                        artifact_id="abc123",
                        artifact_path=".repomap/source-artifacts/example/rss.xml",
                        artifact_byte_length=512,
                        artifact_sha256="0" * 64,
                        http_status=200,
                        content_type="application/rss+xml",
                        observation_count=8,
                        status_summary="ok",
                    ),
                ),
            ) as runs_query:
                runs_payload = repomap_source_runs(source_id="example-news-feed")
            with patch(
                "repomap_kg.mcp_server.query_source_feed_item_records",
                return_value=(
                    SourceFeedItemRecord(
                        item_key=item_key,
                        title="Release note",
                        published_at="2026-06-30T12:00:00Z",
                        updated_at=None,
                        identity_source="guid",
                        identity_strength="strong",
                        duplicate_identity=False,
                        link_targets=(),
                        authors=("Example Author",),
                        categories=("release",),
                        source_run_id="20260630T120000Z",
                        artifact_id="abc123",
                        artifact_path=".repomap/source-artifacts/example/rss.xml",
                    ),
                ),
            ) as items_query:
                items_payload = repomap_source_feed_items(
                    source_id="example-news-feed",
                )
            with patch(
                "repomap_kg.mcp_server.query_source_reference_records",
                return_value=(
                    SourceReferenceRecord(
                        source_item_key=item_key,
                        relation="references",
                        target_key="external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",
                        target_display="https://example.invalid/items/1",
                        not_fetched=True,
                        media_type=None,
                        source_run_id="20260630T120000Z",
                        artifact_id="abc123",
                        artifact_path=".repomap/source-artifacts/example/rss.xml",
                    ),
                ),
            ) as references_query:
                references_payload = repomap_source_references(
                    source_id="example-news-feed",
                    target_kind="external.url",
                )
            with patch(
                "repomap_kg.mcp_server.query_source_feed_item_explanation",
                return_value={
                    "item": {"canonical_key": item_key, "kind": "feed.item"},
                    "source": {"source_id": "example-news-feed"},
                    "evidence": [],
                    "references": [],
                    "content_policy": "full feed bodies are not exposed",
                },
            ) as explain_query:
                explanation_payload = repomap_explain_source_feed_item(
                    item_key=item_key,
                )

        self.assertEqual(sources_payload[0]["source_id"], "example-news-feed")
        self.assertEqual(summary_payload["feed_items"], 2)
        self.assertEqual(runs_payload[0]["source_run_id"], "20260630T120000Z")
        self.assertEqual(items_payload[0]["item_key"], item_key)
        self.assertTrue(references_payload[0]["not_fetched"])
        self.assertEqual(explanation_payload["item"]["canonical_key"], item_key)
        self.assertEqual(sources_query.call_args.args[0], ["-d", "repomap_repo_map"])
        self.assertEqual(sources_query.call_args.kwargs["root_path"], "/Users/slair/projs/repo-map")
        self.assertEqual(summary_query.call_args.kwargs["source_id"], "example-news-feed")
        self.assertEqual(runs_query.call_args.kwargs["source_id"], "example-news-feed")
        self.assertEqual(items_query.call_args.kwargs["source_id"], "example-news-feed")
        self.assertEqual(references_query.call_args.kwargs["target_kind"], "external.url")
        self.assertEqual(explain_query.call_args.kwargs["item_key"], item_key)

    def test_source_feed_mcp_tools_reject_arbitrary_url_inputs(self):
        from repomap_kg.mcp_server import RepoMapMcpError, tool_input_schema

        for name in (
            "repomap_ingested_sources",
            "repomap_source_summary",
            "repomap_source_runs",
            "repomap_source_feed_items",
            "repomap_explain_source_feed_item",
            "repomap_source_references",
        ):
            with self.subTest(tool=name):
                schema = tool_input_schema(name)
                self.assertNotIn("url", schema["properties"])
                self.assertNotIn("feed_url", schema["properties"])
                self.assertNotIn("config_path", schema["properties"])

        from repomap_kg.mcp_server import repomap_source_summary

        with self.assertRaisesRegex(RepoMapMcpError, "source_id must not be a URL"):
            repomap_source_summary(
                root_path="/tmp/fixture",
                pg_database="postgres",
                source_id="https://example.invalid/feed.xml",
            )

    def test_mcp_tools_list_contains_only_read_only_tools(self):
        from repomap_kg.mcp_server import tool_definitions

        names = [tool["name"] for tool in tool_definitions()]

        self.assertEqual(
            names,
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
                "repomap_list_graphs",
                "repomap_graph_status",
                "repomap_search_nodes",
                "repomap_search_observations",
                "repomap_search_files",
                "repomap_neighborhood",
                "repomap_project_summary",
                "repomap_python_summary",
                "repomap_terraform_summary",
                "repomap_openapi_summary",
                "repomap_js_framework_summary",
                "repomap_refresh_status",
            ],
        )
        serialized = json.dumps(tool_definitions(), sort_keys=True)
        self.assertNotIn("discover", serialized)
        self.assertNotIn("load-files", serialized)
        self.assertNotIn("ingest-feed", serialized)
        self.assertNotIn("fetch-feed", serialized)
        self.assertNotIn("refresh_graph", serialized)
        self.assertNotIn("refresh-enabled", serialized)
        self.assertNotIn("write", serialized)
        self.assertNotIn("url", serialized)

    def test_mcp_tool_schemas_do_not_expose_psql_command(self):
        from repomap_kg.mcp_server import tool_definitions

        for tool in tool_definitions():
            with self.subTest(tool=tool["name"]):
                self.assertNotIn(
                    "psql_command",
                    tool["inputSchema"]["properties"],
                )

    def test_mcp_read_tools_accept_project_and_do_not_require_root_path(self):
        from repomap_kg.mcp_server import tool_input_schema

        self.assertEqual(tool_input_schema("repomap_status")["required"], [])
        self.assertEqual(tool_input_schema("repomap_canonical_nodes")["required"], [])
        self.assertEqual(tool_input_schema("repomap_canonical_edges")["required"], [])
        self.assertEqual(
            tool_input_schema("repomap_explain_canonical_edge")["required"],
            ["source_key", "kind", "target_key"],
        )
        self.assertEqual(
            tool_input_schema("repomap_canonical_neighborhood")["required"],
            ["node"],
        )
        for name in (
            "repomap_status",
            "repomap_canonical_nodes",
            "repomap_canonical_edges",
            "repomap_explain_canonical_edge",
            "repomap_canonical_neighborhood",
        ):
            with self.subTest(tool=name):
                self.assertIn("project", tool_input_schema(name)["properties"])
                self.assertIn("root_path", tool_input_schema(name)["properties"])

    def test_handle_tool_call_rejects_unknown_tool_and_non_object_args(self):
        from repomap_kg.mcp_server import RepoMapMcpError, handle_tool_call

        with self.assertRaisesRegex(RepoMapMcpError, "unknown RepoMap MCP tool"):
            handle_tool_call("repomap_discover", {})

        with self.assertRaisesRegex(
            RepoMapMcpError,
            "tool arguments must be a JSON object",
        ):
            handle_tool_call("repomap_status", [])

    def test_jsonrpc_tools_call_reports_missing_required_arguments(self):
        from repomap_kg.mcp_server import handle_jsonrpc_message

        response = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "repomap_canonical_neighborhood",
                    "arguments": {"root_path": "/tmp/fixture"},
                },
            }
        )

        self.assertEqual(response["id"], 9)
        self.assertTrue(response["result"]["isError"])
        self.assertIn("missing required argument", response["result"]["content"][0]["text"])
        self.assertIn("node", response["result"]["structuredContent"]["error"])

    def test_jsonrpc_tools_call_reports_unexpected_arguments(self):
        from repomap_kg.mcp_server import handle_jsonrpc_message

        response = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "repomap_status",
                    "arguments": {
                        "root_path": "/tmp/fixture",
                        "pg_database": "postgres",
                        "psql_command": "/tmp/attacker/psql",
                    },
                },
            }
        )

        self.assertEqual(response["id"], 10)
        self.assertTrue(response["result"]["isError"])
        self.assertIn(
            "unexpected argument",
            response["result"]["content"][0]["text"],
        )
        self.assertIn("psql_command", response["result"]["structuredContent"]["error"])

    def test_handle_tool_call_wraps_storage_schema_errors(self):
        from repomap_kg.mcp_server import RepoMapMcpError, handle_tool_call
        from repomap_kg.storage import StorageSchemaError

        with patch(
            "repomap_kg.mcp_server.repomap_status",
            side_effect=StorageSchemaError("bad storage"),
        ):
            with self.assertRaisesRegex(RepoMapMcpError, "bad storage"):
                handle_tool_call("repomap_status", {"root_path": "/tmp/fixture"})

    def test_handle_tool_call_returns_structured_content_and_text_json(self):
        from repomap_kg.mcp_server import handle_tool_call

        with patch(
            "repomap_kg.mcp_server.repomap_canonical_nodes",
            return_value=[{"canonical_key": "python.module:repomap_kg.cli"}],
        ):
            result = handle_tool_call(
                "repomap_canonical_nodes",
                {
                    "root_path": "/tmp/fixture",
                    "pg_database": "postgres",
                    "kind": "python.module",
                },
            )

        self.assertEqual(
            result["structuredContent"],
            [{"canonical_key": "python.module:repomap_kg.cli"}],
        )
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            [{"canonical_key": "python.module:repomap_kg.cli"}],
        )

    def test_jsonrpc_initialize_tools_list_and_unknown_method(self):
        from repomap_kg.mcp_server import handle_jsonrpc_message

        initialized = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "repomap-kg")

        self.assertIsNone(
            handle_jsonrpc_message(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )

        tools = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        self.assertEqual(tools["result"]["tools"][0]["name"], "repomap_status")

        missing = handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 3, "method": "roots/list"}
        )
        self.assertEqual(missing["error"]["code"], -32601)

    def test_jsonrpc_tools_call_returns_result_or_mcp_error_payload(self):
        from repomap_kg.mcp_server import handle_jsonrpc_message

        with patch(
            "repomap_kg.mcp_server.repomap_status",
            return_value={"server": "repomap-kg"},
        ):
            response = handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "repomap_status",
                        "arguments": {"root_path": "/tmp/fixture"},
                    },
                }
            )

        self.assertEqual(response["result"]["structuredContent"]["server"], "repomap-kg")

        error = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "repomap_missing", "arguments": {}},
            }
        )
        self.assertTrue(error["result"]["isError"])
        self.assertIn("unknown RepoMap MCP tool", error["result"]["content"][0]["text"])

    def test_jsonrpc_helpers_and_stdio_server_loop(self):
        from repomap_kg.mcp_server import jsonrpc_error, jsonrpc_result, serve_stdio

        self.assertEqual(jsonrpc_result("a", {"ok": True})["id"], "a")
        self.assertEqual(jsonrpc_error("b", -1, "nope")["error"]["message"], "nope")

        input_stream = StringIO(
            "\n"
            '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
            "[]\n"
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        )
        output_stream = StringIO()

        self.assertEqual(
            serve_stdio(input_stream=input_stream, output_stream=output_stream),
            0,
        )

        lines = output_stream.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            json.loads(lines[0])["result"]["tools"][0]["name"],
            "repomap_status",
        )
        self.assertEqual(json.loads(lines[1])["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
