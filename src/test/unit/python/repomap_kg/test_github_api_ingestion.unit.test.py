import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from repomap_kg.github_api_ingestion import (
    FixtureGitHubApiTransport,
    GitHubApiPolicyError,
    GitHubTransportResponse,
    PublicGitHubRestTransport,
    acquire_github_api_source,
    build_github_api_plan_from_config,
    content_type_from_headers,
    header_mapping,
    load_github_api_source_config,
    rate_limit_headers,
    redact_github_value,
    validate_no_auth_headers,
)
from repomap_kg.storage import LoadSummary


class GitHubApiIngestionUnitTests(unittest.TestCase):
    def test_github_config_requires_policy_provider_scope_consent_and_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid = self.write_github_fixture(root)
            blocked = self.write_github_fixture(root, policy_status="blocked")
            bad_provider = self.write_github_fixture(root, provider_name="GitLab")
            bad_class = self.write_github_fixture(
                root,
                api_source_class="api.github.issues",
            )
            invalid_owner = self.write_github_fixture(root, owner="bad/owner")
            private_no_ref = self.write_github_fixture(
                root,
                repository_visibility="private",
                credential_mode="pat_readonly_ref",
                include_credentials=False,
            )
            public_pat_no_ref = self.write_github_fixture(
                root,
                credential_mode="pat_readonly_ref",
                include_credentials=False,
            )
            public_none_private = self.write_github_fixture(
                root,
                repository_visibility="private",
                credential_mode="none_public_readonly",
            )
            invalid_ref = self.write_github_fixture(
                root,
                credential_mode="pat_readonly_ref",
                credentials_ref="github-token",
            )

            config = load_github_api_source_config(valid)
            with self.assertRaisesRegex(GitHubApiPolicyError, "policy status"):
                load_github_api_source_config(blocked)
            with self.assertRaisesRegex(GitHubApiPolicyError, "provider_name"):
                load_github_api_source_config(bad_provider)
            with self.assertRaisesRegex(GitHubApiPolicyError, "api_source_class"):
                load_github_api_source_config(bad_class)
            with self.assertRaisesRegex(GitHubApiPolicyError, "owner"):
                load_github_api_source_config(invalid_owner)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials_ref"):
                load_github_api_source_config(private_no_ref)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials_ref"):
                load_github_api_source_config(public_pat_no_ref)
            with self.assertRaisesRegex(GitHubApiPolicyError, "public"):
                load_github_api_source_config(public_none_private)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials_ref"):
                load_github_api_source_config(invalid_ref)

        self.assertEqual(config.source_id, "github-public-fixture")
        self.assertEqual(config.source_type, "api.rest")
        self.assertEqual(config.api_source_class, "api.github.repository")
        self.assertEqual(config.provider_name, "GitHub")
        self.assertEqual(config.provider_product, "GitHub REST API")
        self.assertEqual(config.owner, "fixture-owner")
        self.assertEqual(config.repository, "fixture-repo")
        self.assertEqual(config.repository_visibility, "public")
        self.assertEqual(config.credential_mode, "none_public_readonly")
        self.assertIsNone(config.credentials_ref)
        self.assertEqual([endpoint.name for endpoint in config.endpoints], ["repository"])

    def test_github_config_rejects_endpoint_escape_mutation_and_unsupported_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            non_get = self.write_github_fixture(root, method="POST")
            scheme_path = self.write_github_fixture(
                root,
                endpoint_path="https://api.github.com/repos/{owner}/{repo}",
            )
            wrong_scope = self.write_github_fixture(
                root,
                endpoint_path="/repos/other-owner/{repo}",
            )
            non_allowlisted = self.write_github_fixture(
                root,
                endpoint_path="/repos/{owner}/{repo}/contents/README.md",
            )
            pagination = self.write_github_fixture(root, pagination="page")
            downstream = self.write_github_fixture(root, downstream_route="bulk")
            fixture_escape = self.write_github_fixture(
                root,
                fixture_response_path="../repository.json",
            )

            with self.assertRaisesRegex(GitHubApiPolicyError, "GET"):
                load_github_api_source_config(non_get)
            with self.assertRaisesRegex(GitHubApiPolicyError, "relative API path"):
                load_github_api_source_config(scheme_path)
            with self.assertRaisesRegex(GitHubApiPolicyError, "owner/repository"):
                load_github_api_source_config(wrong_scope)
            with self.assertRaisesRegex(GitHubApiPolicyError, "allowlisted"):
                load_github_api_source_config(non_allowlisted)
            with self.assertRaisesRegex(GitHubApiPolicyError, "pagination"):
                load_github_api_source_config(pagination)
            with self.assertRaisesRegex(GitHubApiPolicyError, "downstream_route"):
                load_github_api_source_config(downstream)
            with self.assertRaisesRegex(GitHubApiPolicyError, "fixture_response_path"):
                load_github_api_source_config(fixture_escape)

    def test_github_plan_is_deterministic_and_does_not_call_transport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_github_fixture(
                Path(tmpdir),
                endpoint_names=("repository", "issues", "pulls"),
            )

            first = build_github_api_plan_from_config(config_path)
            second = build_github_api_plan_from_config(config_path)

        self.assertEqual(first.api_run_id, second.api_run_id)
        self.assertEqual(first.api_manifest_id, second.api_manifest_id)
        self.assertEqual(first.request_count, 3)
        self.assertEqual(first.requests[0].endpoint_name, "repository")
        self.assertEqual(first.requests[0].method, "GET")
        self.assertEqual(first.requests[0].path, "/repos/{owner}/{repo}")
        payload = json.dumps(first.to_jsonable(), sort_keys=True)
        self.assertIn('"owner": "fixture-owner"', payload)
        self.assertIn('"repository": "fixture-repo"', payload)
        self.assertIn('"fixture_transport_only": true', payload)
        self.assertIn('"no_network": true', payload)
        self.assertIn('"no_mutation": true', payload)
        self.assertIn('"no_credentials_resolved": true', payload)
        self.assertIn('"no_scheduler": true', payload)
        self.assertNotIn("fixture-github-token", payload)
        self.assertNotIn(str(config_path.parent), payload)

    def test_github_real_public_transport_config_is_explicit_public_and_credential_free(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                include_fixture_paths=False,
            )
            private = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                repository_visibility="private",
                credential_mode="none_public_readonly",
                include_fixture_paths=False,
            )
            pat_mode = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                credential_mode="pat_readonly_ref",
                include_credentials=True,
                include_fixture_paths=False,
            )
            credentials = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                include_credentials=True,
                include_fixture_paths=False,
            )
            bad_base = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                base_url="https://example.invalid",
                include_fixture_paths=False,
            )

            config = load_github_api_source_config(valid)
            manifest = build_github_api_plan_from_config(valid)

            with self.assertRaisesRegex(GitHubApiPolicyError, "public"):
                load_github_api_source_config(private)
            with self.assertRaisesRegex(GitHubApiPolicyError, "none_public_readonly"):
                load_github_api_source_config(pat_mode)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials"):
                load_github_api_source_config(credentials)
            with self.assertRaisesRegex(GitHubApiPolicyError, "base_url"):
                load_github_api_source_config(bad_base)

        self.assertEqual(config.acquisition_transport, "github_public_rest")
        self.assertEqual(config.base_url, "https://api.github.com")
        self.assertFalse(config.follow_redirects)
        payload = json.dumps(manifest.to_jsonable(), sort_keys=True)
        self.assertIn('"transport": "github_public_rest"', payload)
        self.assertIn('"network_capable": true', payload)
        self.assertIn('"fixture_transport_only": false', payload)
        self.assertIn('"no_credentials_resolved": true', payload)
        self.assertNotIn("fixture-github-token", payload)

    def test_public_github_rest_transport_builds_safe_request_and_captures_rate_headers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_github_fixture(
                Path(tmpdir),
                transport_mode="github_public_rest",
                include_fixture_paths=False,
            )
            config = load_github_api_source_config(config_path)
            request = build_github_api_plan_from_config(config_path).requests[0]
            opener = FakeGitHubOpener(
                status=200,
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "x-ratelimit-limit": "60",
                    "x-ratelimit-remaining": "59",
                    "x-ratelimit-used": "1",
                    "x-ratelimit-reset": "1782921600",
                    "x-ratelimit-resource": "core",
                },
                body=b'{"full_name":"fixture-owner/fixture-repo"}',
            )

            response = PublicGitHubRestTransport(opener=opener).fetch(config, request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.response_type, "application/json")
        self.assertEqual(response.body, b'{"full_name":"fixture-owner/fixture-repo"}')
        self.assertEqual(
            response.rate_limit,
            {
                "x-ratelimit-limit": "60",
                "x-ratelimit-remaining": "59",
                "x-ratelimit-used": "1",
                "x-ratelimit-reset": "1782921600",
                "x-ratelimit-resource": "core",
            },
        )
        self.assertEqual(
            opener.requests[0].full_url,
            "https://api.github.com/repos/fixture-owner/fixture-repo",
        )
        self.assertEqual(opener.requests[0].get_method(), "GET")
        request_headers = {key.lower(): value for key, value in opener.requests[0].header_items()}
        self.assertIn("user-agent", request_headers)
        self.assertNotIn("authorization", request_headers)
        self.assertNotIn("cookie", request_headers)

    def test_public_github_rest_transport_captures_http_errors_and_url_failures_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_github_fixture(
                Path(tmpdir),
                transport_mode="github_public_rest",
                include_fixture_paths=False,
            )
            config = load_github_api_source_config(config_path)
            request = build_github_api_plan_from_config(config_path).requests[0]
            http_error = urllib.error.HTTPError(
                "https://api.github.com/repos/fixture-owner/fixture-repo",
                403,
                "rate limited",
                {
                    "content-type": "application/json",
                    "x-ratelimit-remaining": "0",
                },
                FakeErrorBody(b'{"message":"rate limit exceeded"}'),
            )
            response = PublicGitHubRestTransport(
                opener=FakeGitHubErrorOpener(http_error)
            ).fetch(config, request)

            with self.assertRaisesRegex(GitHubApiPolicyError, "failed"):
                PublicGitHubRestTransport(
                    opener=FakeGitHubErrorOpener(
                        urllib.error.URLError("socket disabled")
                    )
                ).fetch(config, request)

            with self.assertRaisesRegex(GitHubApiPolicyError, "github_public_rest"):
                PublicGitHubRestTransport(opener=FakeGitHubOpener(
                    status=200,
                    headers={"content-type": "application/json"},
                    body=b"{}",
                )).fetch(
                    load_github_api_source_config(
                        self.write_github_fixture(Path(tmpdir))
                    ),
                    request,
                )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.response_type, "application/json")
        self.assertEqual(response.rate_limit["x-ratelimit-remaining"], "0")
        self.assertIn(b"rate limit", response.body)

    def test_github_real_transport_rejects_unsafe_acquisition_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unsupported = self.write_github_fixture(
                root,
                transport_mode="browser",
                include_fixture_paths=False,
            )
            redirects = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                follow_redirects=True,
                include_fixture_paths=False,
            )
            unsafe_agent = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                user_agent="bad\nagent",
                include_fixture_paths=False,
            )

            with self.assertRaisesRegex(GitHubApiPolicyError, "transport"):
                load_github_api_source_config(unsupported)
            with self.assertRaisesRegex(GitHubApiPolicyError, "redirects"):
                load_github_api_source_config(redirects)
            with self.assertRaisesRegex(GitHubApiPolicyError, "user_agent"):
                load_github_api_source_config(unsafe_agent)

    def test_github_transport_header_helpers_keep_only_safe_metadata(self):
        headers = header_mapping(
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("X-RateLimit-Limit", "60"),
                ("Authorization", "token fixture-secret"),
            ]
        )

        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(content_type_from_headers(headers), "application/json")
        self.assertEqual(content_type_from_headers({}), "application/octet-stream")
        self.assertEqual(
            rate_limit_headers(headers),
            {"x-ratelimit-limit": "60"},
        )
        with self.assertRaisesRegex(GitHubApiPolicyError, "auth headers"):
            validate_no_auth_headers(headers)
        self.assertEqual(
            redact_github_value(None, key="body"),
            {
                "body_present": False,
                "body_length": 0,
                "body_sha256": "",
                "body_redacted": True,
            },
        )

    def test_public_github_rest_acquire_uses_injected_transport_and_minimizes_bodies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                endpoint_names=("issues",),
                include_fixture_paths=False,
            )
            calls = []
            summary = acquire_github_api_source(
                config_path,
                repository_name="fixture",
                root_path=root,
                psql_args=("-d", "postgres"),
                psql_command="/bin/psql",
                loader=self.fake_loader(calls),
                transport=FakeGitHubTransport(
                    [
                        GitHubTransportResponse(
                            status_code=200,
                            body=json.dumps(
                                [
                                    {
                                        "number": 1,
                                        "title": "Public issue title",
                                        "body": "public issue body should be minimized",
                                        "token": "fixture-github-token",
                                    }
                                ]
                            ).encode("utf-8"),
                            response_type="application/json",
                            rate_limit={
                                "x-ratelimit-limit": "60",
                                "x-ratelimit-remaining": "59",
                            },
                        )
                    ]
                ),
            )
            artifact_text = (
                summary.output_path / "artifacts" / "issues.json"
            ).read_text(encoding="utf-8")
            manifest_text = (summary.output_path / "manifest.json").read_text(
                encoding="utf-8"
            )

        self.assertEqual(summary.transport, "github_public_rest")
        self.assertFalse(summary.fixture_transport_only)
        self.assertFalse(summary.no_network)
        self.assertEqual(summary.responses, 1)
        self.assertIn('"body_redacted": true', artifact_text)
        self.assertIn('"body_length"', artifact_text)
        self.assertIn('"body_sha256"', artifact_text)
        self.assertNotIn("public issue body should be minimized", artifact_text)
        self.assertNotIn("fixture-github-token", artifact_text)
        self.assertIn('"transport": "github_public_rest"', manifest_text)
        self.assertIn('"x-ratelimit-remaining": "59"', manifest_text)
        payload = json.dumps(
            [observation.to_dict() for observation in calls[0]["observations"]],
            sort_keys=True,
        )
        self.assertIn('"transport": "github_public_rest"', payload)
        self.assertIn("config.document", payload)
        self.assertNotIn("public issue body should be minimized", payload)
        self.assertNotIn("fixture-github-token", payload)
        self.assertNotIn(str(root), json.dumps(summary.to_jsonable(), sort_keys=True))

    def test_public_github_rest_acquire_fails_safely_on_http_and_payload_errors(self):
        cases = (
            (
                GitHubTransportResponse(status_code=302, body=b"{}", response_type="application/json"),
                "redirect",
            ),
            (
                GitHubTransportResponse(
                    status_code=403,
                    body=b'{"message":"rate limit exceeded"}',
                    response_type="application/json",
                    rate_limit={"x-ratelimit-remaining": "0"},
                ),
                "rate limit",
            ),
            (
                GitHubTransportResponse(status_code=200, body=b"not json", response_type="text/plain"),
                "JSON",
            ),
            (
                GitHubTransportResponse(status_code=200, body=b'{"ok": true}' * 20, response_type="application/json"),
                "max_bytes_per_run",
            ),
        )
        for response, message in cases:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    config_path = self.write_github_fixture(
                        root,
                        transport_mode="github_public_rest",
                        include_fixture_paths=False,
                        max_bytes_per_run=40 if "max_bytes" in message else 10485760,
                    )

                    with self.assertRaisesRegex(GitHubApiPolicyError, message):
                        acquire_github_api_source(
                            config_path,
                            repository_name="fixture",
                            root_path=root,
                            psql_args=("-d", "postgres"),
                            loader=self.fake_loader([]),
                            transport=FakeGitHubTransport([response]),
                        )

                self.assertFalse((root / ".repomap" / "api-runs").exists())

    def test_github_acquire_uses_fixture_transport_artifacts_provenance_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(
                root,
                endpoint_names=("repository", "issues", "pulls", "releases", "actions_runs"),
            )
            calls = []
            summary = acquire_github_api_source(
                config_path,
                repository_name="fixture",
                root_path=root,
                psql_args=("-d", "postgres"),
                psql_command="/bin/psql",
                loader=self.fake_loader(calls),
                transport=FixtureGitHubApiTransport(),
            )
            manifest_path = summary.output_path / "manifest.json"
            response_records_path = summary.output_path / "redacted-responses.jsonl"
            repository_artifact = summary.output_path / "artifacts" / "repository.json"
            issues_artifact = summary.output_path / "artifacts" / "issues.json"
            pulls_artifact = summary.output_path / "artifacts" / "pulls.json"
            releases_artifact = summary.output_path / "artifacts" / "releases.json"
            actions_artifact = summary.output_path / "artifacts" / "actions-runs.json"
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest_exists = manifest_path.is_file()
            response_records_exist = response_records_path.is_file()
            repository_artifact_exists = repository_artifact.is_file()
            issues_artifact_exists = issues_artifact.is_file()
            pulls_artifact_exists = pulls_artifact.is_file()
            releases_artifact_exists = releases_artifact.is_file()
            actions_artifact_exists = actions_artifact.is_file()

        self.assertEqual(summary.source_id, "github-public-fixture")
        self.assertEqual(summary.owner, "fixture-owner")
        self.assertEqual(summary.repository, "fixture-repo")
        self.assertEqual(summary.requests, 5)
        self.assertEqual(summary.responses, 5)
        self.assertGreater(summary.observations, 0)
        self.assertEqual(summary.load_summary.repository_id, 7)
        self.assertTrue(manifest_exists)
        self.assertTrue(response_records_exist)
        self.assertTrue(repository_artifact_exists)
        self.assertTrue(issues_artifact_exists)
        self.assertTrue(pulls_artifact_exists)
        self.assertTrue(releases_artifact_exists)
        self.assertTrue(actions_artifact_exists)
        self.assertEqual(calls[0]["root_path"], str(root.resolve()))
        observation_payload = json.dumps(
            [observation.to_dict() for observation in calls[0]["observations"]],
            sort_keys=True,
        )
        self.assertIn('"api_run_id"', observation_payload)
        self.assertIn('"owner": "fixture-owner"', observation_payload)
        self.assertIn('"repository": "fixture-repo"', observation_payload)
        self.assertIn('"endpoint_name": "repository"', observation_payload)
        self.assertIn("api.source", observation_payload)
        self.assertIn("api.response", observation_payload)
        self.assertIn("github.repository", observation_payload)
        self.assertIn("github.issue", observation_payload)
        self.assertIn("github.pull_request", observation_payload)
        self.assertIn("github.release", observation_payload)
        self.assertIn("github.workflow_run", observation_payload)
        self.assertIn("config.document", observation_payload)
        self.assertNotIn("fixture-secret-value", observation_payload)
        self.assertNotIn("fixture-github-token", observation_payload)
        self.assertNotIn("fixture-private-key", observation_payload)
        self.assertNotIn("https://api.github.com/repos/fixture-owner/fixture-repo/tarball/v1.0.0", observation_payload)
        self.assertNotIn(str(root), observation_payload)
        self.assertNotIn("fixture-secret-value", manifest_text)
        self.assertNotIn("fixture-github-token", manifest_text)
        summary_payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"fixture_transport_only": true', summary_payload)
        self.assertIn('"no_network": true', summary_payload)
        self.assertIn('"no_mutation": true', summary_payload)
        self.assertNotIn(str(root), summary_payload)
        self.assertNotIn("fixture-secret-value", summary_payload)

    def test_github_acquire_enforces_response_limits_before_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(root, max_bytes_per_run=10)

            with self.assertRaisesRegex(GitHubApiPolicyError, "max_bytes_per_run"):
                acquire_github_api_source(
                    config_path,
                    repository_name="fixture",
                    root_path=root,
                    psql_args=("-d", "postgres"),
                    loader=self.fake_loader([]),
                    transport=FixtureGitHubApiTransport(),
                )

        self.assertFalse((root / ".repomap" / "api-runs").exists())

    def test_github_acquire_enforces_item_limits_before_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(
                root,
                endpoint_names=("issues",),
                max_items_per_endpoint=1,
            )
            (config_path.parent / "responses" / "issues.json").write_text(
                json.dumps(
                    [
                        {"number": 1, "title": "one"},
                        {"number": 2, "title": "two"},
                    ],
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(GitHubApiPolicyError, "max_items"):
                acquire_github_api_source(
                    config_path,
                    repository_name="fixture",
                    root_path=root,
                    psql_args=("-d", "postgres"),
                    loader=self.fake_loader([]),
                    transport=FixtureGitHubApiTransport(),
                )

        self.assertFalse((root / ".repomap" / "api-runs").exists())

    def write_github_fixture(
        self,
        root: Path,
        *,
        policy_status: str = "allowed_with_limits",
        provider_name: str = "GitHub",
        provider_product: str = "GitHub REST API",
        source_type: str = "api.rest",
        api_source_class: str = "api.github.repository",
        owner: str = "fixture-owner",
        repository: str = "fixture-repo",
        repository_visibility: str = "public",
        credential_mode: str = "none_public_readonly",
        include_credentials: bool = False,
        credentials_ref: str = "local_secret_ref:fixture-github-token",
        include_consent: bool = True,
        consent_revoked: bool = False,
        consent_mutation_allowed: bool = False,
        authorized_operations: tuple[str, ...] = ("read",),
        authorized_data_classes: tuple[str, ...] = (
            "repository_metadata",
            "issues",
            "pull_requests",
            "releases",
            "actions",
        ),
        method: str = "GET",
        endpoint_path: str = "/repos/{owner}/{repo}",
        endpoint_names: tuple[str, ...] = ("repository",),
        pagination: str = "none",
        downstream_route: str = "config",
        fixture_response_path: str | None = None,
        transport_mode: str = "fixture",
        base_url: str = "https://api.github.com",
        follow_redirects: bool = False,
        user_agent: str = "repomap-kg-test",
        include_fixture_paths: bool = True,
        max_requests_per_run: int = 20,
        max_pages_per_endpoint: int = 1,
        max_bytes_per_run: int = 10485760,
        max_items_per_endpoint: int = 100,
        max_concurrent_requests: int = 1,
        max_retries: int = 0,
    ) -> Path:
        fixture = root / f"github-api-{len(list(root.glob('github-api-*')))}"
        fixture.mkdir()
        responses = fixture / "responses"
        responses.mkdir()
        self.write_github_responses(responses)
        credentials_block = (
            "\n[credentials]\n"
            f'credentials_ref = "{credentials_ref}"\n'
            if include_credentials
            else ""
        )
        consent_block = (
            "\n[consent]\n"
            'consent_ref = "local_consent_ref:github-public-fixture-2026-07"\n'
            f"authorized_operations = {json.dumps(list(authorized_operations))}\n"
            f"authorized_data_classes = {json.dumps(list(authorized_data_classes))}\n"
            f"revoked = {str(consent_revoked).lower()}\n"
            f"mutation_allowed = {str(consent_mutation_allowed).lower()}\n"
            if include_consent
            else ""
        )
        endpoint_blocks = []
        endpoint_map = {
            "repository": ("/repos/{owner}/{repo}", "responses/repository.json", 1),
            "issues": ("/repos/{owner}/{repo}/issues", "responses/issues.json", 100),
            "pulls": ("/repos/{owner}/{repo}/pulls", "responses/pulls.json", 100),
            "releases": ("/repos/{owner}/{repo}/releases", "responses/releases.json", 100),
            "actions_runs": (
                "/repos/{owner}/{repo}/actions/runs",
                "responses/actions-runs.json",
                100,
            ),
        }
        for name in endpoint_names:
            default_path, default_fixture, max_page_size = endpoint_map[name]
            path = endpoint_path if len(endpoint_names) == 1 else default_path
            response_path = fixture_response_path or default_fixture
            endpoint_blocks.append(
                "\n[[endpoints]]\n"
                f'name = "{name}"\n'
                f'method = "{method}"\n'
                f'path = "{path}"\n'
                f'purpose = "Export GitHub fixture {name} metadata"\n'
                'response_type = "application/json"\n'
                f"max_page_size = {max_page_size}\n"
                f'pagination = "{pagination}"\n'
                f'downstream_route = "{downstream_route}"\n'
                + (
                    f'fixture_response_path = "{response_path}"\n'
                    if include_fixture_paths
                    else ""
                )
            )
        config_path = fixture / "github-source.toml"
        config_path.write_text(
            "[source]\n"
            'source_id = "github-public-fixture"\n'
            f'source_type = "{source_type}"\n'
            f'api_source_class = "{api_source_class}"\n'
            f'provider_name = "{provider_name}"\n'
            f'provider_product = "{provider_product}"\n'
            f'policy_status = "{policy_status}"\n'
            f'owner = "{owner}"\n'
            f'repository = "{repository}"\n'
            f'repository_visibility = "{repository_visibility}"\n'
            "read_only = true\n"
            "mutation_allowed = false\n"
            f'credential_mode = "{credential_mode}"\n'
            f"{credentials_block}"
            "\n[acquisition]\n"
            f'transport = "{transport_mode}"\n'
            f'base_url = "{base_url}"\n'
            "timeout_seconds = 10\n"
            f"follow_redirects = {str(follow_redirects).lower()}\n"
            f"user_agent = {json.dumps(user_agent)}\n"
            f"{consent_block}"
            "\n[limits]\n"
            f"max_requests_per_run = {max_requests_per_run}\n"
            "max_requests_per_minute = 10\n"
            f"max_pages_per_endpoint = {max_pages_per_endpoint}\n"
            f"max_items_per_endpoint = {max_items_per_endpoint}\n"
            f"max_bytes_per_run = {max_bytes_per_run}\n"
            f"max_concurrent_requests = {max_concurrent_requests}\n"
            f"max_retries = {max_retries}\n"
            "\n[retention]\n"
            'policy = "local_user_controlled"\n'
            'raw_response_retention = "minimized"\n'
            'redacted_response_retention = "retain"\n'
            "\n[redaction]\n"
            'profile = "strict"\n'
            'sensitivity = "public_metadata"\n'
            f"{''.join(endpoint_blocks)}",
            encoding="utf-8",
        )
        return config_path

    def write_github_responses(self, responses: Path) -> None:
        (responses / "repository.json").write_text(
            json.dumps(
                {
                    "id": 1001,
                    "name": "fixture-repo",
                    "full_name": "fixture-owner/fixture-repo",
                    "private": False,
                    "clone_url": "https://fixture-github-token@example.invalid/fixture.git",
                    "ssh_url": "git@example.invalid:fixture-owner/fixture-repo.git",
                    "html_url": "https://example.invalid/fixture-owner/fixture-repo",
                    "secret": "fixture-secret-value",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "issues.json").write_text(
            json.dumps(
                [
                    {
                        "number": 1,
                        "title": "Fixture issue",
                        "body": "safe public issue body",
                        "author_association": "OWNER",
                        "token": "fixture-github-token",
                    }
                ],
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "pulls.json").write_text(
            json.dumps(
                [
                    {
                        "number": 2,
                        "title": "Fixture pull",
                        "diff_url": "https://example.invalid/fixture.diff",
                        "patch_url": "https://example.invalid/fixture.patch",
                    }
                ],
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "releases.json").write_text(
            json.dumps(
                [
                    {
                        "tag_name": "v1.0.0",
                        "tarball_url": "https://api.github.com/repos/fixture-owner/fixture-repo/tarball/v1.0.0",
                        "zipball_url": "https://api.github.com/repos/fixture-owner/fixture-repo/zipball/v1.0.0",
                    }
                ],
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "actions-runs.json").write_text(
            json.dumps(
                {
                    "workflow_runs": [
                        {
                            "id": 3001,
                            "name": "CI",
                            "status": "completed",
                            "conclusion": "success",
                            "logs_url": "https://api.github.com/repos/fixture-owner/fixture-repo/actions/runs/3001/logs?token=fixture-private-key",
                            "artifacts_url": "https://api.github.com/repos/fixture-owner/fixture-repo/actions/runs/3001/artifacts?token=fixture-private-key",
                        }
                    ]
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

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


class FakeGitHubTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def fetch(self, config, request):
        self.requests.append((config, request))
        return self.responses.pop(0)


class FakeGitHubOpener:
    def __init__(self, *, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return FakeGitHubHttpResponse(
            status=self.status,
            headers=self.headers,
            body=self.body,
        )


class FakeGitHubErrorOpener:
    def __init__(self, error):
        self.error = error

    def open(self, request, timeout):
        raise self.error


class FakeGitHubHttpResponse:
    def __init__(self, *, status, headers, body):
        self.status = status
        self.headers = headers
        self._body = body

    def getcode(self):
        return self.status

    def read(self, _size):
        return self._body


class FakeErrorBody:
    def __init__(self, body):
        self.body = body

    def read(self, _size):
        return self.body

    def close(self):
        return None


if __name__ == "__main__":
    unittest.main()
