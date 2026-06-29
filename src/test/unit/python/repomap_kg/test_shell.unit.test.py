import unittest

from repomap_kg.shell import extract_shell_command_observations


class ShellExtractorUnitTests(unittest.TestCase):
    def test_extract_shell_command_observations_preserves_tool_call_evidence(self):
        observations = extract_shell_command_observations(
            "bin/tool",
            "#!/usr/bin/env bash\n\nnix build .#checks\n",
        )

        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.kind, "shell.command")
        self.assertEqual(observation.source_id, "bin/tool#call:3:nix-build")
        self.assertEqual(observation.path, "bin/tool")
        self.assertEqual(observation.start_line, 3)
        self.assertEqual(observation.end_line, 3)
        self.assertEqual(observation.name, "nix build")
        self.assertEqual(observation.target, "tool:nix")
        self.assertEqual(observation.confidence, "heuristic")
        self.assertEqual(observation.extractor, "repo-shell")
        self.assertEqual(observation.metadata["argv"], ["nix", "build", ".#checks"])

    def test_extract_shell_command_observations_skips_non_command_lines(self):
        observations = extract_shell_command_observations(
            "scripts/check.sh",
            (
                "#!/usr/bin/env bash\n"
                "# comment\n"
                "if true; then\n"
                "  echo ok\n"
                "fi\n"
                "FOO=bar\n"
            ),
        )

        self.assertEqual([observation.name for observation in observations], ["echo ok"])
        self.assertEqual(observations[0].source_id, "scripts/check.sh#call:4:echo-ok")


if __name__ == "__main__":
    unittest.main()
