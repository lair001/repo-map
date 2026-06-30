import json
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    StorageSummaryRecord,
    identity_metadata_hash,
)


class McpServerUnitTests(unittest.TestCase):
    def write_mcp_config(self, payload):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "config.json"
        config_path.write_text(json.dumps(payload))
        return config_path

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

    def test_mcp_tools_list_contains_only_read_only_m1_tools(self):
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
            ],
        )
        serialized = json.dumps(tool_definitions(), sort_keys=True)
        self.assertNotIn("discover", serialized)
        self.assertNotIn("load-files", serialized)
        self.assertNotIn("write", serialized)

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
