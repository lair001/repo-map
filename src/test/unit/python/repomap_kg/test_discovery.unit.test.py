import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from repomap_kg.discovery import (
    classify_path,
    discover_observations,
    discover_repository,
    extract_css_file_observations_from_file,
    extract_feed_file_observations_from_file,
)


FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "discovery"

ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
)


def odf_package(content_xml: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("content.xml", content_xml.encode("utf-8"))
    return buffer.getvalue()


def odt_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body><office:text><text:h text:outline-level="1">Overview</text:h></office:text></office:body>
</office:document-content>
"""


def ods_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Budget">
        <table:table-row><table:table-cell><text:p>amount</text:p></table:table-cell></table:table-row>
        <table:table-row><table:table-cell><text:p>12</text:p></table:table-cell></table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""


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

    def test_discover_observations_includes_markdown_documentation_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "README.md",
                (
                    "# Fixture\n"
                    "\n"
                    "See [ADR](docs/adr/0008-markdown-documentation-graph-model.md#decision).\n"
                ),
            )
            self.write(
                root / "docs" / "adr" / "0008-markdown-documentation-graph-model.md",
                "# ADR 0008: Markdown Documentation Graph Model\n\n## Decision\n",
            )

            observations = discover_observations(root)

        kinds = [observation.kind for observation in observations]
        self.assertIn("markdown.document", kinds)
        self.assertIn("markdown.heading", kinds)
        self.assertIn("markdown.link", kinds)
        self.assertIn("markdown.adr_metadata", kinds)
        link = next(item for item in observations if item.kind == "markdown.link")
        self.assertEqual(
            link.target,
            "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
        )
        adr = next(item for item in observations if item.kind == "markdown.adr_metadata")
        self.assertEqual(adr.target, "doc.adr:0008")

    def test_discover_observations_includes_json_family_config_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "mcp" / "repo-map" / "config.json",
                '{"command": "repomap-kg", "api_key": "secret-value"}\n',
            )
            self.write(
                root / "events.jsonl",
                '{"event": "start"}\n{"event": \n{"path": "./mcp/repo-map/config.json"}\n',
            )
            self.write(
                root / "settings.jsonc",
                '{ // comment\n "url": "https://example.com/docs", }\n',
            )

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]

        self.assertNotIn("secret-value", payload)
        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertIn("config.jsonl_record", kinds)
        self.assertIn("config.parse_error", kinds)
        self.assertIn(".jsonl", {item.path[-6:] for item in observations})
        self.assertIn(".jsonc", {item.path[-6:] for item in observations})

    def test_discover_observations_routes_eml_files_without_mbox(self):
        observations = discover_observations(FIXTURE_ROOT / "mail_basic")
        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {observation.kind for observation in observations}
        languages = {
            observation.path: observation.metadata.get("language")
            for observation in observations
            if observation.kind == "file"
        }

        self.assertEqual(languages["single-message.eml"], "eml")
        self.assertIn("email.message", kinds)
        self.assertIn("email.part", kinds)
        self.assertIn("email.attachment_stub", kinds)
        self.assertIn("email.thread_hint", kinds)
        self.assertNotIn("email.mailbox", kinds)
        self.assertNotIn("alice@example.invalid", payload)
        self.assertNotIn("fake-mail-reset-code", payload)

    def test_discover_observations_includes_yaml_config_facts(self):
        observations = discover_observations(FIXTURE_ROOT / "yaml_basic")

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {observation.kind for observation in observations}
        yaml_documents = [
            observation
            for observation in observations
            if observation.kind == "config.document"
            and observation.metadata.get("format") == "yaml"
        ]
        yaml_references = [
            observation
            for observation in observations
            if observation.kind == "config.reference"
            and observation.metadata.get("format") == "yaml"
        ]
        profiles = {
            observation.metadata.get("profile")
            for observation in yaml_documents
        }

        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertIn("config.parse_error", kinds)
        self.assertIn("github_actions", profiles)
        self.assertIn("kubernetes", profiles)
        self.assertIn("openapi", profiles)
        self.assertIn("docker_compose", profiles)
        self.assertIn("generic_yaml", profiles)
        self.assertIn(
            "external:github.action:actions%2Fcheckout%40v4",
            {observation.target for observation in yaml_references},
        )
        self.assertIn(
            "external:docker.image:example%2Fapp%3Alatest",
            {observation.target for observation in yaml_references},
        )
        self.assertNotIn("fake-actions-token", payload)
        self.assertNotIn("fake-kubernetes-password", payload)
        self.assertNotIn("fake-client-secret", payload)

    def test_discover_observations_includes_ruby_facts_for_ruby_files_and_dsls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "lib" / "example.rb",
                (
                    'require_relative "example/service"\n'
                    "module Example\n"
                    "  class Runner\n"
                    "    def call\n"
                    "    end\n"
                    "  end\n"
                    "end\n"
                ),
            )
            self.write(root / "lib" / "example" / "service.rb", "module Example\nend\n")
            self.write(root / "Gemfile", 'source "https://example.invalid"\ngem "rack"\n')
            self.write(root / "Rakefile", 'desc "Run tests"\ntask :test do\nend\n')
            self.write(root / "Vagrantfile", 'Vagrant.configure("2") do |config|\n  config.vm.box = "example/box"\nend\n')
            shebang = root / "bin" / "tool"
            self.write(shebang, "#!/usr/bin/env ruby\nrequire_relative '../lib/example'\n")
            shebang.chmod(shebang.stat().st_mode | 0o111)

            observations = discover_observations(root)

        kinds = {observation.kind for observation in observations}
        ruby_profiles = {
            observation.metadata.get("profile")
            for observation in observations
            if observation.kind == "ruby.file"
        }
        ruby_targets = {
            observation.target
            for observation in observations
            if observation.kind == "ruby.reference"
        }

        self.assertIn("ruby.file", kinds)
        self.assertIn("ruby.module", kinds)
        self.assertIn("ruby.class", kinds)
        self.assertIn("ruby.method", kinds)
        self.assertIn("ruby.gem_dependency", kinds)
        self.assertIn("ruby.vagrant_config", kinds)
        self.assertIn("generic_ruby", ruby_profiles)
        self.assertIn("gemfile", ruby_profiles)
        self.assertIn("rake", ruby_profiles)
        self.assertIn("vagrantfile", ruby_profiles)
        self.assertIn("file:lib/example/service.rb", ruby_targets)
        self.assertIn("external:ruby-gem:rack", ruby_targets)

    def test_discover_observations_reads_ruby_basic_fixture(self):
        observations = discover_observations(FIXTURE_ROOT / "ruby_basic")
        kinds = {observation.kind for observation in observations}
        ruby_profiles = {
            observation.metadata.get("profile")
            for observation in observations
            if observation.kind == "ruby.file"
        }
        ruby_targets = {
            observation.target
            for observation in observations
            if observation.kind == "ruby.reference"
        }

        self.assertIn("ruby.module", kinds)
        self.assertIn("ruby.class", kinds)
        self.assertIn("ruby.route", kinds)
        self.assertIn("ruby.test_method", kinds)
        self.assertIn("ruby.gem_dependency", kinds)
        self.assertIn("ruby.vagrant_config", kinds)
        self.assertIn("sinatra", ruby_profiles)
        self.assertIn("hanami", ruby_profiles)
        self.assertIn("minitest", ruby_profiles)
        self.assertIn("file:lib/example/service.rb", ruby_targets)
        self.assertIn("external:ruby-gem:rack", ruby_targets)
        self.assertTrue(
            any(
                observation.metadata.get("redacted")
                for observation in observations
                if observation.path == "redaction.rb"
            )
        )

    def test_discover_observations_keeps_plist_config_and_extracts_generic_xml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "chrome-policy.plist",
                """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>PolicyPath</key>
    <string>managed/policy.json</string>
  </dict>
</plist>
""",
            )
            self.write(
                root / "dangerous.plist",
                """<?xml version="1.0"?>
<!DOCTYPE plist [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<plist><dict><key>Bad</key><string>&xxe;</string></dict></plist>
""",
            )
            self.write(
                root / "generic.xml",
                """<?xml version="1.0"?>
<beans xmlns="http://www.springframework.org/schema/beans">
  <bean id="service" class="com.example.Service"/>
</beans>
""",
            )
            self.write(root / "managed" / "policy.json", "{}\n")

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        plist_file = next(
            item
            for item in observations
            if item.kind == "file" and item.path == "chrome-policy.plist"
        )
        generic_file = next(
            item
            for item in observations
            if item.kind == "file" and item.path == "generic.xml"
        )

        self.assertEqual(plist_file.metadata["language"], "plist")
        self.assertEqual(plist_file.metadata["role"], "config")
        self.assertEqual(generic_file.metadata["language"], "xml")
        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertIn("config.parse_error", kinds)
        self.assertIn("xml.document", kinds)
        self.assertIn("xml.element", kinds)
        self.assertIn("xml.attribute", kinds)
        self.assertNotIn("file:///etc/passwd", payload)

    def test_discover_observations_includes_static_html_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "site" / "index.html",
                """<!doctype html>
<html lang="en">
  <head><title>Fixture</title><link rel="stylesheet" href="assets/site.css"></head>
  <body>
    <h1 id="welcome">Welcome</h1>
    <a href="#welcome">Jump</a>
    <a href="https://example.com/docs">Docs</a>
    <script src="assets/app.js">alert("nope")</script>
    <form action="submit/login"><input name="password" value="html-secret"></form>
  </body>
</html>
""",
            )

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        html_file = next(
            item
            for item in observations
            if item.kind == "file" and item.path == "site/index.html"
        )

        self.assertEqual(html_file.metadata["language"], "html")
        self.assertIn("html.document", kinds)
        self.assertIn("html.element", kinds)
        self.assertIn("html.heading", kinds)
        self.assertIn("html.link", kinds)
        self.assertIn("html.asset", kinds)
        self.assertIn("html.form", kinds)
        self.assertNotIn("html-secret", payload)
        self.assertNotIn('alert("nope")', payload)

    def test_discover_observations_includes_static_css_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "tools" / "test" / "report" / "static" / "report.css",
                """
@import url("./reset.css");

:root {
  --surface: #111827;
  --api-token: "fixture-secret-token";
}

.report-header,
.status-badge[data-status="pass"]:hover::before,
#summary {
  background-image: url("../../assets/panel.svg");
  mask-image: url(data:image/svg+xml;base64,PHNlY3JldD4=);
}

@media (max-width: 720px) {
  .tree-grid { grid-template-columns: minmax(0, 1fr); }
}

@supports (overflow-wrap: anywhere) {
  .path-cell { overflow-wrap: anywhere; }
}

@font-face {
  font-family: "Report Mono";
  src: url("/Library/Fonts/report.woff2");
}

.broken {
  color: red;
""",
            )
            self.write(root / "tools" / "test" / "report" / "static" / "reset.css", "")

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        css_file = next(
            item
            for item in observations
            if item.kind == "file"
            and item.path == "tools/test/report/static/report.css"
        )

        self.assertEqual(css_file.metadata["language"], "css")
        self.assertIn("css.document", kinds)
        self.assertIn("css.rule", kinds)
        self.assertIn("css.selector", kinds)
        self.assertIn("css.declaration", kinds)
        self.assertIn("css.custom_property", kinds)
        self.assertIn("css.reference", kinds)
        self.assertIn("css.parse_error", kinds)
        self.assertNotIn("fixture-secret-token", payload)
        self.assertNotIn("PHNlY3JldD4=", payload)

    def test_css_fixture_discovery_emits_report_stylesheet_facts(self):
        observations = discover_observations(FIXTURE_ROOT / "css_static_basic")

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        selectors = [
            observation
            for observation in observations
            if observation.kind == "css.selector"
        ]
        references = [
            observation
            for observation in observations
            if observation.kind == "css.reference"
        ]

        self.assertIn("css.document", kinds)
        self.assertIn("css.rule", kinds)
        self.assertIn("css.selector", kinds)
        self.assertIn("css.declaration", kinds)
        self.assertIn("css.custom_property", kinds)
        self.assertIn("css.reference", kinds)
        self.assertIn("css.parse_error", kinds)
        self.assertTrue(
            any(
                "status-badge" in observation.metadata["classes"]
                for observation in selectors
            )
        )
        self.assertTrue(
            any(
                observation.target == "file:tools/test/assets/panel.svg"
                for observation in references
            )
        )
        self.assertTrue(
            any(
                observation.target == "unknown:file:repo-escaping-css-reference"
                for observation in references
            )
        )
        self.assertNotIn("fixture-secret-token", payload)
        self.assertNotIn("PHNlY3JldD4=", payload)

    def test_feed_fixture_discovery_emits_local_feed_facts(self):
        observations = discover_observations(FIXTURE_ROOT / "feed_static_basic")

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        references = [
            observation
            for observation in observations
            if observation.kind in ("feed.link", "feed.enclosure")
        ]

        self.assertIn("feed.document", kinds)
        self.assertIn("feed.channel", kinds)
        self.assertIn("feed.item", kinds)
        self.assertIn("feed.link", kinds)
        self.assertIn("feed.enclosure", kinds)
        self.assertIn("feed.author", kinds)
        self.assertIn("feed.category", kinds)
        self.assertIn("feed.content", kinds)
        self.assertIn("feed.parse_error", kinds)
        self.assertNotIn("fixture-feed-secret", payload)
        self.assertNotIn("throw new Error", payload)
        self.assertTrue(
            any(
                observation.target
                == "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1"
                for observation in references
            )
        )
        self.assertTrue(
            any(
                observation.target
                == "file:media/rss-audio.mp3"
                or observation.target == "file:feeds/media/rss-audio.mp3"
                for observation in references
            )
        )

    def test_css_file_extraction_skips_non_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            css_file = root / "bad.css"
            css_file.write_bytes(b"\xff\xfe\x00")

            observations = extract_css_file_observations_from_file(root, "bad.css")

        self.assertEqual(observations, ())

    def test_feed_file_extraction_skips_non_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            feed_file = root / "bad.xml"
            feed_file.write_bytes(b"\xff\xfe\x00")

            observations = extract_feed_file_observations_from_file(root, "bad.xml")

        self.assertEqual(observations, ())

    def test_discover_observations_routes_docs1_text_table_and_latex_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "notes.txt", "# Overview\nSee data.csv\n")
            self.write(root / "data.csv", "name,amount\nalpha,1\n")
            self.write(root / "data.tsv", "name\tactive\nalpha\ttrue\n")
            self.write(root / "paper.tex", "\\section{Intro}\n\\input{chapter}\n")
            self.write(root / "chapter.tex", "\\section{Chapter}\n")
            self.write(root / "README.md", "# Markdown\n")
            self.write(root / "ignored.pdf", "%PDF\n")

            observations = discover_observations(root)

        kinds = {observation.kind for observation in observations}
        self.assertIn("document.text_document", kinds)
        self.assertIn("document.text_section", kinds)
        self.assertIn("document.table_document", kinds)
        self.assertIn("document.table_column", kinds)
        self.assertIn("document.latex_document", kinds)
        self.assertIn("document.latex_section", kinds)
        self.assertIn("document.latex_command", kinds)
        self.assertIn("document.reference", kinds)
        self.assertIn("markdown.document", kinds)
        self.assertNotIn("document.pdf", kinds)

    def test_discover_observations_routes_docs2_odf_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_bytes(root / "notes.odt", odf_package(odt_content()))
            self.write_bytes(root / "spreadsheet.ods", odf_package(ods_content()))
            self.write_bytes(root / "template.ott", odf_package(odt_content()))
            self.write_bytes(root / "sheet-template.ots", odf_package(ods_content()))
            self.write(root / "notes.txt", "# DOCS1\n")
            self.write(root / "README.md", "# Markdown\n")
            self.write(root / "ignored.xlsx", "not-supported\n")

            observations = discover_observations(root)

        kinds = {observation.kind for observation in observations}
        self.assertIn("document.odf_document", kinds)
        self.assertIn("document.odf_text", kinds)
        self.assertIn("document.odf_sheet", kinds)
        self.assertIn("document.odf_column", kinds)
        self.assertIn("document.text_document", kinds)
        self.assertIn("markdown.document", kinds)
        self.assertNotIn("document.xlsx", kinds)

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

    def write_bytes(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


if __name__ == "__main__":
    unittest.main()
