import io
import json
import os
import runpy
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
