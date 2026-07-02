import io
import json
import runpy
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg import __version__
from repomap_kg.cli import build_parser, main
from repomap_kg.files import FileRecord
from repomap_kg.host_mutators import HostMutatorRecord
from repomap_kg.observations import RawObservation, write_observations_jsonl
from repomap_kg.ops_config import OpsGraphStorageStatus
from repomap_kg.ops_refresh import OpsRefreshGraphResult, OpsRefreshGraphStatus
from repomap_kg.storage import (
    APISummaryRecord,
    BulkSummaryRecord,
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    CanonicalStorageSummaryRecord,
    EdgeRecord,
    EmailSummaryRecord,
    FileNodeRecord,
    FileNeighborhoodRecord,
    JSSummaryRecord,
    JSFrameworkSummaryRecord,
    LoadSummary,
    NeighborhoodRecord,
    NodeRecord,
    PythonSummaryRecord,
    RubySummaryRecord,
    StorageSchemaError,
    StorageSummaryRecord,
    TerraformSummaryRecord,
    identity_metadata_hash,
)


class CliUnitTests(unittest.TestCase):
    def test_version_option_prints_distribution_name_and_version(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main(["--version"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"repomap-kg {__version__}")

    def test_identity_json_outputs_stable_project_metadata(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main(["identity", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["name"], "RepoMap")
        self.assertEqual(payload["distribution"], "repomap-kg")
        self.assertEqual(payload["package"], "repomap_kg")
        self.assertEqual(payload["cli"], "repomap-kg")
        self.assertEqual(payload["license"], "Apache-2.0")
        self.assertEqual(payload["database"], "Postgres")

    def test_identity_text_outputs_key_value_metadata(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main(["identity"])

        self.assertEqual(exit_code, 0)
        self.assertIn("name: RepoMap", stdout.getvalue())
        self.assertIn("distribution: repomap-kg", stdout.getvalue())

    def test_no_arguments_prints_help(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("usage: repomap-kg", stdout.getvalue())

    def test_ops_config_check_prints_redacted_json_without_db_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
password = "mcp-ops1-fake-password"

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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["ops", "config-check", "--config", str(config_path), "--json"]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["postgres_status"]["db_checked"])
        self.assertEqual(payload["postgres"]["password"], "[REDACTED]")
        self.assertNotIn("mcp-ops1-fake-password", stdout.getvalue())

    def test_ops_config_check_text_output_stays_local_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["ops", "config-check", "--config", str(config_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops config status", stdout.getvalue())
        self.assertIn("local_only=true", stdout.getvalue())
        self.assertIn("no_public_tunnel=true", stdout.getvalue())
        self.assertIn("no_destructive_operations=true", stdout.getvalue())

    def test_ops_config_check_can_run_explicit_read_only_db_probe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.check_ops_postgres_status") as check_db:
                check_db.return_value.to_jsonable.return_value = {
                    "db_checked": True,
                    "connected": True,
                    "schema_available": True,
                    "required_tables": {"repositories": True},
                    "error": None,
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "config-check",
                            "--config",
                            str(config_path),
                            "--check-db",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["postgres_status"]["db_checked"])
        check_db.assert_called_once()

    def test_ops_config_check_reports_validation_errors_without_secret_leakage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
[postgres]
password = "mcp-ops1-fake-password"
""",
                encoding="utf-8",
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["ops", "config-check", "--config", str(config_path), "--json"]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("schema_version is required", stderr.getvalue())
        self.assertNotIn("mcp-ops1-fake-password", stderr.getvalue())

    def test_ops_graphs_prints_registry_json_without_db_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
password = "mcp-ops2-fake-password"

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

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["ops", "graphs", "--config", str(config_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["graph_count"], 2)
        self.assertEqual(payload["enabled_graph_count"], 1)
        self.assertEqual(payload["mcp_visible_graph_count"], 1)
        self.assertEqual(payload["private_graph_count"], 1)
        self.assertFalse(payload["db_checked"])
        self.assertTrue(payload["security"]["private_roots_read"] is False)
        self.assertEqual(payload["graphs"][1]["refresh_policy_status"], "deferred")
        self.assertIsNone(payload["graphs"][0]["storage_status"])
        self.assertNotIn("mcp-ops2-fake-password", stdout.getvalue())

    def test_ops_graphs_text_output_lists_graphs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["ops", "graphs", "--config", str(config_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops graph registry", stdout.getvalue())
        self.assertIn("repo-map | repo-map | public-dev | true | true", stdout.getvalue())
        self.assertIn("private_roots_read=false", stdout.getvalue())

    def test_ops_graphs_can_run_explicit_read_only_db_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.check_ops_graph_storage_status") as check_db:
                check_db.return_value = {
                    "repo-map": OpsGraphStorageStatus(
                        db_checked=True,
                        repository_name="repo-map",
                        schema_available=True,
                        repository_exists=True,
                        raw_observations=7,
                        canonical_nodes=5,
                        canonical_edges=3,
                    )
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "graphs",
                            "--config",
                            str(config_path),
                            "--check-db",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["db_checked"])
        self.assertEqual(payload["graphs"][0]["storage_status"]["raw_observations"], 7)
        self.assertEqual(payload["graphs"][0]["storage_status"]["canonical_nodes"], 5)
        self.assertEqual(payload["graphs"][0]["storage_status"]["canonical_edges"], 3)
        check_db.assert_called_once()

    def test_ops_refresh_graph_prints_json_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.refresh_graph") as refresh_one:
                refresh_one.return_value = OpsRefreshGraphResult(
                    graph_id="repo-map",
                    repository_name="repo-map",
                    privacy="public-dev",
                    enabled=True,
                    mcp_visible=True,
                    root_path_display="/placeholder/repo-map",
                    root_path_expanded="/placeholder/repo-map",
                    result="success",
                    repository_id=1,
                    run_id=2,
                    files=1,
                    observations=3,
                )
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "refresh-graph",
                            "--config",
                            str(config_path),
                            "--graph",
                            "repo-map",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "refresh-graph")
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["graphs"][0]["run_id"], 2)
        self.assertFalse(payload["safety"]["source_trees_mutated"])
        refresh_one.assert_called_once()

    def test_ops_refresh_enabled_prints_table_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.refresh_enabled_graphs") as refresh_enabled:
                refresh_enabled.return_value = (
                    OpsRefreshGraphResult(
                        graph_id="repo-map",
                        repository_name="repo-map",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        root_path_display="/placeholder/repo-map",
                        root_path_expanded="/placeholder/repo-map",
                        result="success",
                        repository_id=1,
                        run_id=2,
                        files=1,
                        observations=3,
                    ),
                )
                with redirect_stdout(stdout):
                    exit_code = main(
                        ["ops", "refresh-enabled", "--config", str(config_path)]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops refresh result", stdout.getvalue())
        self.assertIn("repo-map | repo-map | public-dev | success", stdout.getvalue())
        self.assertIn("destructive_db_actions=false", stdout.getvalue())
        refresh_enabled.assert_called_once()

    def test_ops_refresh_status_prints_json_without_root_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with (
                patch("repomap_kg.cli.query_refresh_status") as refresh_status,
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
                refresh_status.return_value = {
                    "repo-map": OpsRefreshGraphStatus(
                        graph_id="repo-map",
                        repository_name="repo-map",
                        privacy="public-dev",
                        enabled=True,
                        mcp_visible=True,
                        refresh_policy="manual",
                        root_path_display="/placeholder/repo-map",
                        root_path_expanded="/placeholder/repo-map",
                        db_checked=True,
                        repository_exists=True,
                        latest_run_id=2,
                        latest_run_status="complete",
                        raw_observations=3,
                        canonical_nodes=2,
                        canonical_edges=1,
                    )
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "refresh-status",
                            "--config",
                            str(config_path),
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["graphs"][0]["latest_run_id"], 2)
        self.assertFalse(payload["graphs"][0]["root_path_checked"])
        self.assertFalse(payload["safety"]["source_trees_mutated"])
        refresh_status.assert_called_once()

    def test_help_mentions_identity_command_and_project_purpose(self):
        help_text = build_parser().format_help()

        self.assertIn("RepoMap", help_text)
        self.assertIn("identity", help_text)
        self.assertIn("deterministic knowledge graph", help_text)

    def test_storage_subcommands_accept_shared_connection_options(self):
        parser = build_parser()
        cases = (
            (
                "load-files",
                [
                    "raw-observations.jsonl",
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    "/tmp/fixture",
                ],
            ),
            ("files", ["--root-path", "/tmp/fixture"]),
            ("canonical-nodes", ["--root-path", "/tmp/fixture"]),
            ("canonical-edges", ["--root-path", "/tmp/fixture"]),
            (
                "canonical-neighborhood",
                ["--root-path", "/tmp/fixture", "--node", "tool:nix"],
            ),
            (
                "explain-canonical-edge",
                [
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:bin/tool",
                    "--kind",
                    "executes",
                    "--target-key",
                    "tool:nix",
                ],
            ),
            ("entrypoints", ["--root-path", "/tmp/fixture"]),
            ("file-nodes", ["--root-path", "/tmp/fixture"]),
            ("nodes", ["--root-path", "/tmp/fixture"]),
            ("neighborhood", ["--root-path", "/tmp/fixture", "--node", "tool:nix"]),
            (
                "file-neighborhood",
                ["--root-path", "/tmp/fixture", "--path", "bin/tool"],
            ),
            ("edges", ["--root-path", "/tmp/fixture"]),
            ("host-mutators", ["--root-path", "/tmp/fixture"]),
            ("host-mutators-summary", ["--root-path", "/tmp/fixture"]),
            ("summary", ["--root-path", "/tmp/fixture"]),
            ("ruby-summary", ["--root-path", "/tmp/fixture"]),
            ("js-summary", ["--root-path", "/tmp/fixture"]),
            ("js-framework-summary", ["--root-path", "/tmp/fixture"]),
            ("terraform-summary", ["--root-path", "/tmp/fixture"]),
            ("python-summary", ["--root-path", "/tmp/fixture"]),
            ("email-summary", ["--root-path", "/tmp/fixture"]),
        )

        for subcommand, required_args in cases:
            with self.subTest(subcommand=subcommand):
                args = parser.parse_args(
                    [
                        "storage",
                        subcommand,
                        *required_args,
                        "--pg-host",
                        "/tmp/socket",
                        "--pg-port",
                        "5432",
                        "--pg-user",
                        "repo_map_test",
                        "--pg-database",
                        "postgres",
                        "--psql-command",
                        "/bin/psql",
                    ]
                )

                self.assertEqual(args.pg_host, "/tmp/socket")
                self.assertEqual(args.pg_port, "5432")
                self.assertEqual(args.pg_user, "repo_map_test")
                self.assertEqual(args.pg_database, "postgres")
                self.assertEqual(args.psql_command, "/bin/psql")

    def test_module_entrypoint_returns_cli_exit_status(self):
        with patch("repomap_kg.cli.main", return_value=7):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_module("repomap_kg", run_name="__main__")

        self.assertEqual(caught.exception.code, 7)

    def test_observations_normalize_prints_normalized_json(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="scripts/build.sh#call:nix-build",
            path="scripts/build.sh",
            start_line=21,
            end_line=21,
            name="nix-build",
            target="tool:nix",
            confidence="heuristic",
            extractor="shell-static",
            extractor_version="0.1.0",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([observation], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["observations", "normalize", str(jsonl_path), "--json"]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["edges"][0]["dst_node_key"], "tool:nix")

    def test_observations_normalize_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["observations", "normalize", str(jsonl_path), "--json"]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_files_prints_json_view(self):
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
                "content_hash": "0" * 64,
                "generated": False,
                "executable": False,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([observation], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["files", str(jsonl_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["path"], "README.md")
        self.assertEqual(payload[0]["confidence"], "manual")

    def test_files_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["files", str(jsonl_path), "--json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_entrypoints_prints_json_view(self):
        entrypoint = RawObservation(
            kind="file",
            source_id="bin/tool",
            path="bin/tool",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "shell",
                "role": "entrypoint",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": True,
            },
        )
        script = RawObservation(
            kind="file",
            source_id="scripts/helper.sh",
            path="scripts/helper.sh",
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
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([entrypoint, script], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["entrypoints", str(jsonl_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual([record["path"] for record in payload], ["bin/tool"])
        self.assertEqual(payload[0]["confidence"], "manual")

    def test_entrypoints_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["entrypoints", str(jsonl_path), "--json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_host_mutators_prints_json_view(self):
        mutation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh",
            start_line=2,
            end_line=2,
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
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([mutation], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["host-mutators", str(jsonl_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["path"], "scripts/maintain.sh")
        self.assertEqual(payload[0]["category"], "package-management")
        self.assertEqual(payload[0]["target"], "host:package-management")

    def test_host_mutators_filters_json_view(self):
        package = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh",
            start_line=2,
            end_line=2,
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
        )
        service = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:3:service",
            path="scripts/maintain.sh",
            start_line=3,
            end_line=3,
            name="launchctl bootout",
            target="host:service-management",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={
                "argv": ["sudo", "launchctl", "bootout", "system/example"],
                "category": "service-management",
                "effective_argv": ["launchctl", "bootout", "system/example"],
                "privileged": True,
                "reason": "launchctl bootout",
                "tool": "launchctl",
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([package, service], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "host-mutators",
                        str(jsonl_path),
                        "--category",
                        "service-management",
                        "--tool",
                        "launchctl",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual([record["name"] for record in payload], [
            "launchctl bootout",
        ])

    def test_host_mutators_summary_prints_json_view(self):
        privileged_rm = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:4:rm",
            path="scripts/maintain.sh",
            start_line=4,
            end_line=4,
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
        )
        user_rm = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:5:rm",
            path="scripts/maintain.sh",
            start_line=5,
            end_line=5,
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
        )
        brew = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh",
            start_line=2,
            end_line=2,
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
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([privileged_rm, user_rm, brew], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "host-mutators-summary",
                        str(jsonl_path),
                        "--category",
                        "filesystem-mutation",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, [
            {
                "category": "filesystem-mutation",
                "count": 2,
                "privileged_count": 1,
                "tool": "rm",
            }
        ])

    def test_host_mutators_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["host-mutators", str(jsonl_path), "--json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_storage_load_files_prints_json_summary(self):
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

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([observation], jsonl_path)
            stdout = io.StringIO()

            with patch(
                "repomap_kg.cli.load_file_observations",
                return_value=LoadSummary(repository_id=7, run_id=11, files=1),
            ) as load:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "load-files",
                            str(jsonl_path),
                            "--repository-name",
                            "fixture",
                            "--root-path",
                            "/tmp/fixture",
                            "--pg-host",
                            "/tmp/socket",
                            "--pg-port",
                            "5432",
                            "--pg-user",
                            "repo_map_test",
                            "--pg-database",
                            "postgres",
                            "--psql-command",
                            "/bin/psql",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["repository_id"], 7)
        self.assertEqual(payload["files"], 1)
        load.assert_called_once()
        self.assertEqual(
            load.call_args.args[0],
            [
                "-h",
                "/tmp/socket",
                "-p",
                "5432",
                "-U",
                "repo_map_test",
                "-d",
                "postgres",
            ],
        )

    def test_storage_load_files_reports_loader_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([], jsonl_path)
            stderr = io.StringIO()

            with patch(
                "repomap_kg.cli.load_file_observations",
                side_effect=StorageSchemaError("psql did not return a summary"),
            ):
                with redirect_stderr(stderr):
                    exit_code = main(
                        [
                            "storage",
                            "load-files",
                            str(jsonl_path),
                            "--repository-name",
                            "fixture",
                            "--root-path",
                            "/tmp/fixture",
                            "--json",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return", stderr.getvalue())

    def test_sources_ingest_feed_prints_json_summary_from_config_only(self):
        from repomap_kg.source_ingestion import FeedIngestionSummary

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "feed-source.toml"
            config_path.write_text("[source]\nid = \"example-news-feed\"\n")
            stdout = io.StringIO()
            expected = FeedIngestionSummary(
                source_id="example-news-feed",
                source_type="feed.rss",
                policy_status="allowed_with_limits",
                source_run_id="20260630T120000Z",
                artifact_path=".repomap/source-artifacts/example/rss.xml",
                artifact_sha256="0" * 64,
                artifact_bytes=512,
                observations=6,
                feed_observations=5,
                raw_observations=(),
                load_summary=LoadSummary(repository_id=7, run_id=11, files=1),
            )

            with patch(
                "repomap_kg.cli.ingest_feed_source",
                return_value=expected,
            ) as ingest:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "sources",
                            "ingest-feed",
                            "--config",
                            str(config_path),
                            "--repository-name",
                            "fixture",
                            "--root-path",
                            "/tmp/fixture",
                            "--pg-host",
                            "/tmp/socket",
                            "--pg-port",
                            "5432",
                            "--pg-user",
                            "repo_map_test",
                            "--pg-database",
                            "postgres",
                            "--psql-command",
                            "/bin/psql",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "example-news-feed")
        self.assertEqual(payload["repository_id"], 7)
        self.assertEqual(payload["run_id"], 11)
        self.assertEqual(payload["observations"], 6)
        ingest.assert_called_once()
        self.assertEqual(ingest.call_args.kwargs["config_path"], str(config_path))
        self.assertEqual(ingest.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_sources_ingest_feed_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "sources",
                        "ingest-feed",
                        "--config",
                        "/tmp/feed-source.toml",
                        "--repository-name",
                        "fixture",
                        "--url",
                        "https://example.invalid/rss.xml",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_sources_import_warc_prints_json_summary_from_config_only(self):
        from repomap_kg.source_ingestion import WarcImportSummary

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "warc-source.toml"
            config_path.write_text("[source]\nid = \"example-warc-archive\"\n")
            stdout = io.StringIO()
            expected = WarcImportSummary(
                source_id="example-warc-archive",
                source_type="saved_page.archive",
                policy_status="allowed",
                artifact_run_id="20260630T120000Z",
                artifact_manifest_id="manifest123",
                record_count=3,
                parsed_records=3,
                skipped_records=0,
                routed_payloads=2,
                observations=12,
                raw_observations=(),
                manifest=None,
                load_summary=LoadSummary(repository_id=7, run_id=11, files=2),
            )

            with patch(
                "repomap_kg.cli.import_warc_source",
                return_value=expected,
            ) as import_warc:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "sources",
                            "import-warc",
                            "--config",
                            str(config_path),
                            "--repository-name",
                            "fixture",
                            "--root-path",
                            "/tmp/fixture",
                            "--pg-host",
                            "/tmp/socket",
                            "--pg-port",
                            "5432",
                            "--pg-user",
                            "repo_map_test",
                            "--pg-database",
                            "postgres",
                            "--psql-command",
                            "/bin/psql",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "example-warc-archive")
        self.assertEqual(payload["repository_id"], 7)
        self.assertEqual(payload["run_id"], 11)
        self.assertEqual(payload["record_count"], 3)
        self.assertEqual(payload["routed_payloads"], 2)
        import_warc.assert_called_once()
        self.assertEqual(import_warc.call_args.kwargs["config_path"], str(config_path))
        self.assertEqual(import_warc.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_sources_import_warc_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "sources",
                        "import-warc",
                        "--config",
                        "/tmp/warc-source.toml",
                        "--repository-name",
                        "fixture",
                        "--url",
                        "https://example.invalid/archive.warc",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_bulk_plan_prints_json_manifest_from_config_only(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "bulk-fixture",
                "corpus_kind": "mixed_corpus",
                "file_count_included": 2,
                "file_count_skipped": 1,
                "no_provider_api": True,
                "no_external_fetch": True,
            }
        )

        with patch(
            "repomap_kg.cli.build_bulk_plan_from_config",
            return_value=expected,
        ) as build_plan:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "bulk",
                        "plan",
                        "--config",
                        "/tmp/bulk.toml",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "bulk-fixture")
        self.assertEqual(payload["file_count_included"], 2)
        self.assertTrue(payload["no_provider_api"])
        build_plan.assert_called_once_with("/tmp/bulk.toml")

    def test_bulk_import_prints_json_summary_and_uses_storage_options(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "bulk-fixture",
                "corpus_kind": "mixed_corpus",
                "observations": 12,
                "repository_id": 7,
                "run_id": 11,
                "no_provider_api": True,
            }
        )

        with patch(
            "repomap_kg.cli.import_bulk_source",
            return_value=expected,
        ) as import_bulk:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "bulk",
                        "import",
                        "--config",
                        "/tmp/bulk.toml",
                        "--repository-name",
                        "fixture",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-host",
                        "/tmp/socket",
                        "--pg-port",
                        "5432",
                        "--pg-user",
                        "repo_map_test",
                        "--pg-database",
                        "postgres",
                        "--psql-command",
                        "/bin/psql",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["repository_id"], 7)
        self.assertEqual(payload["observations"], 12)
        import_bulk.assert_called_once()
        self.assertEqual(import_bulk.call_args.kwargs["config_path"], "/tmp/bulk.toml")
        self.assertEqual(import_bulk.call_args.kwargs["repository_name"], "fixture")
        self.assertEqual(import_bulk.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(import_bulk.call_args.kwargs["psql_command"], "/bin/psql")
        self.assertEqual(
            import_bulk.call_args.kwargs["psql_args"],
            [
                "-h",
                "/tmp/socket",
                "-p",
                "5432",
                "-U",
                "repo_map_test",
                "-d",
                "postgres",
            ],
        )

    def test_bulk_plan_reports_policy_errors(self):
        from repomap_kg.bulk_ingestion import BulkPolicyError

        stderr = io.StringIO()
        with patch(
            "repomap_kg.cli.build_bulk_plan_from_config",
            side_effect=BulkPolicyError("source policy status blocked"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "bulk",
                        "plan",
                        "--config",
                        "/tmp/bulk.toml",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("source policy status blocked", stderr.getvalue())

    def test_bulk_import_rejects_arbitrary_root_argument_substitution(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "bulk",
                        "import",
                        "--config",
                        "/tmp/bulk.toml",
                        "--repository-name",
                        "fixture",
                        "--url",
                        "https://example.invalid/export",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_api_plan_prints_json_manifest_from_config_only(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "fixture-readonly-api",
                "api_source_class": "api.custom_documented_api",
                "request_count": 1,
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.build_api_plan_from_config",
            return_value=expected,
        ) as build_plan:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api",
                        "plan",
                        "--config",
                        "/tmp/api-source.toml",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "fixture-readonly-api")
        self.assertEqual(payload["request_count"], 1)
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        build_plan.assert_called_once_with("/tmp/api-source.toml")

    def test_api_acquire_prints_json_summary_and_uses_storage_options(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "fixture-readonly-api",
                "observations": 9,
                "repository_id": 7,
                "run_id": 11,
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.acquire_api_source",
            return_value=expected,
        ) as acquire:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api",
                        "acquire",
                        "--config",
                        "/tmp/api-source.toml",
                        "--repository-name",
                        "fixture",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-host",
                        "/tmp/socket",
                        "--pg-port",
                        "5432",
                        "--pg-user",
                        "repo_map_test",
                        "--pg-database",
                        "postgres",
                        "--psql-command",
                        "/bin/psql",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["repository_id"], 7)
        self.assertEqual(payload["observations"], 9)
        self.assertTrue(payload["no_network"])
        acquire.assert_called_once()
        self.assertEqual(acquire.call_args.kwargs["config_path"], "/tmp/api-source.toml")
        self.assertEqual(acquire.call_args.kwargs["repository_name"], "fixture")
        self.assertEqual(acquire.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(acquire.call_args.kwargs["psql_command"], "/bin/psql")
        self.assertEqual(
            acquire.call_args.kwargs["psql_args"],
            [
                "-h",
                "/tmp/socket",
                "-p",
                "5432",
                "-U",
                "repo_map_test",
                "-d",
                "postgres",
            ],
        )

    def test_api_plan_reports_policy_errors(self):
        from repomap_kg.api_ingestion import ApiPolicyError

        stderr = io.StringIO()
        with patch(
            "repomap_kg.cli.build_api_plan_from_config",
            side_effect=ApiPolicyError("source policy status blocked"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "api",
                        "plan",
                        "--config",
                        "/tmp/api-source.toml",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("source policy status blocked", stderr.getvalue())

    def test_api_acquire_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "api",
                        "acquire",
                        "--config",
                        "/tmp/api-source.toml",
                        "--repository-name",
                        "fixture",
                        "--url",
                        "https://example.invalid/items",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_github_plan_prints_json_manifest_from_config_only(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "github-public-fixture",
                "api_source_class": "api.github.repository",
                "owner": "fixture-owner",
                "repository": "fixture-repo",
                "request_count": 5,
                "fixture_transport_only": True,
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.build_github_api_plan_from_config",
            return_value=expected,
        ) as build_plan:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "github",
                        "plan",
                        "--config",
                        "/tmp/github-source.toml",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "github-public-fixture")
        self.assertEqual(payload["api_source_class"], "api.github.repository")
        self.assertEqual(payload["owner"], "fixture-owner")
        self.assertEqual(payload["repository"], "fixture-repo")
        self.assertEqual(payload["request_count"], 5)
        self.assertTrue(payload["fixture_transport_only"])
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        build_plan.assert_called_once_with("/tmp/github-source.toml")

    def test_github_acquire_prints_json_summary_and_uses_storage_options(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "github-public-fixture",
                "owner": "fixture-owner",
                "repository": "fixture-repo",
                "observations": 21,
                "repository_id": 7,
                "run_id": 11,
                "fixture_transport_only": True,
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.acquire_github_api_source",
            return_value=expected,
        ) as acquire:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "github",
                        "acquire",
                        "--config",
                        "/tmp/github-source.toml",
                        "--repository-name",
                        "fixture",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-host",
                        "/tmp/socket",
                        "--pg-port",
                        "5432",
                        "--pg-user",
                        "repo_map_test",
                        "--pg-database",
                        "postgres",
                        "--psql-command",
                        "/bin/psql",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["repository_id"], 7)
        self.assertEqual(payload["observations"], 21)
        self.assertEqual(payload["owner"], "fixture-owner")
        self.assertTrue(payload["fixture_transport_only"])
        self.assertTrue(payload["no_network"])
        acquire.assert_called_once()
        self.assertEqual(
            acquire.call_args.kwargs["config_path"],
            "/tmp/github-source.toml",
        )
        self.assertEqual(acquire.call_args.kwargs["repository_name"], "fixture")
        self.assertEqual(acquire.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(acquire.call_args.kwargs["psql_command"], "/bin/psql")
        self.assertEqual(
            acquire.call_args.kwargs["psql_args"],
            [
                "-h",
                "/tmp/socket",
                "-p",
                "5432",
                "-U",
                "repo_map_test",
                "-d",
                "postgres",
            ],
        )

    def test_github_plan_reports_policy_errors(self):
        from repomap_kg.github_api_ingestion import GitHubApiPolicyError

        stderr = io.StringIO()
        with patch(
            "repomap_kg.cli.build_github_api_plan_from_config",
            side_effect=GitHubApiPolicyError("source policy status blocked"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "github",
                        "plan",
                        "--config",
                        "/tmp/github-source.toml",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("source policy status blocked", stderr.getvalue())

    def test_github_acquire_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "github",
                        "acquire",
                        "--config",
                        "/tmp/github-source.toml",
                        "--repository-name",
                        "fixture",
                        "--url",
                        "https://github.com/fixture-owner/fixture-repo",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_storage_files_prints_filtered_json_records(self):
        records = (
            FileRecord(
                path="generated/report.json",
                language="json",
                role="generated",
                confidence="extracted",
                generated=True,
                executable=False,
            ),
            FileRecord(
                path="src/main/python/app.py",
                language="python",
                role="source",
                confidence="manual",
                generated=False,
                executable=False,
            ),
        )
        stdout = io.StringIO()

        with patch("repomap_kg.cli.query_file_records", return_value=records) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
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
                        "/tmp/socket",
                        "--pg-port",
                        "5432",
                        "--pg-user",
                        "repo_map_test",
                        "--pg-database",
                        "postgres",
                        "--psql-command",
                        "/bin/psql",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["path"], "src/main/python/app.py")
        self.assertEqual(len(payload), 1)
        self.assertEqual(
            query.call_args.args[0],
            [
                "-h",
                "/tmp/socket",
                "-p",
                "5432",
                "-U",
                "repo_map_test",
                "-d",
                "postgres",
            ],
        )
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_files_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_file_records",
            side_effect=StorageSchemaError("psql did not return file records"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "files",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return file records", stderr.getvalue())

    def test_storage_entrypoints_prints_json_records(self):
        records = (
            FileRecord(
                path="bin/tool",
                language="shell",
                role="entrypoint",
                confidence="manual",
                generated=False,
                executable=True,
            ),
            FileRecord(
                path="scripts/helper.sh",
                language="shell",
                role="script",
                confidence="extracted",
                generated=False,
                executable=True,
            ),
        )
        stdout = io.StringIO()

        with patch("repomap_kg.cli.query_file_records", return_value=records) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "entrypoints",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual([record["path"] for record in payload], ["bin/tool"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_entrypoints_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_file_records",
            side_effect=StorageSchemaError("psql did not return file records"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "entrypoints",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return file records", stderr.getvalue())

    def test_storage_file_nodes_prints_json_records(self):
        records = (
            FileNodeRecord(
                path="bin/tool",
                node_kind="file",
                node_name="bin/tool",
                node_stable_key="node:bin/tool:file:bin/tool",
                evidence_stable_key="evidence:bin/tool:0-0:fixture:bin/tool",
                extractor="fixture",
                extractor_version="0.1.0",
                raw_source_id="bin/tool",
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_file_node_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "file-nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--path",
                        "bin/tool",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["path"], "bin/tool")
        self.assertEqual(payload[0]["node_stable_key"], "node:bin/tool:file:bin/tool")
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["path"], "bin/tool")

    def test_storage_file_nodes_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_file_node_records",
            side_effect=StorageSchemaError("psql did not return file node records"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "file-nodes",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return file node records", stderr.getvalue())

    def test_storage_nodes_legacy_prints_json_records(self):
        records = (
            NodeRecord(
                path="bin/tool",
                node_kind="shell.command",
                node_name="nix build",
                node_stable_key="node:bin/tool:shell.command:x",
                start_line=2,
                end_line=2,
            ),
        )
        stdout = io.StringIO()

        with patch("repomap_kg.cli.query_node_records", return_value=records) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--legacy",
                        "--root-path",
                        "/tmp/fixture",
                        "--kind",
                        "shell.command",
                        "--path",
                        "bin/tool",
                        "--stable-key",
                        "node:bin/tool:shell.command:x",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["node_kind"], "shell.command")
        self.assertEqual(payload[0]["node_stable_key"], "node:bin/tool:shell.command:x")
        self.assertEqual(payload[0]["start_line"], 2)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["kind"], "shell.command")
        self.assertEqual(query.call_args.kwargs["path"], "bin/tool")
        self.assertEqual(
            query.call_args.kwargs["stable_key"],
            "node:bin/tool:shell.command:x",
        )

    def test_storage_nodes_prints_canonical_json_by_default(self):
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
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            return_value=records,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_node_records") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "nodes",
                            "--root-path",
                            "/tmp/fixture",
                            "--kind",
                            "file",
                            "--canonical-key",
                            "file:bin/tool",
                            "--path-prefix",
                            "bin/",
                            "--pg-database",
                            "postgres",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["canonical_key"], "file:bin/tool")
        self.assertNotIn("node_stable_key", payload[0])
        self.assertEqual(canonical_query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(canonical_query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(canonical_query.call_args.kwargs["kind"], "file")
        self.assertEqual(
            canonical_query.call_args.kwargs["canonical_key"],
            "file:bin/tool",
        )
        self.assertEqual(canonical_query.call_args.kwargs["path_prefix"], "bin/")
        self.assertEqual(canonical_query.call_args.kwargs["graph_key_version"], 1)
        legacy_query.assert_not_called()

    def test_storage_nodes_canonical_alias_prints_json_records(self):
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
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            return_value=records,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_node_records") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "nodes",
                            "--canonical",
                            "--root-path",
                            "/tmp/fixture",
                            "--kind",
                            "file",
                            "--canonical-key",
                            "file:bin/tool",
                            "--pg-database",
                            "postgres",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["canonical_key"], "file:bin/tool")
        self.assertEqual(canonical_query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(
            canonical_query.call_args.kwargs["canonical_key"],
            "file:bin/tool",
        )
        legacy_query.assert_not_called()

    def test_storage_nodes_rejects_canonical_and_legacy_together(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as canonical_query:
            with patch("repomap_kg.cli.query_node_records") as legacy_query:
                with redirect_stderr(stderr):
                    exit_code = main(
                        [
                            "storage",
                            "nodes",
                            "--canonical",
                            "--legacy",
                            "--root-path",
                            "/tmp/fixture",
                            "--json",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        self.assertIn("cannot combine --canonical and --legacy", stderr.getvalue())
        canonical_query.assert_not_called()
        legacy_query.assert_not_called()

    def test_storage_nodes_rejects_legacy_stable_key_filter_by_default(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--stable-key",
                        "node:bin/tool:shell.command:x",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("stable-key is a legacy node filter", stderr.getvalue())
        query.assert_not_called()

    def test_storage_nodes_rejects_legacy_path_filter_by_default(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--path",
                        "bin/tool",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("path is a legacy node filter", stderr.getvalue())
        query.assert_not_called()

    def test_storage_nodes_rejects_canonical_filters_in_legacy_mode(self):
        cases = (
            (
                ("--canonical-key", "file:bin/tool"),
                "canonical-key is a canonical node filter",
            ),
            (("--path-prefix", "bin"), "path-prefix is a canonical node filter"),
            (
                ("--graph-key-version", "2"),
                "graph-key-version is a canonical node filter",
            ),
        )

        for extra_args, expected_message in cases:
            with self.subTest(extra_args=extra_args):
                stderr = io.StringIO()
                with patch("repomap_kg.cli.query_node_records") as query:
                    with redirect_stderr(stderr):
                        exit_code = main(
                            [
                                "storage",
                                "nodes",
                                "--legacy",
                                "--root-path",
                                "/tmp/fixture",
                                *extra_args,
                                "--json",
                            ]
                        )

                self.assertEqual(exit_code, 1)
                self.assertIn(expected_message, stderr.getvalue())
                query.assert_not_called()

    def test_storage_nodes_rejects_invalid_canonical_key_by_default(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--canonical-key",
                        "file:bin/tool#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_nodes_rejects_unsupported_graph_key_version_by_default(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_nodes_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            side_effect=StorageSchemaError("psql did not return canonical node records"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical node records", stderr.getvalue())

    def test_storage_canonical_nodes_prints_json_records(self):
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
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "canonical-nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--path-prefix",
                        "bin/",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["canonical_key"], "file:bin/tool")
        self.assertEqual(payload[0]["metadata"], {"role": "entrypoint"})
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["kind"], "file")
        self.assertIsNone(query.call_args.kwargs["canonical_key"])
        self.assertEqual(query.call_args.kwargs["path_prefix"], "bin/")
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)

    def test_storage_canonical_nodes_prints_table_records(self):
        records = (
            CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="manual",
                conflict=False,
                metadata={"ignored": True},
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            return_value=records,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "canonical-nodes",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("canonical_key", output)
        self.assertIn("tool:nix", output)
        self.assertIn("last_seen_run_id", output)
        self.assertNotIn("metadata", output)

    def test_storage_canonical_nodes_validates_canonical_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--canonical-key",
                        "file:bin/tool#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_nodes_rejects_unsupported_graph_key_version(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_nodes_rejects_path_prefix_for_non_file_kind(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--kind",
                        "tool",
                        "--path-prefix",
                        "bin/",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("path-prefix only applies", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_nodes_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            side_effect=StorageSchemaError("psql did not return canonical nodes"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-nodes",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical nodes", stderr.getvalue())

    def test_storage_canonical_edges_prints_json_records(self):
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
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
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["source_key"], "file:bin/tool")
        self.assertEqual(payload[0]["edge_kind"], "executes")
        self.assertEqual(payload[0]["target_key"], "tool:nix")
        self.assertEqual(payload[0]["identity_metadata_hash"], hash_text)
        self.assertEqual(payload[0]["metadata"], {"commands": ["nix"]})
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["kind"], "executes")
        self.assertEqual(query.call_args.kwargs["source_key"], "file:bin/tool")
        self.assertEqual(query.call_args.kwargs["target_key"], "tool:nix")
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)

    def test_storage_canonical_edges_prints_table_records(self):
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
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "canonical-edges",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("source_key", output)
        self.assertIn("file:bin/tool", output)
        self.assertIn("identity_metadata_hash", output)
        self.assertIn(hash_text, output)
        self.assertIn("last_seen_run_id", output)
        self.assertNotIn("commands", output)

    def test_storage_canonical_edges_validates_source_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid source canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_validates_target_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--target-key",
                        "tool:nix#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid target canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_rejects_unsupported_kind(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--kind",
                        "invokes",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported canonical edge kind", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_rejects_unsupported_graph_key_version(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            side_effect=StorageSchemaError("psql did not return canonical edges"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-edges",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical edges", stderr.getvalue())

    def test_storage_explain_canonical_edge_prints_json_record(self):
        hash_text = identity_metadata_hash({"order": [2, 1], "scope": "flake"})
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={"order": [2, 1], "scope": "flake"},
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            return_value=record,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
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
                        "--identity-metadata-json",
                        '{"scope": "flake", "order": [2, 1]}',
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["edge"]["source_key"], "file:bin/tool")
        self.assertEqual(payload["edge"]["identity_metadata_hash"], hash_text)
        self.assertEqual(payload["evidence"][0]["raw_observation"]["ordinal"], 0)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["source_key"], "file:bin/tool")
        self.assertEqual(query.call_args.kwargs["kind"], "executes")
        self.assertEqual(query.call_args.kwargs["target_key"], "tool:nix")
        self.assertEqual(query.call_args.kwargs["identity_metadata_hash"], hash_text)
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)

    def test_storage_explain_canonical_edge_prints_table_record(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"ignored": True},
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            return_value=record,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
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
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("edge:", output)
        self.assertIn("file:bin/tool", output)
        self.assertIn("identity_metadata_hash", output)
        self.assertIn(hash_text, output)
        self.assertIn("evidence:", output)
        self.assertIn("raw_observation.ordinal", output)
        self.assertIn("repo-shell", output)
        self.assertNotIn("ignored", output)
        self.assertNotIn("argv", output)

    def test_storage_explain_canonical_edge_prints_missing_json_result(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            return_value=CanonicalEdgeExplanationRecord(edge=None, evidence=()),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
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
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"edge": None, "evidence": []})

    def test_storage_explain_canonical_edge_validates_source_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool#line:12",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid source canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_validates_target_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid target canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_unsupported_kind(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "invokes",
                        "--target-key",
                        "tool:nix",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported canonical edge kind", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_identity_metadata_non_object(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
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
                        "--identity-metadata-json",
                        "[]",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("identity-metadata-json must be a JSON object", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_malformed_identity_metadata_json(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
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
                        "--identity-metadata-json",
                        "{",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("identity-metadata-json must be a JSON object", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_unsupported_graph_key_version(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
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
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            side_effect=StorageSchemaError(
                "psql did not return canonical edge explanation"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
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
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return canonical edge explanation",
            stderr.getvalue(),
        )

    def test_storage_canonical_neighborhood_prints_json_record(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalNeighborhoodRecord(
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
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=record,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--direction",
                        "in",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["center"]["canonical_key"], "tool:nix")
        self.assertEqual(payload["nodes"][0]["canonical_key"], "file:bin/tool")
        self.assertEqual(payload["edges"][0]["identity_metadata_hash"], hash_text)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["node"], "tool:nix")
        self.assertEqual(query.call_args.kwargs["direction"], "in")
        self.assertEqual(query.call_args.kwargs["depth"], 1)
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)

    def test_storage_canonical_neighborhood_prints_table_record(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="manual",
                conflict=False,
                metadata={"ignored": True},
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=record,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("center: tool:nix", output)
        self.assertIn("Nodes:", output)
        self.assertIn("file:bin/tool", output)
        self.assertIn("Edges:", output)
        self.assertIn("identity_metadata_hash", output)
        self.assertIn(hash_text, output)
        self.assertNotIn("ignored", output)
        self.assertNotIn("commands", output)

    def test_storage_canonical_neighborhood_prints_missing_json_result(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=CanonicalNeighborhoodRecord(
                center=None,
                nodes=(),
                edges=(),
            ),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:missing",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"center": None, "nodes": [], "edges": []},
        )

    def test_storage_canonical_neighborhood_validates_node_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid node canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_neighborhood_rejects_unsupported_graph_key_version(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_neighborhood_rejects_depth_above_one(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--depth",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("canonical-neighborhood only supports depth 1", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_neighborhood_rejects_invalid_direction(self):
        parser = build_parser()
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                parser.parse_args(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--direction",
                        "sideways",
                    ]
                )

        self.assertEqual(caught.exception.code, 2)

    def test_storage_canonical_neighborhood_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            side_effect=StorageSchemaError(
                "psql did not return canonical neighborhood"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "canonical-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical neighborhood", stderr.getvalue())

    def test_storage_neighborhood_prints_json_record(self):
        record = NeighborhoodRecord(
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
        stdout = io.StringIO()

        with patch("repomap_kg.cli.query_neighborhood", return_value=record) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--direction",
                        "in",
                        "--depth",
                        "1",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["center"]["node_stable_key"], "tool:nix")
        self.assertEqual(payload["nodes"][0]["node_stable_key"], "tool:nix")
        self.assertEqual(payload["edges"][0]["dst_node_stable_key"], "tool:nix")
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["node"], "tool:nix")
        self.assertEqual(query.call_args.kwargs["direction"], "in")
        self.assertEqual(query.call_args.kwargs["depth"], 1)

    def test_storage_neighborhood_canonical_prints_json_record(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalNeighborhoodRecord(
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
                    metadata={},
                    confidence="extracted",
                    conflict=False,
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=record,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_neighborhood") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "neighborhood",
                            "--canonical",
                            "--root-path",
                            "/tmp/fixture",
                            "--node",
                            "tool:nix",
                            "--direction",
                            "in",
                            "--pg-database",
                            "postgres",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["center"]["canonical_key"], "tool:nix")
        self.assertEqual(payload["edges"][0]["identity_metadata_hash"], hash_text)
        self.assertEqual(canonical_query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(canonical_query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(canonical_query.call_args.kwargs["node"], "tool:nix")
        self.assertEqual(canonical_query.call_args.kwargs["direction"], "in")
        self.assertEqual(canonical_query.call_args.kwargs["depth"], 1)
        self.assertEqual(canonical_query.call_args.kwargs["graph_key_version"], 1)
        legacy_query.assert_not_called()

    def test_storage_neighborhood_canonical_rejects_invalid_node_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--canonical",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid node canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_neighborhood_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_neighborhood",
            side_effect=StorageSchemaError("psql did not return neighborhood"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return neighborhood", stderr.getvalue())

    def test_storage_file_neighborhood_prints_json_record(self):
        record = FileNeighborhoodRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_file_neighborhood",
            return_value=record,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "file-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--path",
                        "bin/tool",
                        "--direction",
                        "out",
                        "--depth",
                        "1",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["path"], "bin/tool")
        self.assertEqual(payload["centers"][0]["node_kind"], "shell.command")
        self.assertEqual(payload["edges"][0]["dst_node_stable_key"], "tool:nix")
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["path"], "bin/tool")
        self.assertEqual(query.call_args.kwargs["direction"], "out")
        self.assertEqual(query.call_args.kwargs["depth"], 1)

    def test_storage_file_neighborhood_canonical_maps_path_to_file_key(self):
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
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
            nodes=(),
            edges=(),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=record,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_file_neighborhood") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "file-neighborhood",
                            "--canonical",
                            "--root-path",
                            "/tmp/fixture",
                            "--path",
                            "bin/tool",
                            "--direction",
                            "out",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["center"]["canonical_key"], "file:bin/tool")
        self.assertEqual(canonical_query.call_args.kwargs["node"], "file:bin/tool")
        self.assertEqual(canonical_query.call_args.kwargs["direction"], "out")
        self.assertEqual(canonical_query.call_args.kwargs["depth"], 1)
        self.assertEqual(canonical_query.call_args.kwargs["graph_key_version"], 1)
        legacy_query.assert_not_called()

    def test_storage_file_neighborhood_canonical_rejects_repo_escaping_path(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "file-neighborhood",
                        "--canonical",
                        "--root-path",
                        "/tmp/fixture",
                        "--path",
                        "../outside",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid file path", stderr.getvalue())
        query.assert_not_called()

    def test_storage_file_neighborhood_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_file_neighborhood",
            side_effect=StorageSchemaError("psql did not return file neighborhood"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "file-neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--path",
                        "bin/tool",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return file neighborhood", stderr.getvalue())

    def test_storage_edges_legacy_prints_json_records(self):
        records = (
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
        )
        stdout = io.StringIO()

        with patch("repomap_kg.cli.query_edge_records", return_value=records) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--legacy",
                        "--root-path",
                        "/tmp/fixture",
                        "--kind",
                        "shell.command",
                        "--source-node",
                        "node:bin/tool:shell.command:x",
                        "--target-node",
                        "tool:nix",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["edge_kind"], "shell.command")
        self.assertEqual(payload[0]["dst_node_stable_key"], "tool:nix")
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["kind"], "shell.command")
        self.assertEqual(
            query.call_args.kwargs["source_node"],
            "node:bin/tool:shell.command:x",
        )
        self.assertEqual(query.call_args.kwargs["target_node"], "tool:nix")

    def test_storage_edges_prints_canonical_json_by_default(self):
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_edge_records") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
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
                            "--pg-database",
                            "postgres",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["source_key"], "file:bin/tool")
        self.assertEqual(payload[0]["edge_kind"], "executes")
        self.assertEqual(payload[0]["target_key"], "tool:nix")
        self.assertEqual(payload[0]["identity_metadata_hash"], hash_text)
        self.assertNotIn("edge_stable_key", payload[0])
        self.assertEqual(canonical_query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(canonical_query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(canonical_query.call_args.kwargs["kind"], "executes")
        self.assertEqual(canonical_query.call_args.kwargs["source_key"], "file:bin/tool")
        self.assertEqual(canonical_query.call_args.kwargs["target_key"], "tool:nix")
        self.assertEqual(canonical_query.call_args.kwargs["graph_key_version"], 1)
        legacy_query.assert_not_called()

    def test_storage_edges_canonical_alias_prints_json_records(self):
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_edge_records") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "edges",
                            "--canonical",
                            "--root-path",
                            "/tmp/fixture",
                            "--kind",
                            "executes",
                            "--source-key",
                            "file:bin/tool",
                            "--target-key",
                            "tool:nix",
                            "--pg-database",
                            "postgres",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["source_key"], "file:bin/tool")
        self.assertEqual(payload[0]["identity_metadata_hash"], hash_text)
        self.assertEqual(canonical_query.call_args.args[0], ["-d", "postgres"])
        legacy_query.assert_not_called()

    def test_storage_edges_rejects_canonical_and_legacy_together(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as canonical_query:
            with patch("repomap_kg.cli.query_edge_records") as legacy_query:
                with redirect_stderr(stderr):
                    exit_code = main(
                        [
                            "storage",
                            "edges",
                            "--canonical",
                            "--legacy",
                            "--root-path",
                            "/tmp/fixture",
                            "--json",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        self.assertIn("cannot combine --canonical and --legacy", stderr.getvalue())
        canonical_query.assert_not_called()
        legacy_query.assert_not_called()

    def test_storage_edges_rejects_legacy_node_filters_by_default(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-node",
                        "node:bin/tool:shell.command:x",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("source-node is a legacy edge filter", stderr.getvalue())
        query.assert_not_called()

    def test_storage_edges_rejects_canonical_filters_in_legacy_mode(self):
        cases = (
            (("--source-key", "file:bin/tool"), "source-key is a canonical edge filter"),
            (("--target-key", "tool:nix"), "target-key is a canonical edge filter"),
            (
                ("--graph-key-version", "2"),
                "graph-key-version is a canonical edge filter",
            ),
        )

        for extra_args, expected_message in cases:
            with self.subTest(extra_args=extra_args):
                stderr = io.StringIO()
                with patch("repomap_kg.cli.query_edge_records") as query:
                    with redirect_stderr(stderr):
                        exit_code = main(
                            [
                                "storage",
                                "edges",
                                "--legacy",
                                "--root-path",
                                "/tmp/fixture",
                                *extra_args,
                                "--json",
                            ]
                        )

                self.assertEqual(exit_code, 1)
                self.assertIn(expected_message, stderr.getvalue())
                query.assert_not_called()

    def test_storage_edges_rejects_invalid_source_key_by_default(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid source canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_edges_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            side_effect=StorageSchemaError("psql did not return canonical edge records"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical edge records", stderr.getvalue())

    def test_storage_host_mutators_prints_json_records(self):
        records = (
            HostMutatorRecord(
                path="scripts/maintain.sh",
                line=2,
                name="rm",
                target="host:filesystem-mutation",
                category="filesystem-mutation",
                tool="rm",
                privileged=True,
                confidence="heuristic",
                reason="rm host filesystem path",
                argv=("sudo", "rm", "-rf", "/Library/Caches/example"),
                effective_argv=("rm", "-rf", "/Library/Caches/example"),
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_host_mutator_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "host-mutators",
                        "--root-path",
                        "/tmp/fixture",
                        "--category",
                        "filesystem-mutation",
                        "--tool",
                        "rm",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["category"], "filesystem-mutation")
        self.assertEqual(payload[0]["effective_argv"], [
            "rm",
            "-rf",
            "/Library/Caches/example",
        ])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(
            query.call_args.kwargs["category"],
            "filesystem-mutation",
        )
        self.assertEqual(query.call_args.kwargs["tool"], "rm")

    def test_storage_host_mutators_canonical_prints_json_records(self):
        records = (
            CanonicalEdgeRecord(
                source_key="file:scripts/maintain.sh",
                edge_kind="mutates_host",
                target_key="host.category:package-management",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash="a" * 64,
                metadata={
                    "tools": ["brew"],
                    "privileged_observed": False,
                    "reasons": ["brew install"],
                },
                confidence="heuristic",
                conflict=False,
                first_seen_run_id=11,
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "host-mutators",
                        "--canonical",
                        "--root-path",
                        "/tmp/fixture",
                        "--category",
                        "package-management",
                        "--tool",
                        "brew",
                        "--source-key",
                        "file:scripts/maintain.sh",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, [records[0].to_dict()])
        self.assertNotIn("stable_key", payload[0])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["kind"], "mutates_host")
        self.assertEqual(
            query.call_args.kwargs["source_key"],
            "file:scripts/maintain.sh",
        )
        self.assertEqual(
            query.call_args.kwargs["target_key"],
            "host.category:package-management",
        )
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)

    def test_storage_host_mutators_canonical_filters_tool_metadata(self):
        records = (
            CanonicalEdgeRecord(
                source_key="file:scripts/maintain.sh",
                edge_kind="mutates_host",
                target_key="host.category:package-management",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash="a" * 64,
                metadata={"tools": ["brew"]},
                confidence="heuristic",
                conflict=False,
                first_seen_run_id=11,
                last_seen_run_id=11,
            ),
            CanonicalEdgeRecord(
                source_key="file:scripts/maintain.sh",
                edge_kind="mutates_host",
                target_key="host.category:system-activation",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash="b" * 64,
                metadata={"tools": ["darwin-rebuild"]},
                confidence="heuristic",
                conflict=False,
                first_seen_run_id=11,
                last_seen_run_id=11,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "host-mutators",
                        "--canonical",
                        "--root-path",
                        "/tmp/fixture",
                        "--tool",
                        "brew",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["metadata"], {"tools": ["brew"]})

    def test_storage_host_mutators_canonical_rejects_invalid_source_key(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "storage",
                    "host-mutators",
                    "--canonical",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:scripts/maintain.sh#line:2",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("--source-key", stderr.getvalue())

    def test_storage_host_mutators_legacy_rejects_canonical_source_key(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "storage",
                    "host-mutators",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:scripts/maintain.sh",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("--source-key requires --canonical", stderr.getvalue())

    def test_storage_host_mutators_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_host_mutator_records",
            side_effect=StorageSchemaError("psql did not return host-mutators"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "host-mutators",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return host-mutators", stderr.getvalue())

    def test_storage_host_mutators_summary_prints_json_records(self):
        records = (
            HostMutatorRecord(
                path="scripts/maintain.sh",
                line=4,
                name="rm",
                target="host:filesystem-mutation",
                category="filesystem-mutation",
                tool="rm",
                privileged=True,
                confidence="heuristic",
                reason="rm host filesystem path",
                argv=("sudo", "rm", "-rf", "/Library/Caches/example"),
                effective_argv=("rm", "-rf", "/Library/Caches/example"),
            ),
            HostMutatorRecord(
                path="scripts/maintain.sh",
                line=5,
                name="rm",
                target="host:filesystem-mutation",
                category="filesystem-mutation",
                tool="rm",
                privileged=False,
                confidence="heuristic",
                reason="rm host filesystem path",
                argv=("rm", "-rf", "~/Library/Caches/example"),
                effective_argv=("rm", "-rf", "~/Library/Caches/example"),
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_host_mutator_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "host-mutators-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--category",
                        "filesystem-mutation",
                        "--tool",
                        "rm",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, [
            {
                "category": "filesystem-mutation",
                "count": 2,
                "privileged_count": 1,
                "tool": "rm",
            }
        ])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(
            query.call_args.kwargs["category"],
            "filesystem-mutation",
        )
        self.assertEqual(query.call_args.kwargs["tool"], "rm")

    def test_storage_host_mutators_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_host_mutator_records",
            side_effect=StorageSchemaError("psql did not return host-mutators"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "host-mutators-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return host-mutators", stderr.getvalue())

    def test_storage_summary_legacy_prints_json_record(self):
        summary = StorageSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_storage_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "summary",
                        "--legacy",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["files"], 2)
        self.assertEqual(payload["edges"], 2)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_summary_prints_canonical_json_by_default(self):
        summary = CanonicalStorageSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_storage_summary",
            return_value=summary,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_storage_summary") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "summary",
                            "--root-path",
                            "/tmp/fixture",
                            "--pg-database",
                            "postgres",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["repository_name"], "fixture")
        self.assertEqual(payload["legacy_nodes"], 5)
        self.assertEqual(payload["canonical_nodes"], 6)
        self.assertEqual(payload["canonical_edges"], 7)
        self.assertEqual(payload["canonical_evidence"], 8)
        self.assertNotIn("repository_id", payload)
        self.assertNotIn("nodes", payload)
        self.assertEqual(canonical_query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(canonical_query.call_args.kwargs["root_path"], "/tmp/fixture")
        legacy_query.assert_not_called()

    def test_storage_summary_canonical_alias_prints_json_record(self):
        summary = CanonicalStorageSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_storage_summary",
            return_value=summary,
        ) as canonical_query:
            with patch("repomap_kg.cli.query_storage_summary") as legacy_query:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "summary",
                            "--canonical",
                            "--root-path",
                            "/tmp/fixture",
                            "--pg-database",
                            "postgres",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, summary.to_dict())
        self.assertEqual(canonical_query.call_args.args[0], ["-d", "postgres"])
        legacy_query.assert_not_called()

    def test_storage_summary_rejects_canonical_and_legacy_together(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_storage_summary") as canonical_query:
            with patch("repomap_kg.cli.query_storage_summary") as legacy_query:
                with redirect_stderr(stderr):
                    exit_code = main(
                        [
                            "storage",
                            "summary",
                            "--canonical",
                            "--legacy",
                            "--root-path",
                            "/tmp/fixture",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        self.assertIn("cannot combine --canonical and --legacy", stderr.getvalue())
        canonical_query.assert_not_called()
        legacy_query.assert_not_called()

    def test_storage_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_storage_summary",
            side_effect=StorageSchemaError(
                "psql did not return canonical storage summary"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical storage summary", stderr.getvalue())

    def test_storage_ruby_summary_prints_json_record(self):
        summary = RubySummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_ruby_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "ruby-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["routes"], 5)
        self.assertEqual(payload["test_methods"], 4)
        self.assertEqual(payload["gem_dependencies"], 5)
        self.assertEqual(payload["profile_counts"]["minitest"], 2)
        self.assertTrue(payload["no_execution"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_ruby_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_ruby_summary",
            side_effect=StorageSchemaError("psql did not return ruby summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "ruby-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return ruby summary", stderr.getvalue())

    def test_storage_js_summary_prints_json_record(self):
        summary = JSSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "js-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["components"], 5)
        self.assertEqual(payload["test_cases"], 4)
        self.assertEqual(payload["source_map_references"], 1)
        self.assertEqual(payload["frontend_asset_files"], 2)
        self.assertEqual(payload["profile_counts"]["react"], 3)
        self.assertTrue(payload["no_execution"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_js_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_summary",
            side_effect=StorageSchemaError("psql did not return js summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "js-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return js summary", stderr.getvalue())

    def test_storage_js_framework_summary_prints_json_record(self):
        summary = js_framework_summary_fixture()
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_framework_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "js-framework-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["framework_observations"], 42)
        self.assertEqual(payload["framework_profiles"]["express"], 8)
        self.assertEqual(payload["node"]["entrypoints"], 2)
        self.assertEqual(payload["express"]["dynamic_routes"], 1)
        self.assertEqual(payload["next"]["route_handlers"], 1)
        self.assertEqual(payload["jquery"]["ajax_references"], 2)
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_js_framework_summary_prints_table_record(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_framework_summary",
            return_value=js_framework_summary_fixture(),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "js-framework-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        table = stdout.getvalue()
        self.assertIn("framework_observations", table)
        self.assertIn("entrypoints=2", table)
        self.assertIn("dynamic_routes=1", table)
        self.assertIn("no_fetch=true", table)

    def test_storage_js_framework_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_js_framework_summary",
            side_effect=StorageSchemaError(
                "psql did not return js framework summary"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "js-framework-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return js framework summary",
            stderr.getvalue(),
        )

    def test_storage_terraform_summary_prints_json_record(self):
        summary = terraform_summary_fixture()
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_terraform_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "terraform-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["terraform_observations"], 120)
        self.assertEqual(payload["file_families"]["tf"], 5)
        self.assertEqual(payload["terraform"]["resources"], 12)
        self.assertEqual(payload["references"]["remote_refs_not_fetched"], 2)
        self.assertEqual(payload["tfvars"]["variables"], 8)
        self.assertFalse(payload["tfvars"]["literal_values_exposed"])
        self.assertTrue(payload["safety"]["no_terraform_cli"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_terraform_summary_prints_table_record(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_terraform_summary",
            return_value=terraform_summary_fixture(),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "terraform-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        table = stdout.getvalue()
        self.assertIn("terraform_observations", table)
        self.assertIn("resources=12", table)
        self.assertIn("literal_values_exposed=false", table)
        self.assertIn("no_terraform_cli=true", table)

    def test_storage_terraform_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_terraform_summary",
            side_effect=StorageSchemaError(
                "psql did not return terraform summary"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "terraform-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return terraform summary",
            stderr.getvalue(),
        )

    def test_storage_python_summary_prints_json_record(self):
        summary = python_summary_fixture()
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_python_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "python-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["python_observations"], 250)
        self.assertEqual(payload["package_files"]["requirements"], 3)
        self.assertEqual(payload["packaging"]["requirements"], 20)
        self.assertEqual(payload["tests"]["pytest_tests"], 20)
        self.assertEqual(payload["frameworks"]["fastapi_routes"], 10)
        self.assertEqual(payload["references"]["direct_urls_not_fetched"], 2)
        self.assertTrue(payload["dogfooding"]["repo_map_profile_observed"])
        self.assertTrue(payload["safety"]["no_imports"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_python_summary_prints_table_record(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_python_summary",
            return_value=python_summary_fixture(),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "python-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        table = stdout.getvalue()
        self.assertIn("python_observations", table)
        self.assertIn("pytest_tests=20", table)
        self.assertIn("fastapi_routes=10", table)
        self.assertIn("no_imports=true", table)

    def test_storage_python_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_python_summary",
            side_effect=StorageSchemaError("psql did not return python summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "python-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return python summary",
            stderr.getvalue(),
        )

    def test_storage_email_summary_prints_json_record(self):
        summary = EmailSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_email_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "email-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path"], "/tmp/fixture")
        self.assertEqual(payload["mailboxes"], 1)
        self.assertEqual(payload["messages"], 10)
        self.assertEqual(payload["mbox_messages"], 2)
        self.assertEqual(payload["attachment_stubs"], 3)
        self.assertEqual(payload["list_unsubscribe_references"], 1)
        self.assertTrue(payload["no_provider_api"])
        self.assertTrue(payload["no_mutation"])
        self.assertTrue(payload["no_body_text"])
        self.assertTrue(payload["no_attachment_content"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_email_summary_prints_table_record(self):
        summary = EmailSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_email_summary",
            return_value=summary,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "email-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("mailboxes", stdout.getvalue())
        self.assertIn("attachment_stubs", stdout.getvalue())
        self.assertIn("no_provider_api", stdout.getvalue())
        self.assertIn("no_attachment_content", stdout.getvalue())

    def test_storage_email_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_email_summary",
            side_effect=StorageSchemaError("psql did not return email summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "email-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return email summary", stderr.getvalue())

    def test_storage_bulk_summary_prints_json_record(self):
        summary = BulkSummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_bulk_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path_summary"], ".")
        self.assertEqual(payload["bulk_runs"], 2)
        self.assertEqual(payload["source_ids"], ["email-export", "mixed-corpus"])
        self.assertEqual(payload["corpus_kinds"]["mixed_corpus"], 1)
        self.assertEqual(payload["skip_reasons"]["archive_deferred"], 1)
        self.assertEqual(payload["observations_with_bulk_provenance"], 42)
        self.assertTrue(payload["no_provider_api"])
        self.assertTrue(payload["no_external_fetch"])
        self.assertTrue(payload["no_source_mutation"])
        self.assertTrue(payload["no_archive_decompression"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_bulk_summary_prints_table_record(self):
        summary = BulkSummaryRecord(
            root_path_summary=".",
            repository_name="fixture",
            bulk_runs=1,
            sources=1,
            source_ids=("mixed-corpus",),
            corpus_kinds={"mixed_corpus": 1},
            policy_statuses={"allowed_with_limits": 1},
            file_count_included=6,
            file_count_skipped=2,
            total_bytes_included=2048,
            extractor_counts={"javascript": 1},
            skip_reasons={"excluded_directory": 1},
            diagnostic_counts={},
            redaction_counts={},
            limit_hit_count=0,
            max_files_hit_count=0,
            max_total_bytes_hit_count=0,
            max_file_bytes_hit_count=0,
            max_depth_hit_count=0,
            archive_deferred=0,
            warc_deferred=0,
            email_export_runs=0,
            mixed_corpus_runs=1,
            observations_with_bulk_provenance=12,
            no_provider_api=True,
            no_external_fetch=True,
            no_source_mutation=True,
            no_archive_decompression=True,
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_bulk_summary",
            return_value=summary,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("bulk_runs", stdout.getvalue())
        self.assertIn("source_ids", stdout.getvalue())
        self.assertIn("mixed_corpus=1", stdout.getvalue())
        self.assertIn("no_archive_decompression", stdout.getvalue())

    def test_storage_bulk_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_bulk_summary",
            side_effect=StorageSchemaError("psql did not return bulk summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "bulk-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return bulk summary", stderr.getvalue())

    def test_storage_api_summary_prints_json_record(self):
        summary = APISummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_api_summary",
            return_value=summary,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "api-summary",
                        "--root-path",
                        "/tmp/fixture",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["root_path_summary"], ".")
        self.assertEqual(payload["api_runs"], 1)
        self.assertEqual(payload["source_ids"], ["fixture-readonly-api"])
        self.assertEqual(payload["provider_names"]["Fixture Provider"], 1)
        self.assertEqual(payload["methods"]["GET"], 1)
        self.assertEqual(payload["observations_with_api_provenance"], 7)
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        self.assertTrue(payload["no_credentials_resolved"])
        self.assertTrue(payload["no_scheduler"])
        self.assertTrue(payload["no_provider_specific_behavior"])
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_storage_api_summary_prints_table_record(self):
        summary = APISummaryRecord(
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
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_api_summary",
            return_value=summary,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "api-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("api_runs", stdout.getvalue())
        self.assertIn("source_ids", stdout.getvalue())
        self.assertIn("api.rest=1", stdout.getvalue())
        self.assertIn("Fixture Provider=1", stdout.getvalue())
        self.assertIn("no_provider_specific_behavior", stdout.getvalue())

    def test_storage_api_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_api_summary",
            side_effect=StorageSchemaError("psql did not return api summary"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "api-summary",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return api summary", stderr.getvalue())

    def test_discover_prints_text_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "src" / "main" / "python" / "app.py"
            source.parent.mkdir(parents=True)
            source.write_text("print('ok')\n")
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["discover", str(root)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "discovered 2 observations")

    def test_discover_reports_profile_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profile = root / "repomap-profile.toml"
            profile.write_text(
                """
[confidence_overrides]
"README.md" = "certain"
"""
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["discover", str(root), "--profile", str(profile)])

        self.assertEqual(exit_code, 1)
        self.assertIn("confidence_overrides", stderr.getvalue())


def js_framework_summary_fixture() -> JSFrameworkSummaryRecord:
    return JSFrameworkSummaryRecord(
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


def terraform_summary_fixture() -> TerraformSummaryRecord:
    return TerraformSummaryRecord(
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


def python_summary_fixture() -> PythonSummaryRecord:
    return PythonSummaryRecord(
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


if __name__ == "__main__":
    unittest.main()
