import io
import json
import runpy
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from repomap_kg import __version__
from repomap_kg.cli import build_parser, main
from repomap_kg.files import FileRecord
from repomap_kg.host_mutators import HostMutatorRecord
from repomap_kg.observations import RawObservation, write_observations_jsonl
from repomap_kg.storage import (
    CanonicalEdgeRecord,
    CanonicalNodeRecord,
    EdgeRecord,
    FileNodeRecord,
    FileNeighborhoodRecord,
    LoadSummary,
    NeighborhoodRecord,
    NodeRecord,
    StorageSchemaError,
    StorageSummaryRecord,
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

    def test_storage_nodes_prints_json_records(self):
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

    def test_storage_nodes_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_node_records",
            side_effect=StorageSchemaError("psql did not return node records"),
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
        self.assertIn("psql did not return node records", stderr.getvalue())

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

    def test_storage_edges_prints_json_records(self):
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

    def test_storage_edges_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_edge_records",
            side_effect=StorageSchemaError("psql did not return edge records"),
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
        self.assertIn("psql did not return edge records", stderr.getvalue())

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

    def test_storage_summary_prints_json_record(self):
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

    def test_storage_summary_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_storage_summary",
            side_effect=StorageSchemaError("psql did not return storage summary"),
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
        self.assertIn("psql did not return storage summary", stderr.getvalue())

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
        self.assertEqual(stdout.getvalue().strip(), "discovered 1 files")

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


if __name__ == "__main__":
    unittest.main()
