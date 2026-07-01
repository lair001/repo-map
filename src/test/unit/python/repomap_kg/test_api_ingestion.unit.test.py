import json
import tempfile
import unittest
from pathlib import Path

from repomap_kg.api_ingestion import (
    ApiPolicyError,
    FixtureApiTransport,
    acquire_api_source,
    build_api_plan_from_config,
    load_api_source_config,
)
from repomap_kg.storage import LoadSummary


class ApiIngestionUnitTests(unittest.TestCase):
    def test_api_config_requires_policy_consent_credential_limits_and_get_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid = self.write_api_fixture(root)
            blocked = self.write_api_fixture(root, policy_status="blocked")
            missing_consent = self.write_api_fixture(root, include_consent=False)
            invalid_credential = self.write_api_fixture(
                root,
                credentials_ref="plain-token-name",
            )
            mutation = self.write_api_fixture(root, method="POST")
            provider_class = self.write_api_fixture(
                root,
                api_source_class="api.email_provider",
            )

            config = load_api_source_config(valid)
            with self.assertRaisesRegex(ApiPolicyError, "policy status"):
                load_api_source_config(blocked)
            with self.assertRaisesRegex(ApiPolicyError, "consent"):
                load_api_source_config(missing_consent)
            with self.assertRaisesRegex(ApiPolicyError, "credentials_ref"):
                load_api_source_config(invalid_credential)
            with self.assertRaisesRegex(ApiPolicyError, "GET"):
                load_api_source_config(mutation)
            with self.assertRaisesRegex(ApiPolicyError, "api_source_class"):
                load_api_source_config(provider_class)

        self.assertEqual(config.source_id, "fixture-readonly-api")
        self.assertEqual(config.source_type, "api.rest")
        self.assertEqual(config.api_source_class, "api.custom_documented_api")
        self.assertEqual(config.credentials_ref, "local_secret_ref:fixture-api-token")
        self.assertEqual(config.endpoints[0].name, "items")
        self.assertEqual(config.endpoints[0].downstream_route, "config")

    def test_api_plan_is_deterministic_and_does_not_call_transport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_api_fixture(Path(tmpdir))

            first = build_api_plan_from_config(config_path)
            second = build_api_plan_from_config(config_path)

        self.assertEqual(first.api_run_id, second.api_run_id)
        self.assertEqual(first.api_manifest_id, second.api_manifest_id)
        self.assertEqual(first.request_count, 1)
        self.assertEqual(first.requests[0].endpoint_name, "items")
        self.assertEqual(first.requests[0].method, "GET")
        self.assertEqual(first.requests[0].path, "/v1/items")
        payload = json.dumps(first.to_jsonable(), sort_keys=True)
        self.assertIn('"no_network": true', payload)
        self.assertIn('"no_mutation": true', payload)
        self.assertNotIn("fixture-api-token", payload)
        self.assertNotIn(str(config_path.parent), payload)

    def test_api_acquire_uses_fixture_transport_writes_artifacts_and_routes_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_api_fixture(root)
            calls = []
            summary = acquire_api_source(
                config_path,
                repository_name="fixture",
                root_path=root,
                psql_args=("-d", "postgres"),
                psql_command="/bin/psql",
                loader=self.fake_loader(calls),
                transport=FixtureApiTransport(),
            )
            manifest_path = summary.output_path / "manifest.json"
            redacted_path = summary.output_path / "redacted-responses.jsonl"
            artifact_path = summary.output_path / "artifacts" / "items.json"
            manifest_exists = manifest_path.is_file()
            redacted_exists = redacted_path.is_file()
            artifact_exists = artifact_path.is_file()

        self.assertEqual(summary.source_id, "fixture-readonly-api")
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.responses, 1)
        self.assertGreater(summary.observations, 0)
        self.assertEqual(summary.load_summary.repository_id, 7)
        self.assertTrue(manifest_exists)
        self.assertTrue(redacted_exists)
        self.assertTrue(artifact_exists)
        self.assertEqual(calls[0]["root_path"], str(root.resolve()))
        observation_payload = json.dumps(
            [observation.to_dict() for observation in calls[0]["observations"]],
            sort_keys=True,
        )
        self.assertIn('"api_run_id"', observation_payload)
        self.assertIn('"endpoint_name": "items"', observation_payload)
        self.assertIn('"api_retention_policy": "local_user_controlled"', observation_payload)
        self.assertIn("config.document", observation_payload)
        self.assertNotIn("fixture-secret-value", observation_payload)
        self.assertNotIn("fixture-api-token", observation_payload)
        summary_payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"no_network": true', summary_payload)
        self.assertIn('"no_mutation": true', summary_payload)
        self.assertNotIn(str(root), summary_payload)
        self.assertNotIn("fixture-secret-value", summary_payload)

    def test_api_acquire_enforces_response_limits_before_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_api_fixture(root, max_bytes_per_run=10)

            with self.assertRaisesRegex(ApiPolicyError, "max_bytes_per_run"):
                acquire_api_source(
                    config_path,
                    repository_name="fixture",
                    root_path=root,
                    psql_args=("-d", "postgres"),
                    loader=self.fake_loader([]),
                    transport=FixtureApiTransport(),
                )

        self.assertFalse((root / ".repomap" / "api-runs").exists())

    def write_api_fixture(
        self,
        root: Path,
        *,
        policy_status: str = "allowed_with_limits",
        include_consent: bool = True,
        credentials_ref: str = "local_secret_ref:fixture-api-token",
        method: str = "GET",
        api_source_class: str = "api.custom_documented_api",
        max_bytes_per_run: int = 1048576,
    ) -> Path:
        fixture = root / f"api-{len(list(root.glob('api-*')))}"
        fixture.mkdir()
        responses = fixture / "responses"
        responses.mkdir()
        (responses / "items.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "item-1",
                            "name": "Fixture item",
                            "secret": "fixture-secret-value",
                        }
                    ]
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        consent_block = (
            "\n[consent]\n"
            'consent_ref = "local_consent_ref:fixture-readonly-api-2026-07"\n'
            'scope_description = "Read-only fixture API metadata export"\n'
            'authorized_operations = ["read"]\n'
            'authorized_data_classes = ["metadata"]\n'
            "revoked = false\n"
            "mutation_allowed = false\n"
            if include_consent
            else ""
        )
        config_path = fixture / "api-source.toml"
        config_path.write_text(
            "[source]\n"
            'source_id = "fixture-readonly-api"\n'
            'source_type = "api.rest"\n'
            f'api_source_class = "{api_source_class}"\n'
            'provider_name = "Fixture Provider"\n'
            'provider_product = "Fixture API"\n'
            f'policy_status = "{policy_status}"\n'
            "read_only = true\n"
            "mutation_allowed = false\n"
            "\n[credentials]\n"
            f'credentials_ref = "{credentials_ref}"\n'
            f"{consent_block}"
            "\n[limits]\n"
            "max_requests_per_run = 10\n"
            "max_requests_per_minute = 10\n"
            "max_concurrent_requests = 1\n"
            f"max_bytes_per_run = {max_bytes_per_run}\n"
            "max_items_per_run = 100\n"
            "max_retries = 0\n"
            "\n[retention]\n"
            'policy = "local_user_controlled"\n'
            'raw_response_retention = "minimized"\n'
            'redacted_response_retention = "retain"\n'
            "\n[redaction]\n"
            'profile = "strict"\n'
            'sensitivity = "private"\n'
            "\n[[endpoints]]\n"
            'name = "items"\n'
            f'method = "{method}"\n'
            'path = "/v1/items"\n'
            'purpose = "Export fixture item metadata"\n'
            'response_type = "application/json"\n'
            "max_page_size = 100\n"
            'pagination = "none"\n'
            'downstream_route = "config"\n'
            'fixture_response_path = "responses/items.json"\n',
            encoding="utf-8",
        )
        return config_path

    def fake_loader(self, calls: list[dict[str, object]]):
        def load(psql_args, observations, **kwargs):
            calls.append(
                {
                    "psql_args": tuple(psql_args),
                    "observations": tuple(observations),
                    **kwargs,
                }
            )
            return LoadSummary(repository_id=7, run_id=11, files=1)

        return load
