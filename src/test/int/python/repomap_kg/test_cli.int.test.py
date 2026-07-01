import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repomap_kg.nix import resolve_repo_path
from repomap_kg.observations import RawObservation, write_observations_jsonl


REPO_ROOT = Path(__file__).resolve().parents[5]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"


class CliIntegrationTests(unittest.TestCase):
    def run_cli(self, *args, input_text=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SOURCE_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "repomap_kg", *args],
            check=False,
            cwd=REPO_ROOT,
            env=env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_module_entrypoint_prints_version(self):
        result = self.run_cli("--version")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^repomap-kg \d+\.\d+\.\d+$")
        self.assertEqual(result.stderr, "")

    def test_module_entrypoint_can_run_in_process(self):
        exit_code, stdout, stderr = self.run_module_entrypoint("--version")

        self.assertEqual(exit_code, 0)
        self.assertRegex(stdout.strip(), r"^repomap-kg \d+\.\d+\.\d+$")
        self.assertEqual(stderr, "")

    def test_identity_command_emits_json_for_scripts_and_tests(self):
        exit_code, stdout, stderr = self.run_module_entrypoint("identity", "--json")

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["name"], "RepoMap")
        self.assertEqual(payload["cli"], "repomap-kg")
        self.assertEqual(payload["database"], "Postgres")
        self.assertEqual(stderr, "")

    def test_observation_normalization_command_accepts_fixture_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_root = Path(tmpdir) / "fixture-repo"
            fixture_script = fixture_root / "scripts" / "build.sh"
            fixture_script.parent.mkdir(parents=True)
            fixture_script.write_text("#!/usr/bin/env bash\nnix build .#checks\n")
            raw_jsonl = fixture_root / "raw-observations.jsonl"
            write_observations_jsonl(
                [
                    RawObservation(
                        kind="shell.command",
                        source_id="scripts/build.sh#call:nix-build",
                        path="scripts/build.sh",
                        start_line=2,
                        end_line=2,
                        name="nix build",
                        target="tool:nix",
                        confidence="heuristic",
                        extractor="fixture-shell",
                        extractor_version="0.1.0",
                        metadata={"fixture": True},
                    )
                ],
                raw_jsonl,
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(raw_jsonl), "--json"
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 1)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 1)
        self.assertEqual(payload["nodes"][0]["path"], "scripts/build.sh")
        self.assertEqual(payload["edges"][0]["dst_node_key"], "tool:nix")
        self.assertEqual(stderr, "")

    def test_observation_normalization_command_prints_text_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl(
                [
                    RawObservation(
                        kind="file",
                        source_id="README.md",
                        path="README.md",
                        confidence="extracted",
                        extractor="fixture-discovery",
                        extractor_version="0.1.0",
                    )
                ],
                raw_jsonl,
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(raw_jsonl)
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(
            "normalized 1 observations into 1 nodes, 0 edges, and 1 evidence records",
            stdout,
        )
        self.assertEqual(stderr, "")

    def test_observation_normalization_command_reports_bad_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text("{bad json}\n")

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(bad_jsonl), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("invalid JSON", stderr)

    def test_observation_normalization_command_reports_schema_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "file",
                        "source_id": "README.md",
                        "path": "README.md",
                        "confidence": "certain",
                        "extractor": "fixture-discovery",
                        "extractor_version": "0.1.0",
                        "metadata": {},
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(bad_jsonl), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("confidence must be one of", stderr)

    def test_observation_normalization_command_reports_bad_line_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "shell.command",
                        "source_id": "scripts/build.sh#call:nix-build",
                        "path": "scripts/build.sh",
                        "start_line": "2",
                        "end_line": 2,
                        "name": "nix build",
                        "target": "tool:nix",
                        "confidence": "heuristic",
                        "extractor": "fixture-shell",
                        "extractor_version": "0.1.0",
                        "metadata": {},
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(bad_jsonl), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("start_line must be an integer", stderr)

    def test_storage_load_files_command_reports_schema_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "file",
                        "source_id": "README.md",
                        "path": "README.md",
                        "confidence": "certain",
                        "extractor": "fixture-discovery",
                        "extractor_version": "0.1.0",
                        "metadata": {},
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "storage",
                "load-files",
                str(bad_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("confidence must be one of", stderr)

    def test_discover_command_emits_file_observations_for_fixture_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "bin" / "tool",
                "#!/usr/bin/env bash\nnix build .#checks\n",
            )
            (fixture / "bin" / "tool").chmod(
                (fixture / "bin" / "tool").stat().st_mode | 0o111
            )
            self.write_fixture(
                fixture / "src" / "main" / "python" / "app.py",
                "print('ok')\n",
            )
            self.write_fixture(
                fixture / "src" / "test" / "unit" / "python" / "app.unit.test.py",
                "import unittest\n",
            )
            self.write_fixture(fixture / "flake.nix", "{ outputs = _: {}; }\n")
            self.write_fixture(fixture / "generated" / "report.json", "{}\n")
            self.write_fixture(fixture / ".git" / "config", "ignored\n")

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        file_observations = [
            observation for observation in observations if observation["kind"] == "file"
        ]
        shell_observations = [
            observation
            for observation in observations
            if observation["kind"] == "shell.command"
        ]
        paths = [observation["path"] for observation in file_observations]
        metadata_by_path = {
            observation["path"]: observation["metadata"]
            for observation in file_observations
        }
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            paths,
            [
                "bin/tool",
                "flake.nix",
                "generated/report.json",
                "src/main/python/app.py",
                "src/test/unit/python/app.unit.test.py",
            ],
        )
        self.assertEqual(len(shell_observations), 1)
        self.assertEqual(shell_observations[0]["path"], "bin/tool")
        self.assertEqual(
            shell_observations[0]["source_id"],
            "bin/tool#call:2:nix-build",
        )
        self.assertEqual(shell_observations[0]["name"], "nix build")
        self.assertEqual(shell_observations[0]["target"], "tool:nix")
        self.assertEqual(shell_observations[0]["start_line"], 2)
        self.assertEqual(shell_observations[0]["end_line"], 2)
        self.assertEqual(shell_observations[0]["confidence"], "heuristic")
        self.assertNotIn(".git/config", paths)
        self.assertEqual(metadata_by_path["bin/tool"]["language"], "shell")
        self.assertEqual(metadata_by_path["bin/tool"]["role"], "entrypoint")
        self.assertTrue(metadata_by_path["bin/tool"]["executable"])
        self.assertEqual(metadata_by_path["flake.nix"]["language"], "nix")
        self.assertEqual(metadata_by_path["flake.nix"]["role"], "config")
        self.assertEqual(metadata_by_path["generated/report.json"]["role"], "generated")
        self.assertEqual(metadata_by_path["src/main/python/app.py"]["role"], "source")
        self.assertEqual(
            metadata_by_path["src/test/unit/python/app.unit.test.py"]["role"],
            "test",
        )

    def test_discover_command_emits_nix_static_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "nix-fixture"
            self.write_fixture(fixture / "bin" / "tool", "#!/usr/bin/env bash\n")
            self.write_fixture(
                fixture / "bin" / "to-string-tool",
                "#!/usr/bin/env bash\n",
            )
            self.write_fixture(
                fixture / "bin" / "literal-tool",
                "#!/usr/bin/env bash\n",
            )
            self.write_fixture(fixture / "modules" / "base.nix", "{ ... }: {}\n")
            self.write_fixture(fixture / "pkgs" / "default.nix", "{ stdenv }: {}\n")
            self.write_fixture(fixture / "README.md", "Fixture docs\n")
            self.write_fixture(fixture / "config" / "settings.json", "{}\n")
            self.write_fixture(
                fixture / "flake.nix",
                (
                    "{ self }: {\n"
                    "  imports = [ (import ./modules/base.nix) ./README.md ];\n"
                    "  apps.aarch64-darwin.tool = {\n"
                    "    program = \"${self}/bin/tool\";\n"
                    "  };\n"
                    "  apps.aarch64-darwin.toStringTool = {\n"
                    "    program = toString ./bin/to-string-tool;\n"
                    "  };\n"
                    "  apps.aarch64-darwin.literalTool = {\n"
                    "    program = ./bin/literal-tool;\n"
                    "  };\n"
                    "  apps.aarch64-darwin.noProgram = { type = \"app\"; };\n"
                    "  packages.aarch64-darwin.default = ./pkgs/default.nix;\n"
                    "  devShells.aarch64-darwin.default = {};\n"
                    "  checks.aarch64-darwin.unit = {};\n"
                    "  root = ./.;\n"
                    "  scripts = [ ./config/settings.json ];\n"
                    "}\n"
                ),
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        nix_observations = [
            observation
            for observation in observations
            if observation["kind"].startswith("nix.")
        ]
        kinds_and_targets = [
            (observation["kind"], observation["target"])
            for observation in nix_observations
        ]
        app = next(
            observation
            for observation in nix_observations
            if observation["kind"] == "nix.app"
            and observation["name"] == "tool"
        )
        apps_by_name = {
            observation["name"]: observation
            for observation in nix_observations
            if observation["kind"] == "nix.app"
        }
        path_refs = [
            observation
            for observation in nix_observations
            if observation["kind"] == "nix.path_ref"
        ]

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn(("nix.import", "file:modules/base.nix"), kinds_and_targets)
        self.assertIn(
            (
                "nix.app",
                "nix.app:nix-fixture:aarch64-darwin:tool",
            ),
            kinds_and_targets,
        )
        self.assertIn(
            (
                "nix.package",
                "nix.package:nix-fixture:aarch64-darwin:default",
            ),
            kinds_and_targets,
        )
        self.assertIn(
            (
                "nix.devShell",
                "nix.devShell:nix-fixture:aarch64-darwin:default",
            ),
            kinds_and_targets,
        )
        self.assertIn(
            (
                "nix.check",
                "nix.check:nix-fixture:aarch64-darwin:unit",
            ),
            kinds_and_targets,
        )
        self.assertEqual(app["metadata"]["program_path"], "bin/tool")
        self.assertEqual(app["metadata"]["program_resolution"], "local")
        self.assertEqual(
            apps_by_name["toStringTool"]["metadata"]["program_path"],
            "bin/to-string-tool",
        )
        self.assertEqual(
            apps_by_name["literalTool"]["metadata"]["program_path"],
            "bin/literal-tool",
        )
        self.assertNotIn("program", apps_by_name["noProgram"]["metadata"])
        self.assertEqual(
            [observation["target"] for observation in path_refs],
            [
                "file:README.md",
                "file:pkgs/default.nix",
                "file:.",
                "file:config/settings.json",
            ],
        )

    def test_discover_command_emits_nix_unknown_and_dynamic_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "nix-fixture"
            self.write_fixture(
                fixture / "flake.nix",
                (
                    "{ self, name, pkgs }: {\n"
                    "  escaped = import ../outside.nix;\n"
                    "  apps.aarch64-darwin.dynamic = {\n"
                    "    program = \"${self}/${name}\";\n"
                    "  };\n"
                    "  apps.aarch64-darwin.external = {\n"
                    "    program = pkgs.hello + \"/bin/hello\";\n"
                    "  };\n"
                    "  apps.aarch64-darwin.bad = {\n"
                    "    program = ../outside/tool;\n"
                    "  };\n"
                    "  apps.aarch64-darwin.selfBad = {\n"
                    "    program = \"${self}/../outside/tool\";\n"
                    "  };\n"
                    "  scripts = [ ../outside/resource ];\n"
                    "}\n"
                ),
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        nix_observations = [
            observation
            for observation in observations
            if observation["kind"].startswith("nix.")
        ]
        imports = [
            observation
            for observation in nix_observations
            if observation["kind"] == "nix.import"
        ]
        apps_by_name = {
            observation["name"]: observation
            for observation in nix_observations
            if observation["kind"] == "nix.app"
        }
        path_refs = [
            observation
            for observation in nix_observations
            if observation["kind"] == "nix.path_ref"
        ]

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            imports[0]["target"],
            "unknown:file:repo-escaping-nix-import",
        )
        self.assertEqual(
            apps_by_name["dynamic"]["metadata"]["program_resolution"],
            "dynamic",
        )
        self.assertEqual(
            apps_by_name["dynamic"]["metadata"]["dynamic_reason"],
            "nix-app-program-interpolation",
        )
        self.assertEqual(
            apps_by_name["external"]["metadata"]["program_resolution"],
            "external",
        )
        self.assertEqual(
            apps_by_name["bad"]["metadata"]["program_target"],
            "unknown:file:repo-escaping-nix-app-program",
        )
        self.assertEqual(
            apps_by_name["bad"]["metadata"]["program_resolution"],
            "unknown",
        )
        self.assertEqual(
            apps_by_name["selfBad"]["metadata"]["program_target"],
            "unknown:file:repo-escaping-nix-app-program",
        )
        self.assertEqual(
            apps_by_name["selfBad"]["metadata"]["program_resolution"],
            "unknown",
        )
        self.assertEqual(
            [observation["target"] for observation in path_refs],
            [
                "unknown:file:repo-escaping-nix-path-ref",
                "unknown:file:repo-escaping-nix-path-ref",
                "unknown:file:repo-escaping-nix-path-ref",
            ],
        )

    def test_discover_command_emits_markdown_documentation_observations(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "markdown_docs_basic"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        observations = [json.loads(line) for line in stdout.splitlines()]
        kinds = {item["kind"] for item in observations}
        links = [item for item in observations if item["kind"] == "markdown.link"]
        frontmatter = next(
            item
            for item in observations
            if item["kind"] == "markdown.frontmatter" and item["path"] == "README.md"
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(
            {
                "markdown.document",
                "markdown.heading",
                "markdown.link",
                "markdown.frontmatter",
                "markdown.code_fence",
                "markdown.adr_metadata",
                "markdown.skill_metadata",
            }.issubset(kinds)
        )
        self.assertIn("api_key", frontmatter["metadata"]["redacted_keys"])
        self.assertIn(
            "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
            {item.get("target") for item in links},
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.get("target") for item in links},
        )

    def test_discover_command_emits_json_family_config_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "mcp" / "config.json",
                json.dumps(
                    {
                        "projects": {
                            "repo-map": {
                                "root_path": "./projects/repo-map",
                                "pg_database": "repomap_repo_map",
                            }
                        },
                        "mcp_servers": {
                            "repomap": {
                                "command": "repomap-kg",
                                "args": ["python3", "-m", "repomap_kg"],
                                "program": "repomap-kg --serve",
                                "executable": "bin/tool",
                                "env": {
                                    "REPOMAP_MCP_CONFIG": "$REPOMAP_MCP_CONFIG",
                                    "TOKEN": "cfg1-sensitive-token",
                                },
                                "docs_url": "https://example.com/docs",
                                "mailto": "mailto:dev@example.com",
                                "path": "../../outside.json",
                                "absolute_path": "/tmp/external.json",
                                "template_path": "${PROJECT_ROOT}/config.json",
                            }
                        },
                        "items": [{"name": "alpha", "path": "./alpha.json"}],
                        "array": ["one", "two"],
                        "api_key": "cfg1-sensitive-api-key",
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
            )
            self.write_fixture(
                fixture / "events.jsonl",
                "\n".join(
                    [
                        json.dumps({"event": "load", "command": "repomap-kg"}),
                        json.dumps(["array", "record"]),
                        "{bad json",
                    ]
                )
                + "\n",
            )
            self.write_fixture(
                fixture / "settings.jsonc",
                """
{
  // line comment
  /* block comment */
  "command": "repomap-kg",
  "docs_url": "mailto:dev@example.com",
  "note": "keep // inside string",
  "block_note": "keep /* inside string */",
  "quoted": "escaped \\" quote",
  "nested": {
    "path": "./mcp/config.json",
  },
}
""",
            )
            self.write_fixture(
                fixture / "broken.jsonc",
                "{ /* unterminated block comment\n",
            )
            self.write_fixture(fixture / "broken.json", "{bad json}\n")

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.jsonl_record",
                "config.parse_error",
            }.issubset(kinds)
        )
        self.assertNotIn("cfg1-sensitive-token", stdout)
        self.assertNotIn("cfg1-sensitive-api-key", stdout)

        references = [
            observation
            for observation in observations
            if observation["kind"] == "config.reference"
        ]
        reference_targets = {observation["target"] for observation in references}
        self.assertTrue(
            {
                "tool:repomap-kg",
                "tool:python3",
                "dynamic:tool:config-command-fragment",
                "unknown:tool:unknown-config-command",
                "env:REPOMAP_MCP_CONFIG",
                "env:TOKEN",
                "external.url:https%3A%2F%2Fexample.com%2Fdocs",
                "external.url:mailto%3Adev%40example.com",
                "file:mcp/config.json",
                "unknown:file:repo-escaping-config-reference",
                "external:file:absolute-config-reference",
                "dynamic:file:config-reference-expanded-from-variable",
            }.issubset(reference_targets)
        )

        path_metadata = {
            observation["metadata"]["pointer"]: observation["metadata"]
            for observation in observations
            if observation["kind"] == "config.path"
            and observation["path"] == "mcp/config.json"
        }
        self.assertTrue(path_metadata["/api_key"]["redacted"])
        self.assertEqual(path_metadata["/array"]["array_policy"], "summary-only")

        parse_errors = [
            observation
            for observation in observations
            if observation["kind"] == "config.parse_error"
        ]
        self.assertTrue(
            {
                "malformed-json",
                "malformed-jsonl-line",
                "unsupported-jsonc-construct",
            }.issubset(
                {error["metadata"]["error_kind"] for error in parse_errors}
            )
        )
        jsonl_records = [
            observation
            for observation in observations
            if observation["kind"] == "config.jsonl_record"
        ]
        self.assertEqual(
            [record["metadata"]["top_level_type"] for record in jsonl_records],
            ["object", "array"],
        )

    def test_discover_command_emits_toml_config_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "config_toml_basic"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
            }.issubset(kinds)
        )
        self.assertNotIn("cfg2-sensitive-api-key", stdout)
        self.assertNotIn("cfg2-sensitive-token", stdout)

        toml_files = [
            observation
            for observation in observations
            if observation["kind"] == "file"
            and observation["metadata"]["language"] == "toml"
        ]
        self.assertEqual(
            [observation["path"] for observation in toml_files],
            ["bad.toml", "mcp/config.toml"],
        )

        references = [
            observation
            for observation in observations
            if observation["kind"] == "config.reference"
        ]
        reference_targets = {observation["target"] for observation in references}
        self.assertTrue(
            {
                "tool:python3",
                "tool:repomap-kg",
                "env:PYTHONPATH",
                "env:TOKEN",
                "file:src/main/python",
                "file:docs/guide.md",
                "file:projects/repo-map",
                "file:bin/tool",
                "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            }.issubset(reference_targets)
        )
        self.assertNotIn("tool:-m", reference_targets)

        path_metadata = {
            observation["metadata"]["pointer"]: observation["metadata"]
            for observation in observations
            if observation["kind"] == "config.path"
            and observation["path"] == "mcp/config.toml"
        }
        self.assertTrue(path_metadata["/mcp_servers/repomap/api_key"]["redacted"])
        self.assertEqual(path_metadata["/tools"]["array_policy"], "stable-member-key")
        self.assertEqual(path_metadata["/anonymous"]["array_policy"], "summary-only")
        self.assertIn("/tools/repomap/command", path_metadata)
        self.assertIn("/tools/helper/command", path_metadata)
        self.assertNotIn("/tools/0/command", path_metadata)
        self.assertNotIn("/anonymous/0/command", path_metadata)

        parse_errors = [
            observation
            for observation in observations
            if observation["kind"] == "config.parse_error"
        ]
        self.assertIn(
            "malformed-toml",
            {error["metadata"]["error_kind"] for error in parse_errors},
        )

    def test_discover_command_emits_css_static_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "css_static_basic"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        self.assertNotIn("fixture-secret-token", stdout)
        self.assertNotIn("PHNlY3JldD4=", stdout)
        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertTrue(
            {
                "css.document",
                "css.rule",
                "css.selector",
                "css.declaration",
                "css.custom_property",
                "css.reference",
                "css.parse_error",
            }.issubset(kinds)
        )
        css_files = [
            observation
            for observation in observations
            if observation["kind"] == "file"
            and observation["metadata"]["language"] == "css"
        ]
        self.assertEqual(
            [observation["path"] for observation in css_files],
            [
                "tools/test/report/static/report.css",
                "tools/test/report/static/reset.css",
            ],
        )
        selector_classes = {
            class_name
            for observation in observations
            if observation["kind"] == "css.selector"
            for class_name in observation["metadata"]["classes"]
        }
        self.assertTrue(
            {
                "status-badge",
                "report-header",
                "report-badges",
                "tree-grid",
                "test-grid",
                "path-cell",
                "metric-cell",
                "status-cell",
                "row",
            }.issubset(selector_classes)
        )
        reference_targets = {
            observation["target"]
            for observation in observations
            if observation["kind"] == "css.reference"
        }
        self.assertIn("file:tools/test/assets/panel.svg", reference_targets)
        self.assertIn("unknown:file:repo-escaping-css-reference", reference_targets)
        self.assertIn("dynamic:file:css-url-dynamic", reference_targets)

    def test_discover_command_emits_ruby_static_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "ruby_basic"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        profiles = {
            observation["metadata"].get("profile")
            for observation in observations
            if observation["kind"] == "ruby.file"
        }
        targets = {
            observation.get("target")
            for observation in observations
            if observation["kind"] == "ruby.reference"
        }

        self.assertTrue(
            {
                "ruby.file",
                "ruby.module",
                "ruby.class",
                "ruby.method",
                "ruby.singleton_method",
                "ruby.constant",
                "ruby.require",
                "ruby.route",
                "ruby.test_case",
                "ruby.test_method",
                "ruby.gem_dependency",
                "ruby.vagrant_config",
                "ruby.parse_error",
            }.issubset(kinds)
        )
        self.assertTrue(
            {
                "generic_ruby",
                "minitest",
                "vagrantfile",
                "sinatra",
                "hanami",
                "rake",
                "gemfile",
                "gemspec",
            }.issubset(profiles)
        )
        self.assertIn("file:lib/example/service.rb", targets)
        self.assertIn("external:ruby-gem:rack", targets)
        self.assertIn("external:vagrant-box:example%2Fubuntu", targets)
        self.assertNotIn("echo setup", stdout)

    def test_discover_command_emits_js_static_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "js_basic"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        profiles = {
            observation["metadata"].get("profile")
            for observation in observations
            if observation["kind"] == "js.file"
        }
        targets = {
            observation.get("target")
            for observation in observations
            if observation["kind"] == "js.reference"
        }

        self.assertTrue(
            {
                "js.file",
                "js.module",
                "js.import",
                "js.export",
                "js.function",
                "js.class",
                "js.method",
                "js.variable",
                "js.component",
                "js.hook",
                "js.route",
                "js.test_suite",
                "js.test_case",
                "js.test_expectation",
                "js.reference",
                "js.parse_error",
            }.issubset(kinds)
        )
        self.assertTrue(
            {
                "generic_javascript",
                "generic_typescript",
                "jest",
                "react",
                "angular",
                "vue",
                "frontend_asset",
                "test_report_asset",
            }.issubset(profiles)
        )
        self.assertIn("file:src/util.mjs", targets)
        self.assertIn("external:js-package:react", targets)
        self.assertIn("file:public/report.js.map", targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.invalid%2Fapi%3Ftoken%3DREDACTED",
            targets,
        )
        self.assertNotIn("placeholder", stdout)
        self.assertNotIn("Bearer ${apiToken}", stdout)

    def test_discover_command_emits_feed_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "feed_static_basic"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        self.assertNotIn("fixture-feed-secret", stdout)
        self.assertNotIn("throw new Error", stdout)
        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertTrue(
            {
                "feed.document",
                "feed.channel",
                "feed.item",
                "feed.link",
                "feed.enclosure",
                "feed.author",
                "feed.category",
                "feed.content",
                "feed.parse_error",
            }.issubset(kinds)
        )

        feed_formats = {
            observation["metadata"].get("feed_format")
            for observation in observations
            if observation["kind"] == "feed.document"
        }
        self.assertEqual(feed_formats, {"rss", "atom", "json-feed"})
        feed_files = [
            observation
            for observation in observations
            if observation["kind"] == "file"
            and observation["metadata"]["language"] in ("json", "xml")
        ]
        self.assertEqual(
            [observation["path"] for observation in feed_files],
            [
                "atom.xml",
                "feed.json",
                "malformed-rss.xml",
                "rss.xml",
                "secret-feed.xml",
            ],
        )
        link_targets = {
            observation["target"]
            for observation in observations
            if observation["kind"] in ("feed.link", "feed.enclosure")
        }
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1",
            link_targets,
        )
        self.assertIn("file:media/rss-audio.mp3", link_targets)
        parse_errors = [
            observation
            for observation in observations
            if observation["kind"] == "feed.parse_error"
        ]
        self.assertIn(
            "xml-parse-error",
            {error["metadata"]["error_kind"] for error in parse_errors},
        )

    def test_discover_command_emits_java_spring_maven_xml_observations(self):
        fixture = (
            REPO_ROOT
            / "src"
            / "test"
            / "fixtures"
            / "discovery"
            / "xml_java_spring_maven_basic"
        )

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        self.assertNotIn("xml2-fixture-maven-secret", stdout)
        self.assertNotIn("xml2-fixture-spring-secret", stdout)
        self.assertNotIn("file:///etc/passwd", stdout)
        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertTrue(
            {
                "file",
                "xml.document",
                "xml.element",
                "xml.attribute",
                "xml.reference",
                "xml.parse_error",
            }.issubset(kinds)
        )
        roles = {
            observation["metadata"].get("document_role")
            for observation in observations
            if observation["kind"] == "xml.document"
        }
        self.assertTrue({"maven-pom", "spring-config"}.issubset(roles))
        targets = {
            observation.get("target")
            for observation in observations
            if observation["kind"] == "xml.reference"
        }
        self.assertIn(
            "external.url:https%3A%2F%2Fmaven.apache.org%2Fxsd%2Fmaven-4.0.0.xsd",
            targets,
        )
        self.assertIn("file:src/main/resources/config/service.properties", targets)
        self.assertIn("env:DB_PASSWORD", targets)
        self.assertIn(
            "dynamic:xml.property-placeholder:spring-maven-property",
            targets,
        )
        parse_errors = [
            observation
            for observation in observations
            if observation["kind"] == "xml.parse_error"
        ]
        self.assertEqual(
            parse_errors[0]["metadata"]["error_kind"],
            "unsafe-xml-construct",
        )

    def test_discover_command_emits_codex_mcp_config_dogfood_observations(self):
        fixture = (
            REPO_ROOT
            / "src"
            / "test"
            / "fixtures"
            / "discovery"
            / "config_codex_mcp_dogfood"
        )

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        for secret in (
            "cfg3-json-secret-token",
            "cfg3-json-secret-api-key",
            "cfg3-toml-secret-refresh-token",
            "cfg3-toml-secret-api-key",
            "cfg3-jsonl-secret-token",
            "cfg3-jsonc-secret-password",
        ):
            self.assertNotIn(secret, stdout)

        observations = [
            json.loads(line)
            for line in stdout.splitlines()
            if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.jsonl_record",
                "config.parse_error",
            }.issubset(kinds)
        )
        file_languages = {
            observation["path"]: observation["metadata"]["language"]
            for observation in observations
            if observation["kind"] == "file"
        }
        self.assertEqual(
            file_languages,
            {
                "codex/config.toml": "toml",
                "editor/settings.jsonc": "jsonc",
                "logs/events.jsonl": "jsonl",
                "mcp/repo-map/config.json": "json",
            },
        )

        document_targets = {
            observation["target"]
            for observation in observations
            if observation["kind"] == "config.document"
        }
        self.assertEqual(
            document_targets,
            {
                "config.document:file%3Acodex%2Fconfig.toml",
                "config.document:file%3Aeditor%2Fsettings.jsonc",
                "config.document:file%3Alogs%2Fevents.jsonl",
                "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
            },
        )

        reference_targets = {
            observation["target"]
            for observation in observations
            if observation["kind"] == "config.reference"
        }
        self.assertTrue(
            {
                "tool:repomap-kg",
                "tool:python3",
                "dynamic:tool:config-command-fragment",
                "env:REPOMAP_MCP_CONFIG",
                "env:CODEX_HOME",
                "env:TOKEN",
                "env:API_KEY",
                "env:PASSWORD",
                "file:codex/config.toml",
                "file:mcp/repo-map/config.json",
                "file:src/main/python",
                "file:projects/repo-map",
                "file:bin/repomap",
                "external.url:https%3A%2F%2Fexample.com%2Frepo-map",
                "external.url:https%3A%2F%2Fexample.com%2Feditor",
                "external.url:https%3A%2F%2Fexample.com%2Flog",
                "external.url:mailto%3Aops%40example.com",
                "external:file:absolute-config-reference",
                "unknown:file:repo-escaping-config-reference",
            }.issubset(reference_targets)
        )

        path_metadata = {
            (observation["path"], observation["metadata"]["pointer"]): observation[
                "metadata"
            ]
            for observation in observations
            if observation["kind"] == "config.path"
        }
        self.assertTrue(
            path_metadata[
                ("mcp/repo-map/config.json", "/api_key")
            ]["redacted"]
        )
        self.assertTrue(
            path_metadata[
                ("codex/config.toml", "/profiles/default/refresh_token")
            ]["redacted"]
        )
        self.assertTrue(
            path_metadata[
                ("editor/settings.jsonc", "/env/PASSWORD")
            ]["redacted"]
        )
        self.assertEqual(
            path_metadata[("codex/config.toml", "/tools")]["array_policy"],
            "stable-member-key",
        )

        parse_errors = [
            observation
            for observation in observations
            if observation["kind"] == "config.parse_error"
        ]
        self.assertEqual(
            [(error["path"], error["metadata"]["error_kind"]) for error in parse_errors],
            [("logs/events.jsonl", "malformed-jsonl-line")],
        )
        jsonl_records = [
            observation
            for observation in observations
            if observation["kind"] == "config.jsonl_record"
        ]
        self.assertEqual(len(jsonl_records), 3)

    def test_discover_command_handles_markdown_ambiguity_without_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "docs" / "guide.md",
                (
                    "---\n"
                    "title: \"Guide\"\n"
                    "published: true\n"
                    "draft: false\n"
                    "tags:\n"
                    "  - docs\n"
                    "not yaml\n"
                    "secret_token: hidden\n"
                    "---\n"
                    "# Guide\n"
                    "See [same](#guide), [missing](missing.md), "
                    "[template]({{ site.url }}/docs), and [bad](bad%zz).\n"
                    "```sh\n"
                    "echo '[not](executed.md)'\n"
                ),
            )
            self.write_fixture(
                fixture / "docs" / "skills" / "path-only" / "SKILL.md",
                "# Path Only\n",
            )
            self.write_fixture(
                fixture / "docs" / "adr" / "0010-filename-title.md",
                "No heading here.\n",
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        guide_items = [item for item in observations if item["path"] == "docs/guide.md"]
        frontmatter = next(item for item in guide_items if item["kind"] == "markdown.frontmatter")
        fence = next(item for item in guide_items if item["kind"] == "markdown.code_fence")
        link_targets = {
            item.get("target") for item in guide_items if item["kind"] == "markdown.link"
        }
        skill = next(item for item in observations if item["kind"] == "markdown.skill_metadata")
        adr = next(item for item in observations if item["kind"] == "markdown.adr_metadata")

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(frontmatter["metadata"]["parse_status"], "partial")
        self.assertIn("secret_token", frontmatter["metadata"]["redacted_keys"])
        self.assertFalse(fence["metadata"]["closed"])
        self.assertIn("doc.section:file%3Adocs%2Fguide.md:guide", link_targets)
        self.assertIn("unknown:doc.page:missing-markdown-link-target", link_targets)
        self.assertIn("dynamic:external.url:markdown-link-template", link_targets)
        self.assertIn("unknown:external.url:malformed-markdown-link", link_targets)
        self.assertEqual(skill["target"], "doc.skill:path-only")
        self.assertEqual(adr["metadata"]["metadata_source"], "filename")

    def test_nix_repo_path_resolution_contract(self):
        self.assertEqual(
            resolve_repo_path("flake.nix", "${self}/bin/tool"),
            "bin/tool",
        )
        self.assertEqual(
            resolve_repo_path("modules/base.nix", "../lib/shared.nix"),
            "lib/shared.nix",
        )
        self.assertIsNone(resolve_repo_path("flake.nix", "pkgs.hello"))

    def test_discover_command_emits_shell_source_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "bin" / "tool",
                "#!/usr/bin/env bash\nsource ../lib/common.sh\n",
            )
            self.write_fixture(fixture / "lib" / "common.sh", "echo common\n")

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        sources = [
            observation
            for observation in observations
            if observation["kind"] == "shell.source"
        ]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["path"], "bin/tool")
        self.assertEqual(sources[0]["source_id"], "bin/tool#source:2:lib-common-sh")
        self.assertEqual(sources[0]["name"], "../lib/common.sh")
        self.assertEqual(sources[0]["target"], "file:lib/common.sh")
        self.assertEqual(sources[0]["start_line"], 2)
        self.assertEqual(sources[0]["metadata"]["resolved_path"], "lib/common.sh")

    def test_discover_command_skips_dynamic_shell_source_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "bin" / "tool",
                (
                    "#!/usr/bin/env bash\n"
                    "FOO=bar\n"
                    "source \"$DYNAMIC\"\n"
                    "if true; then\n"
                    "  echo ok\n"
                    "fi\n"
                ),
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        sources = [
            observation
            for observation in observations
            if observation["kind"] == "shell.source"
        ]
        commands = [
            observation
            for observation in observations
            if observation["kind"] == "shell.command"
        ]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(sources, [])
        self.assertEqual([command["name"] for command in commands], ["echo ok"])

    def test_discover_command_emits_shell_env_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "bin" / "tool",
                (
                    "#!/usr/bin/env bash\n"
                    'PATH="$PWD/bin:$PATH"\n'
                    "FOO=bar nix build .#checks\n"
                    'echo "$PATH"\n'
                ),
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        env = [
            observation
            for observation in observations
            if observation["kind"] == "shell.env"
        ]
        commands = [
            observation
            for observation in observations
            if observation["kind"] == "shell.command"
        ]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [
                (observation["metadata"]["operation"], observation["name"])
                for observation in env
            ],
            [
                ("write", "PATH"),
                ("read", "PWD"),
                ("read", "PATH"),
                ("write", "FOO"),
                ("read", "PATH"),
            ],
        )
        self.assertEqual(env[0]["source_id"], "bin/tool#env-write:2:path")
        self.assertEqual(env[0]["target"], "env:PATH")
        self.assertEqual(env[0]["metadata"]["scope"], "shell")
        self.assertEqual(env[3]["metadata"]["scope"], "command")
        self.assertEqual(
            [command["name"] for command in commands],
            ["nix build", "echo $PATH"],
        )

    def test_discover_command_handles_ambiguous_shell_env_and_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "bin" / "tool",
                (
                    "#!/usr/bin/env bash\n"
                    "source\n"
                    "source ../../outside.sh\n"
                    'source "$DYNAMIC"\n'
                    'echo "$PATH:${PATH:-/bin}:$PATH"\n'
                    "nix --version\n"
                    'echo "unterminated\n'
                ),
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        sources = [
            observation
            for observation in observations
            if observation["kind"] == "shell.source"
        ]
        env = [
            observation
            for observation in observations
            if observation["kind"] == "shell.env"
        ]
        commands = [
            observation
            for observation in observations
            if observation["kind"] == "shell.command"
        ]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(sources, [])
        self.assertEqual(
            [
                (observation["metadata"]["operation"], observation["name"])
                for observation in env
            ],
            [("read", "DYNAMIC"), ("read", "PATH")],
        )
        self.assertEqual(
            [command["name"] for command in commands],
            [
                "echo $PATH:${PATH:-/bin}:$PATH",
                "nix",
            ],
        )

    def test_discover_command_emits_shell_host_mutation_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "scripts" / "maintain.sh",
                (
                    "#!/usr/bin/env bash\n"
                    "brew install postgresql\n"
                    "nix profile install nixpkgs#ripgrep\n"
                    "sudo launchctl bootout system/com.example.agent\n"
                    "darwin-rebuild switch --flake ~/.flakes/nix-darwin\n"
                    "sudo rm -rf /Library/Caches/example\n"
                    "mv build/tool /usr/local/bin/tool\n"
                    "cp scripts/tool ~/.local/bin/tool\n"
                    "rm build/output\n"
                    "cp /etc/hosts ./hosts.copy\n"
                    "nix build .#checks\n"
                ),
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        mutations = [
            observation
            for observation in observations
            if observation["kind"] == "shell.host_mutation"
        ]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [
                (
                    observation["name"],
                    observation["target"],
                    observation["metadata"]["privileged"],
                )
                for observation in mutations
            ],
            [
                ("brew install", "host:package-management", False),
                ("nix profile install", "host:package-management", False),
                ("launchctl bootout", "host:service-management", True),
                ("darwin-rebuild switch", "host:system-activation", False),
                ("rm", "host:filesystem-mutation", True),
                ("mv", "host:filesystem-mutation", False),
                ("cp", "host:filesystem-mutation", False),
            ],
        )
        self.assertEqual(
            mutations[2]["metadata"]["effective_argv"],
            ["launchctl", "bootout", "system/com.example.agent"],
        )
        self.assertEqual(
            mutations[4]["metadata"]["effective_argv"],
            ["rm", "-rf", "/Library/Caches/example"],
        )

    def test_discover_command_applies_project_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            profile_path = Path(tmpdir) / "repomap-profile.toml"
            self.write_fixture(fixture / "ops" / "ship", "#!/usr/bin/env bash\n")
            self.write_fixture(
                fixture / "scripts" / "repair.sh",
                "#!/usr/bin/env bash\n",
            )
            self.write_fixture(fixture / "out" / "manifest.json", "{}\n")
            self.write_fixture(fixture / "README.md", "# Fixture\n")
            profile_path.write_text(
                """
command_dirs = ["ops"]
script_dirs = ["scripts"]
generated_dirs = ["out"]

[role_overrides]
"README.md" = "config"

[confidence_overrides]
"README.md" = "manual"
"""
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--profile", str(profile_path), "--jsonl"
            )

        observations = [json.loads(line) for line in stdout.splitlines()]
        file_observations = [
            observation for observation in observations if observation["kind"] == "file"
        ]
        by_path = {observation["path"]: observation for observation in file_observations}
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(by_path["ops/ship"]["metadata"]["role"], "entrypoint")
        self.assertEqual(by_path["scripts/repair.sh"]["metadata"]["role"], "script")
        self.assertEqual(by_path["out/manifest.json"]["metadata"]["role"], "generated")
        self.assertTrue(by_path["out/manifest.json"]["metadata"]["generated"])
        self.assertEqual(by_path["README.md"]["metadata"]["role"], "config")
        self.assertEqual(by_path["README.md"]["confidence"], "manual")

    def test_files_command_prints_filtered_table_from_discovery_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            self.write_fixture(fixture / "README.md", "# Fixture\n")
            self.write_fixture(
                fixture / "src" / "main" / "python" / "app.py",
                "print('ok')\n",
            )
            self.write_fixture(fixture / "generated" / "report.json", "{}\n")

            discover_exit, discover_stdout, discover_stderr = (
                self.run_module_entrypoint("discover", str(fixture), "--jsonl")
            )
            raw_jsonl.write_text(discover_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "files", str(raw_jsonl), "--role", "source", "--language", "python"
            )

        self.assertEqual(discover_exit, 0, discover_stderr)
        self.assertEqual(exit_code, 0)
        self.assertIn("path", stdout)
        self.assertIn("src/main/python/app.py", stdout)
        self.assertNotIn("README.md", stdout)
        self.assertNotIn("generated/report.json", stdout)
        self.assertEqual(stderr, "")

    def test_files_command_accepts_stdin_jsonl_as_json(self):
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

        result = self.run_cli(
            "files", "-", "--json", input_text=observation.to_json_line()
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload[0]["path"], "README.md")
        self.assertEqual(payload[0]["confidence"], "manual")
        self.assertEqual(result.stderr, "")

    def test_entrypoints_command_prints_profile_command_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            profile_path = Path(tmpdir) / "repomap-profile.toml"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            self.write_fixture(fixture / "ops" / "ship", "#!/usr/bin/env bash\n")
            self.write_fixture(
                fixture / "scripts" / "repair.sh",
                "#!/usr/bin/env bash\n",
            )
            profile_path.write_text(
                """
command_dirs = ["ops"]
script_dirs = ["scripts"]
"""
            )

            discover_args = (
                "discover",
                str(fixture),
                "--profile",
                str(profile_path),
                "--jsonl",
            )
            discover_exit, discover_stdout, discover_stderr = (
                self.run_module_entrypoint(*discover_args)
            )
            raw_jsonl.write_text(discover_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "entrypoints", str(raw_jsonl)
            )

        self.assertEqual(discover_exit, 0, discover_stderr)
        self.assertEqual(exit_code, 0)
        self.assertIn("ops/ship", stdout)
        self.assertIn("entrypoint", stdout)
        self.assertNotIn("scripts/repair.sh", stdout)
        self.assertEqual(stderr, "")

    def test_entrypoints_command_accepts_stdin_jsonl_as_json(self):
        observation = RawObservation(
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

        result = self.run_cli(
            "entrypoints", "-", "--json", input_text=observation.to_json_line()
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload[0]["path"], "bin/tool")
        self.assertEqual(payload[0]["confidence"], "manual")
        self.assertEqual(result.stderr, "")

    def test_host_mutators_command_prints_discovered_mutations_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            self.write_fixture(
                fixture / "scripts" / "maintain.sh",
                (
                    "#!/usr/bin/env bash\n"
                    "brew install postgresql\n"
                    "sudo launchctl bootout system/com.example.agent\n"
                    "nix build .#checks\n"
                ),
            )

            discover_exit, discover_stdout, discover_stderr = (
                self.run_module_entrypoint("discover", str(fixture), "--jsonl")
            )
            raw_jsonl.write_text(discover_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "host-mutators",
                str(raw_jsonl),
                "--category",
                "service-management",
                "--tool",
                "launchctl",
                "--json",
            )

        payload = json.loads(stdout)
        self.assertEqual(discover_exit, 0, discover_stderr)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [(record["name"], record["target"]) for record in payload],
            [
                ("launchctl bootout", "host:service-management"),
            ],
        )
        self.assertEqual(payload[0]["effective_argv"], [
            "launchctl",
            "bootout",
            "system/com.example.agent",
        ])

    def test_host_mutators_summary_command_prints_discovered_counts_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            self.write_fixture(
                fixture / "scripts" / "maintain.sh",
                (
                    "#!/usr/bin/env bash\n"
                    "brew install postgresql\n"
                    "sudo launchctl bootout system/com.example.agent\n"
                    "nix build .#checks\n"
                ),
            )

            discover_exit, discover_stdout, discover_stderr = (
                self.run_module_entrypoint("discover", str(fixture), "--jsonl")
            )
            raw_jsonl.write_text(discover_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "host-mutators-summary",
                str(raw_jsonl),
                "--json",
            )

        payload = json.loads(stdout)
        self.assertEqual(discover_exit, 0, discover_stderr)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload, [
            {
                "category": "package-management",
                "count": 1,
                "privileged_count": 0,
                "tool": "brew",
            },
            {
                "category": "service-management",
                "count": 1,
                "privileged_count": 1,
                "tool": "launchctl",
            },
        ])

    def test_host_mutators_summary_command_prints_raw_jsonl_as_table(self):
        observations = [
            RawObservation(
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
            ),
            RawObservation(
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
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl(observations, raw_jsonl)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "host-mutators-summary",
                str(raw_jsonl),
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("category", stdout)
        self.assertIn("privileged_count", stdout)
        self.assertIn("package-management", stdout)
        self.assertIn("service-management", stdout)
        self.assertIn("launchctl", stdout)
        self.assertEqual(stderr, "")

    def test_host_mutators_command_prints_raw_jsonl_as_table(self):
        observation = RawObservation(
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
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([observation], raw_jsonl)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "host-mutators",
                str(raw_jsonl),
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("path", stdout)
        self.assertIn("category", stdout)
        self.assertIn("package-management", stdout)
        self.assertIn("brew install", stdout)
        self.assertEqual(stderr, "")

    def run_module_entrypoint(self, *args):
        original_argv = sys.argv[:]
        stdout = io.StringIO()
        stderr = io.StringIO()

        try:
            sys.argv = ["repomap-kg", *args]
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_module("repomap_kg", run_name="__main__")
        finally:
            sys.argv = original_argv

        return caught.exception.code, stdout.getvalue(), stderr.getvalue()

    def write_fixture(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


if __name__ == "__main__":
    unittest.main()
