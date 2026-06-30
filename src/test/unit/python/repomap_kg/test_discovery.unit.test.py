import tempfile
import unittest
from pathlib import Path

from repomap_kg.discovery import (
    classify_path,
    discover_observations,
    discover_repository,
)


class DiscoveryUnitTests(unittest.TestCase):
    def test_classify_path_uses_extension_directory_and_executable_bit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script = root / "bin" / "repomap-kg"
            script.parent.mkdir()
            script.write_text("#!/usr/bin/env python3\nprint('ok')\n")
            script.chmod(script.stat().st_mode | 0o111)

            file_info = classify_path(root, script)

        self.assertEqual(file_info.path, "bin/repomap-kg")
        self.assertEqual(file_info.language, "python")
        self.assertEqual(file_info.role, "entrypoint")
        self.assertTrue(file_info.executable)
        self.assertFalse(file_info.generated)
        self.assertRegex(file_info.content_hash, r"^[0-9a-f]{64}$")

    def test_discover_repository_skips_ignored_directories_and_sorts_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / ".git" / "config", "ignored")
            self.write(root / "__pycache__" / "cached.pyc", "ignored")
            self.write(root / "src" / "main" / "python" / "app.py", "print('ok')\n")
            self.write(root / "docs" / "specs" / "architecture.md", "# Arch\n")
            self.write(root / "generated" / "report.json", "{}\n")

            files = discover_repository(root)

        self.assertEqual(
            [file_info.path for file_info in files],
            [
                "docs/specs/architecture.md",
                "generated/report.json",
                "src/main/python/app.py",
            ],
        )
        self.assertEqual(files[0].role, "documentation")
        self.assertEqual(files[1].role, "generated")
        self.assertTrue(files[1].generated)
        self.assertEqual(files[2].language, "python")
        self.assertEqual(files[2].role, "source")

    def test_file_info_emits_raw_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "src" / "test" / "unit" / "python" / "app.unit.test.py"
            self.write(source, "import unittest\n")

            file_info = classify_path(root, source)
            observation = file_info.to_observation()

        self.assertEqual(observation.kind, "file")
        self.assertEqual(observation.source_id, file_info.path)
        self.assertEqual(observation.path, file_info.path)
        self.assertEqual(observation.confidence, "extracted")
        self.assertEqual(observation.extractor, "repo-discovery")
        self.assertEqual(observation.metadata["language"], "python")
        self.assertEqual(observation.metadata["role"], "test")
        self.assertEqual(observation.metadata["content_hash"], file_info.content_hash)

    def test_discover_observations_includes_shell_commands_for_shell_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script = root / "bin" / "tool"
            self.write(script, "#!/usr/bin/env bash\nnix build .#checks\n")
            script.chmod(script.stat().st_mode | 0o111)

            observations = discover_observations(root)

        self.assertEqual(
            [observation.kind for observation in observations],
            [
                "file",
                "shell.command",
            ],
        )
        command = observations[1]
        self.assertEqual(command.path, "bin/tool")
        self.assertEqual(command.name, "nix build")
        self.assertEqual(command.target, "tool:nix")
        self.assertEqual(command.start_line, 2)

    def test_discover_observations_includes_nix_facts_for_nix_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            flake = root / "flake.nix"
            self.write(
                flake,
                (
                    "{ self }: {\n"
                    "  imports = [ ./module.nix ];\n"
                    "  apps.aarch64-darwin.tool = {\n"
                    "    program = \"${self}/bin/tool\";\n"
                    "  };\n"
                    "}\n"
                ),
            )
            self.write(root / "module.nix", "{ ... }: {}\n")

            observations = discover_observations(root)

        kinds = [observation.kind for observation in observations]
        self.assertIn("nix.import", kinds)
        self.assertIn("nix.app", kinds)
        app = next(item for item in observations if item.kind == "nix.app")
        self.assertEqual(app.metadata["flake_ref"], root.name)
        self.assertEqual(app.metadata["program_path"], "bin/tool")

    def test_unknown_language_and_role_fall_back_honestly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unknown = root / "mystery" / "blob.weird"
            self.write(unknown, "data\n")

            file_info = classify_path(root, unknown)

        self.assertEqual(file_info.language, "unknown")
        self.assertEqual(file_info.role, "unknown")

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


if __name__ == "__main__":
    unittest.main()
