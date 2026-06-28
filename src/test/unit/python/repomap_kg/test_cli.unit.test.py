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
from repomap_kg.observations import RawObservation, write_observations_jsonl
from repomap_kg.storage import FileNodeRecord, LoadSummary, StorageSchemaError


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
            ("entrypoints", ["--root-path", "/tmp/fixture"]),
            ("file-nodes", ["--root-path", "/tmp/fixture"]),
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
