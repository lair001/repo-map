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
            ],
        )
        self.assertEqual(
            mutations[2]["metadata"]["effective_argv"],
            ["launchctl", "bootout", "system/com.example.agent"],
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
        by_path = {observation["path"]: observation for observation in observations}
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
