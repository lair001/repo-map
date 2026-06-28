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
    def run_cli(self, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SOURCE_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "repomap_kg", *args],
            check=False,
            cwd=REPO_ROOT,
            env=env,
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

    def test_discover_command_emits_file_observations_for_fixture_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "bin" / "tool",
                "#!/usr/bin/env bash\necho ok\n",
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
        paths = [observation["path"] for observation in observations]
        metadata_by_path = {
            observation["path"]: observation["metadata"] for observation in observations
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
        self.assertTrue(
            all(observation["kind"] == "file" for observation in observations)
        )
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
