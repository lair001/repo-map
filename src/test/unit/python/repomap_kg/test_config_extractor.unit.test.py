import json
import unittest

from repomap_kg.config_extractor import (
    extract_config_file_observations,
    json_pointer,
)


class ConfigExtractorUnitTests(unittest.TestCase):
    def test_extracts_json_paths_references_and_redacts_secret_values(self):
        observations = extract_config_file_observations(
            "mcp/repo-map/config.json",
            json.dumps(
                {
                    "projects": {
                        "repo-map": {
                            "root_path": "projects/repo-map",
                            "pg_database": "repomap_repo_map",
                        }
                    },
                    "mcp_servers": {
                        "repomap": {
                            "command": "repomap-kg",
                            "args": ["repomap-kg", "mcp", "serve"],
                            "url": "https://example.com/docs",
                            "env": {
                                "REPOMAP_MCP_CONFIG": "$REPOMAP_MCP_CONFIG",
                                "TOKEN": "secret-value",
                            },
                        }
                    },
                    "api_key": "top-secret",
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        references = [item for item in observations if item.kind == "config.reference"]
        paths = [item for item in observations if item.kind == "config.path"]

        self.assertNotIn("top-secret", payload)
        self.assertNotIn("secret-value", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "json")
        self.assertIn(
            "/projects/repo-map/pg_database",
            {item.metadata["pointer"] for item in paths},
        )
        self.assertIn(
            "/api_key",
            {item.metadata["pointer"] for item in paths},
        )
        api_key = next(item for item in paths if item.metadata["pointer"] == "/api_key")
        self.assertTrue(api_key.metadata["redacted"])
        self.assertEqual(api_key.metadata["redaction_reason"], "secret-prone-key")
        self.assertNotIn("value_summary", api_key.metadata)
        self.assertIn(
            (
                "/projects/repo-map/root_path",
                "file:projects/repo-map",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/command",
                "tool:repomap-kg",
                "tool",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/env/REPOMAP_MCP_CONFIG",
                "env:REPOMAP_MCP_CONFIG",
                "env",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )

    def test_pointer_escaping_and_array_policy_avoid_numeric_identity(self):
        observations = extract_config_file_observations(
            "settings.json",
            json.dumps(
                {
                    "a/b": {"tilde~key": 3},
                    "items": ["one", "two"],
                    "anonymous": [{"command": "do-not-index-by-array-position"}],
                }
            ),
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointers = {item.metadata["pointer"] for item in paths}
        array_path = next(item for item in paths if item.metadata["pointer"] == "/items")

        self.assertEqual(json_pointer(("a/b", "tilde~key")), "/a~1b/tilde~0key")
        self.assertIn("/a~1b/tilde~0key", pointers)
        self.assertIn("/items", pointers)
        self.assertEqual(array_path.metadata["value_type"], "array")
        self.assertEqual(array_path.metadata["array_policy"], "summary-only")
        self.assertNotIn("/items/0", pointers)
        self.assertNotIn("/anonymous/0/command", pointers)

    def test_json_parse_error_emits_raw_error_without_document_paths(self):
        observations = extract_config_file_observations(
            "broken.json",
            '{"ok": true,,}',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].confidence, "unknown")
        self.assertEqual(observations[0].metadata["format"], "json")
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-json")

    def test_jsonl_mixed_valid_and_malformed_lines_preserves_valid_records(self):
        observations = extract_config_file_observations(
            "events.jsonl",
            '{"event": "start", "token": "secret-value"}\n'
            "\n"
            '{"event": \n'
            '{"event": "stop", "path": "./logs/out.json"}\n',
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        records = [item for item in observations if item.kind == "config.jsonl_record"]
        errors = [item for item in observations if item.kind == "config.parse_error"]
        references = [item for item in observations if item.kind == "config.reference"]

        self.assertNotIn("secret-value", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "jsonl")
        self.assertEqual([item.metadata["record_index"] for item in records], [0, 1])
        self.assertEqual([item.start_line for item in records], [1, 4])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].metadata["error_kind"], "malformed-jsonl-line")
        self.assertEqual(errors[0].start_line, 3)
        self.assertIn("file:logs/out.json", {item.target for item in references})

    def test_jsonc_comments_and_trailing_commas_are_normalized_conservatively(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            (
                "{\n"
                "  // comment outside a string\n"
                "  \"program\": \"repomap-kg\",\n"
                "  \"nested\": {\n"
                "    \"url\": \"mailto:dev@example.com\", /* block comment */\n"
                "  },\n"
                "}\n"
            ),
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].confidence, "heuristic")
        self.assertIn("tool:repomap-kg", {item.target for item in references})
        self.assertIn("external.url:mailto%3Adev%40example.com", {item.target for item in references})

    def test_jsonc_unterminated_block_comment_emits_parse_error(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "ok": true /* unterminated\n',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].metadata["format"], "jsonc")
        self.assertEqual(
            observations[0].metadata["error_kind"],
            "unsupported-jsonc-construct",
        )

    def test_jsonc_malformed_after_normalization_emits_parse_error(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "ok": }',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-jsonc")
        self.assertEqual(observations[0].metadata["parser"], "jsonc-conservative")

    def test_jsonc_unterminated_string_emits_conservative_parse_error(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "text": "unterminated }',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(
            observations[0].metadata["error_kind"],
            "unsupported-jsonc-construct",
        )

    def test_jsonc_preserves_comment_markers_inside_strings_and_array_trailing_commas(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "text": "not // a comment", "items": [1, 2,], }\n',
        )

        paths = {item.metadata["pointer"]: item for item in observations if item.kind == "config.path"}

        self.assertEqual(paths["/text"].metadata["value_summary"], "not // a comment")
        self.assertEqual(paths["/items"].metadata["value_summaries"], [1, 2])

    def test_absolute_and_parent_relative_file_references_are_conservative(self):
        observations = extract_config_file_observations(
            "configs/settings.json",
            json.dumps(
                {
                    "parent_path": "../README.md",
                    "absolute_path": "/var/db/config.json",
                }
            ),
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertIn("file:README.md", {item.target for item in references})
        self.assertIn(
            "external:file:absolute-config-reference",
            {item.target for item in references},
        )

    def test_jsonl_scalar_record_keeps_safe_summary_without_record_key(self):
        observations = extract_config_file_observations(
            "events.jsonl",
            '"hello"\n42\n',
        )

        records = [item for item in observations if item.kind == "config.jsonl_record"]

        self.assertEqual([item.metadata["value_summary"] for item in records], ["hello", 42])
        self.assertEqual([item.metadata["top_level_type"] for item in records], ["string", "number"])
        self.assertNotIn("config.record", json.dumps([item.to_dict() for item in observations]))

    def test_unknown_command_and_root_scalar_document_are_recorded_honestly(self):
        command_observations = extract_config_file_observations(
            "settings.json",
            '{"command": "bin/tool"}',
        )
        scalar_observations = extract_config_file_observations(
            "value.json",
            "true",
        )

        references = [
            item for item in command_observations if item.kind == "config.reference"
        ]

        self.assertEqual(
            references[0].target,
            "unknown:tool:unknown-config-command",
        )
        self.assertEqual(scalar_observations[0].kind, "config.document")
        self.assertEqual(scalar_observations[0].metadata["top_level_type"], "boolean")

    def test_long_string_summary_and_root_array_document_are_compact(self):
        long_text = "x" * 130
        long_observations = extract_config_file_observations(
            "settings.json",
            json.dumps({"description": long_text}),
        )
        array_observations = extract_config_file_observations(
            "array.json",
            '[{"name": "one"}]',
        )

        description = next(
            item
            for item in long_observations
            if item.kind == "config.path" and item.metadata["pointer"] == "/description"
        )

        self.assertEqual(description.metadata["value_summary"], "<string:130>")
        self.assertEqual(array_observations[0].kind, "config.document")
        self.assertEqual(array_observations[0].metadata["top_level_type"], "array")

    def test_dynamic_and_unknown_references_prefer_placeholders(self):
        observations = extract_config_file_observations(
            "settings.json",
            json.dumps(
                {
                    "outside_path": "../outside.json",
                    "nested_escape_path": "folder/../../outside.json",
                    "dynamic_path": "${HOME}/tool",
                    "command": "echo hello",
                    "env": {"${NAME}": "value"},
                }
            ),
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertIn("unknown:file:repo-escaping-config-reference", {item.target for item in references})
        self.assertEqual(
            sum(
                1
                for item in references
                if item.target == "unknown:file:repo-escaping-config-reference"
            ),
            2,
        )
        self.assertIn("dynamic:file:config-reference-expanded-from-variable", {item.target for item in references})
        self.assertIn("dynamic:tool:config-command-fragment", {item.target for item in references})
        self.assertIn("dynamic:env:dynamic-config-env-name", {item.target for item in references})

    def test_toml_document_paths_references_and_redaction(self):
        observations = extract_config_file_observations(
            "config.toml",
            """
[mcp_servers.repomap]
command = "python3"
args = ["-m", "repomap_kg.mcp_server"]
cwd = "src/main/python"
docs_url = "https://example.com/docs"
api_key = "toml-secret-api-key"
dotted.path.value = "docs/guide.md"

[mcp_servers.repomap.env]
PYTHONPATH = "src/main/python"
TOKEN = "toml-secret-token"

[projects.repo-map]
root_path = "projects/repo-map"
pg_database = "repomap_repo_map"
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("toml-secret-api-key", payload)
        self.assertNotIn("toml-secret-token", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "toml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-tomllib")
        self.assertIn("/mcp_servers/repomap", pointer_by_path)
        self.assertIn("/mcp_servers/repomap/command", pointer_by_path)
        self.assertIn("/mcp_servers/repomap/dotted/path/value", pointer_by_path)
        self.assertIn("/projects/repo-map/root_path", pointer_by_path)
        self.assertTrue(pointer_by_path["/mcp_servers/repomap/api_key"].metadata["redacted"])
        self.assertNotIn(
            "value_summary",
            pointer_by_path["/mcp_servers/repomap/api_key"].metadata,
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/command",
                "tool:python3",
                "tool",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/cwd",
                "file:src/main/python",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/env/PYTHONPATH",
                "env:PYTHONPATH",
                "env",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn("env:TOKEN", {item.target for item in references})
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )
        self.assertIn("file:docs/guide.md", {item.target for item in references})

    def test_toml_arrays_of_tables_use_stable_member_keys_without_indexes(self):
        observations = extract_config_file_observations(
            "tools.toml",
            """
plugins = ["python", "ruby"]

[[tools]]
name = "repomap"
command = "repomap-kg"
path = "bin/tool"

[[tools]]
id = "helper"
command = "python3"

[[anonymous]]
command = "do-not-index-with-number"
""",
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointers = {item.metadata["pointer"] for item in paths}
        references = [item for item in observations if item.kind == "config.reference"]
        plugins = next(item for item in paths if item.metadata["pointer"] == "/plugins")
        tools = next(item for item in paths if item.metadata["pointer"] == "/tools")
        anonymous = next(item for item in paths if item.metadata["pointer"] == "/anonymous")

        self.assertEqual(plugins.metadata["array_policy"], "summary-only")
        self.assertEqual(plugins.metadata["value_summaries"], ["python", "ruby"])
        self.assertEqual(tools.metadata["array_policy"], "stable-member-key")
        self.assertEqual(anonymous.metadata["array_policy"], "summary-only")
        self.assertIn("/tools/repomap", pointers)
        self.assertIn("/tools/repomap/command", pointers)
        self.assertIn("/tools/helper/command", pointers)
        self.assertNotIn("/tools/0/command", pointers)
        self.assertNotIn("/anonymous/0/command", pointers)
        self.assertIn("tool:repomap-kg", {item.target for item in references})
        self.assertIn("tool:python3", {item.target for item in references})
        self.assertIn("file:bin/tool", {item.target for item in references})

    def test_toml_malformed_parse_error_is_raw_only(self):
        observations = extract_config_file_observations(
            "bad.toml",
            "[mcp_servers.repomap]\ncommand =\n",
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].confidence, "unknown")
        self.assertEqual(observations[0].metadata["format"], "toml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-tomllib")
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-toml")

    def test_toml_dynamic_and_unknown_references_use_placeholders(self):
        observations = extract_config_file_observations(
            "settings.toml",
            """
outside_path = "../outside.toml"
absolute_path = "/var/db/config.toml"
dynamic_path = "${PROJECT_ROOT}/config.toml"
program = "echo hello"

[env]
"${NAME}" = "value"
""",
        )

        references = [item for item in observations if item.kind == "config.reference"]
        self.assertIn("unknown:file:repo-escaping-config-reference", {item.target for item in references})
        self.assertIn("external:file:absolute-config-reference", {item.target for item in references})
        self.assertIn("dynamic:file:config-reference-expanded-from-variable", {item.target for item in references})
        self.assertIn("dynamic:tool:config-command-fragment", {item.target for item in references})
        self.assertIn("dynamic:env:dynamic-config-env-name", {item.target for item in references})


if __name__ == "__main__":
    unittest.main()
