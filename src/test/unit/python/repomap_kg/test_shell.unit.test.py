import unittest

from repomap_kg.shell import (
    extract_shell_command_observations,
    extract_shell_observations,
)


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

    def test_extract_shell_observations_emits_sourced_file_edges(self):
        observations = extract_shell_observations(
            "bin/tool",
            (
                "#!/usr/bin/env bash\n"
                "source ../lib/common.sh\n"
                ". ./helpers.sh\n"
                "source \"$DYNAMIC\"\n"
                "nix build .#checks\n"
            ),
        )

        sources = [
            observation
            for observation in observations
            if observation.kind == "shell.source"
        ]
        commands = [
            observation
            for observation in observations
            if observation.kind == "shell.command"
        ]
        self.assertEqual([source.target for source in sources], [
            "file:lib/common.sh",
            "file:bin/helpers.sh",
        ])
        self.assertEqual(sources[0].source_id, "bin/tool#source:2:lib-common-sh")
        self.assertEqual(sources[0].name, "../lib/common.sh")
        self.assertEqual(sources[0].start_line, 2)
        self.assertEqual(sources[0].confidence, "heuristic")
        self.assertEqual(sources[0].metadata["resolved_path"], "lib/common.sh")
        self.assertEqual([command.name for command in commands], ["nix build"])


if __name__ == "__main__":
    unittest.main()
