import unittest

from repomap_kg.nix import extract_nix_file_observations, resolve_repo_path


class NixExtractorUnitTests(unittest.TestCase):
    def test_extracts_static_imports_from_import_calls_and_imports_list(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ ... }:\n"
                "let\n"
                "  base = import ./nix/base.nix;\n"
                "in {\n"
                "  imports = [ ./modules/one.nix ./modules/two.nix ];\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual([item.target for item in imports], [
            "file:nix/base.nix",
            "file:modules/one.nix",
            "file:modules/two.nix",
        ])
        self.assertEqual([item.start_line for item in imports], [3, 5, 5])
        self.assertTrue(all(item.confidence == "heuristic" for item in imports))
        self.assertEqual(imports[0].metadata["syntax"], "import")
        self.assertEqual(imports[1].metadata["syntax"], "imports-list")

    def test_extracts_static_imports_from_multiline_imports_list(self):
        observations = extract_nix_file_observations(
            "nix/modules/default.nix",
            (
                "{ ... }: {\n"
                "  imports = [\n"
                "    ./one.nix\n"
                "    ../shared/two.nix\n"
                "  ];\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual([item.target for item in imports], [
            "file:nix/modules/one.nix",
            "file:nix/shared/two.nix",
        ])
        self.assertEqual([item.start_line for item in imports], [3, 4])

    def test_imports_list_ignores_non_nix_paths(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            "{ ... }: { imports = [ ./module.nix ./README.md ]; }\n",
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual([item.target for item in imports], ["file:module.nix"])

    def test_repo_escaping_import_uses_unknown_placeholder(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            "{ ... }: import ../outside.nix\n",
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual(imports[0].target, "unknown:file:repo-escaping-nix-import")
        self.assertEqual(imports[0].metadata["resolution"], "unknown")
        self.assertEqual(
            imports[0].metadata["dynamic_reason"],
            "repo-escaping-nix-import",
        )

    def test_extracts_flake_output_attr_paths(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.tool = { type = \"app\"; };\n"
                "  packages.aarch64-darwin.default = self.packages.${system}.tool;\n"
                "  devShells.aarch64-darwin.default = {};\n"
                "  checks.aarch64-darwin.unit = {};\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        output_observations = [
            item
            for item in observations
            if item.kind in {"nix.app", "nix.package", "nix.devShell", "nix.check"}
        ]

        self.assertEqual([item.kind for item in output_observations], [
            "nix.app",
            "nix.package",
            "nix.devShell",
            "nix.check",
        ])
        self.assertEqual(
            [item.target for item in output_observations],
            [
                "nix.app:fixture:aarch64-darwin:tool",
                "nix.package:fixture:aarch64-darwin:default",
                "nix.devShell:fixture:aarch64-darwin:default",
                "nix.check:fixture:aarch64-darwin:unit",
            ],
        )
        self.assertEqual(output_observations[0].metadata["attr_path"], "apps.aarch64-darwin.tool")
        self.assertEqual(output_observations[1].metadata["output_kind"], "package")

    def test_extracts_app_program_static_repo_paths(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.selfPath = {\n"
                "    type = \"app\";\n"
                "    program = \"${self}/bin/self-tool\";\n"
                "  };\n"
                "  apps.aarch64-darwin.toStringPath = {\n"
                "    program = toString ./bin/to-string-tool;\n"
                "  };\n"
                "  apps.aarch64-darwin.literalPath = {\n"
                "    program = ./bin/literal-tool;\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app_observations = [item for item in observations if item.kind == "nix.app"]

        self.assertEqual(
            [(item.name, item.metadata.get("program_path")) for item in app_observations],
            [
                ("selfPath", "bin/self-tool"),
                ("toStringPath", "bin/to-string-tool"),
                ("literalPath", "bin/literal-tool"),
            ],
        )
        self.assertEqual(
            [item.metadata.get("program_resolution") for item in app_observations],
            ["local", "local", "local"],
        )

    def test_dynamic_app_program_is_recorded_without_fabricated_path(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self, name }: {\n"
                "  apps.aarch64-darwin.dynamic = {\n"
                "    program = \"${self}/${name}\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertEqual(app.target, "nix.app:fixture:aarch64-darwin:dynamic")
        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "dynamic")
        self.assertEqual(app.metadata["dynamic_reason"], "nix-app-program-interpolation")

    def test_external_app_program_is_recorded_without_repo_program_path(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ pkgs }: {\n"
                "  apps.aarch64-darwin.external = {\n"
                "    program = \"${pkgs.hello}/bin/hello\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "dynamic")

    def test_expression_app_program_is_recorded_as_external(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ pkgs }: {\n"
                "  apps.aarch64-darwin.external = {\n"
                "    program = pkgs.hello + \"/bin/hello\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "external")

    def test_repo_escaping_literal_app_program_records_unknown_target(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.bad = {\n"
                "    program = ../outside/tool;\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "unknown")
        self.assertEqual(
            app.metadata["program_target"],
            "unknown:file:repo-escaping-nix-app-program",
        )

    def test_repo_escaping_self_app_program_records_unknown_target(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.bad = {\n"
                "    program = \"${self}/../outside/tool\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "unknown")
        self.assertEqual(
            app.metadata["program_target"],
            "unknown:file:repo-escaping-nix-app-program",
        )

    def test_app_without_program_has_no_program_metadata(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.noProgram = { type = \"app\"; };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program", app.metadata)
        self.assertNotIn("program_path", app.metadata)

    def test_non_flake_nix_file_does_not_emit_flake_outputs(self):
        observations = extract_nix_file_observations(
            "nix/module.nix",
            "apps.aarch64-darwin.tool = { program = ./bin/tool; };\n",
            flake_ref="fixture",
        )

        self.assertEqual([item.kind for item in observations], ["nix.path_ref"])

    def test_extracts_raw_only_path_references(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  packages.aarch64-darwin.default = ./pkgs/default.nix;\n"
                "  scripts = [ ./bin/tool ./config/settings.json ];\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        path_refs = [item for item in observations if item.kind == "nix.path_ref"]

        self.assertEqual([item.target for item in path_refs], [
            "file:pkgs/default.nix",
            "file:bin/tool",
            "file:config/settings.json",
        ])
        self.assertEqual([item.metadata["resolution"] for item in path_refs], [
            "local",
            "local",
            "local",
        ])

    def test_repo_escaping_path_reference_uses_unknown_placeholder(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            "{ self }: { scripts = [ ../outside/tool ]; }\n",
            flake_ref="fixture",
        )

        path_ref = next(item for item in observations if item.kind == "nix.path_ref")

        self.assertEqual(path_ref.target, "unknown:file:repo-escaping-nix-path-ref")
        self.assertEqual(path_ref.metadata["resolution"], "unknown")

    def test_resolve_repo_path_normalizes_relative_and_self_paths(self):
        self.assertEqual(
            resolve_repo_path("nix/module.nix", "./child.nix"),
            "nix/child.nix",
        )
        self.assertEqual(
            resolve_repo_path("nix/module.nix", "../lib/shared.nix"),
            "lib/shared.nix",
        )
        self.assertEqual(resolve_repo_path("flake.nix", "${self}/bin/tool"), "bin/tool")
        self.assertIsNone(resolve_repo_path("flake.nix", "../outside.nix"))
        self.assertIsNone(resolve_repo_path("flake.nix", "pkgs.hello"))


if __name__ == "__main__":
    unittest.main()
