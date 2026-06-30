import tempfile
import unittest
import urllib.error
import json
from datetime import UTC, datetime
from pathlib import Path

from repomap_kg.source_ingestion import (
    FeedFetchResponse,
    SourceAcquisitionError,
    SourcePolicyError,
    archive_observations_from_manifest,
    build_archive_manifest,
    fetch_feed_source,
    import_archive_source,
    ingest_feed_source,
    load_archive_source_config,
    load_feed_source_config,
)
from repomap_kg.storage import LoadSummary


class SourceIngestionIntegrationTests(unittest.TestCase):
    def test_feed_source_fixture_policy_matrix(self):
        allowed = load_feed_source_config(source_fixture("allowed-rss.toml"))
        secret = load_feed_source_config(source_fixture("secret-bearing.toml"))

        self.assertEqual(allowed.source_id, "example-rss-feed")
        self.assertEqual(allowed.source_type, "feed.rss")
        self.assertEqual(allowed.timeout_seconds, 10)
        self.assertEqual(
            secret.redacted_config_keys,
            ("credentials", "credentials.token"),
        )

        for filename in ("blocked-policy.toml", "manual-review.toml"):
            with self.subTest(filename=filename):
                with self.assertRaises(SourcePolicyError):
                    load_feed_source_config(source_fixture(filename))

    def test_archive_source_fixture_policy_and_manifest_matrix(self):
        allowed = load_archive_source_config(
            archive_source_fixture("allowed-test-report.toml")
        )
        saved_page = load_archive_source_config(
            archive_source_fixture("allowed-saved-page.toml")
        )
        manifest = build_archive_manifest(
            allowed,
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )
        limited = build_archive_manifest(
            load_archive_source_config(archive_source_fixture("limited-files.toml")),
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )

        self.assertEqual(allowed.source_type, "test_report.artifact")
        self.assertEqual(saved_page.source_type, "saved_page.archive")
        self.assertEqual(manifest.file_count, 6)
        self.assertEqual(
            [item.relative_path for item in manifest.included_files],
            [
                "assets/logo.svg",
                "config/settings.json",
                "feed/feed.json",
                "index.html",
                "static/app.js",
                "static/report.css",
            ],
        )
        self.assertTrue(
            any(skipped.reason == "hidden" for skipped in manifest.skipped_files)
        )
        self.assertTrue(
            any(
                skipped.reason == "excluded-directory"
                for skipped in manifest.skipped_files
            )
        )
        self.assertEqual(limited.file_count, 1)
        self.assertTrue(
            any(skipped.reason == "max_file_count" for skipped in limited.skipped_files)
        )
        for filename in ("blocked-policy.toml", "manual-review.toml"):
            with self.subTest(filename=filename):
                with self.assertRaises(SourcePolicyError):
                    load_archive_source_config(archive_source_fixture(filename))

    def test_archive_fixture_observations_are_local_and_redacted(self):
        config = load_archive_source_config(
            archive_source_fixture("allowed-test-report.toml")
        )
        manifest = build_archive_manifest(
            config,
            root_path=source_ingestion_fixture_root(),
            clock=fixed_clock,
        )

        observations = archive_observations_from_manifest(
            config,
            manifest,
            root_path=source_ingestion_fixture_root(),
        )

        kinds = {observation.kind for observation in observations}
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("css.selector_match", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("feed.document", kinds)
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertIn('"artifact_manifest_id"', payload)
        self.assertIn(
            '"artifact_relative_path": '
            '"archive_artifacts/example-test-report/index.html"',
            payload,
        )
        self.assertNotIn("fixture-secret", payload)

    def test_archive_import_uses_existing_loader_path_without_network(self):
        captured = {}

        def loader(_psql_args, observations, **kwargs):
            captured["observations"] = tuple(observations)
            captured["kwargs"] = dict(kwargs)
            return LoadSummary(repository_id=42, run_id=43, files=6)

        summary = import_archive_source(
            archive_source_fixture("allowed-test-report.toml"),
            repository_name="fixture",
            root_path=source_ingestion_fixture_root(),
            psql_args=("--no-network-placeholder",),
            psql_command="psql",
            loader=loader,
            clock=fixed_clock,
        )

        self.assertEqual(summary.source_id, "example-test-report")
        self.assertEqual(summary.included_files, 6)
        self.assertEqual(summary.load_summary.repository_id, 42)
        self.assertEqual(captured["kwargs"]["repository_name"], "fixture")
        self.assertGreater(len(captured["observations"]), 6)
        payload = json.dumps(
            [observation.to_dict() for observation in captured["observations"]],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_default_fetcher_uses_configured_timeout_method_and_user_agent(self):
        config = load_feed_source_config(source_fixture("allowed-rss.toml"))
        opener = FakeOpener(FakeResponse(200, b"<rss />", {"content-type": "text/xml"}))

        response = fetch_feed_source(config, opener=opener)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"<rss />")
        self.assertEqual(response.headers["content-type"], "text/xml")
        self.assertEqual(opener.timeout, 10)
        self.assertEqual(opener.request.get_method(), "GET")
        self.assertEqual(
            dict(opener.request.header_items())["User-agent"],
            "RepoMap feed ingestion test fixture",
        )

    def test_default_fetcher_captures_http_error_without_following_redirect_body(self):
        config = load_feed_source_config(source_fixture("allowed-rss.toml"))
        opener = FakeOpener(
            urllib.error.HTTPError(
                config.url,
                302,
                "Found",
                {"location": "https://example.invalid/redirect"},
                FakeBody(b"redirect"),
            )
        )

        response = fetch_feed_source(config, opener=opener)

        self.assertEqual(response.status, 302)
        self.assertEqual(response.body, b"redirect")
        self.assertEqual(
            response.headers["location"],
            "https://example.invalid/redirect",
        )

    def test_policy_blocked_ingestion_stops_before_fetch(self):
        calls = []

        with self.assertRaises(SourcePolicyError):
            ingest_feed_source(
                source_fixture("blocked-policy.toml"),
                repository_name="fixture",
                root_path=Path("/tmp/fixture"),
                psql_args=(),
                fetcher=lambda config: calls.append(config.url),
                loader=fake_loader,
            )

        self.assertEqual(calls, [])

    def test_unrecognized_fetched_artifact_is_retained_but_not_loaded(self):
        loaded = []
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()

            with self.assertRaises(SourceAcquisitionError):
                ingest_feed_source(
                    source_fixture("allowed-json.toml"),
                    repository_name="fixture",
                    root_path=root,
                    psql_args=(),
                    fetcher=lambda _config: FeedFetchResponse(
                        status=200,
                        headers={"content-type": "application/json"},
                        body=b'{"not": "a feed"}',
                    ),
                    loader=lambda *args, **kwargs: loaded.append(args),
                )

            artifacts = list((root / ".repomap" / "source-artifacts").rglob("feed.json"))

        self.assertEqual(loaded, [])
        self.assertEqual(len(artifacts), 1)

    def test_oversized_and_redirect_responses_stop_before_load(self):
        cases = (
            (
                source_fixture("oversized-artifact.toml"),
                FeedFetchResponse(status=200, body=b"too many bytes"),
                "max_artifact_bytes",
            ),
            (
                source_fixture("allowed-rss.toml"),
                FeedFetchResponse(status=302, body=b"redirect"),
                "redirect",
            ),
        )
        for config_path, response, message in cases:
            with self.subTest(message=message):
                loaded = []
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()

                    with self.assertRaisesRegex(SourceAcquisitionError, message):
                        ingest_feed_source(
                            config_path,
                            repository_name="fixture",
                            root_path=root,
                            psql_args=(),
                            fetcher=lambda _config: response,
                            loader=lambda *args, **kwargs: loaded.append(args),
                        )

                self.assertEqual(loaded, [])

    def test_atom_and_json_feed_sources_retain_expected_artifact_names(self):
        cases = (
            (
                source_fixture("allowed-atom.toml"),
                b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title><id>urn:a</id><entry><id>urn:a:1</id><title>One</title></entry></feed>""",
                "atom.xml",
                "atom",
            ),
            (
                source_fixture("allowed-json.toml"),
                b'{"version":"https://jsonfeed.org/version/1.1","title":"J","items":[{"id":"1","title":"One"}]}',
                "feed.json",
                "json-feed",
            ),
        )
        for config_path, body, artifact_name, feed_format in cases:
            with self.subTest(artifact_name=artifact_name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()
                    summary = ingest_feed_source(
                        config_path,
                        repository_name="fixture",
                        root_path=root,
                        psql_args=(),
                        fetcher=lambda _config: FeedFetchResponse(
                            status=200,
                            body=body,
                        ),
                        loader=fake_loader,
                        clock=fixed_clock,
                    )

                self.assertTrue(summary.artifact_path.endswith(artifact_name))
                self.assertEqual(
                    [
                        observation.metadata["feed_format"]
                        for observation in summary.raw_observations
                        if observation.kind == "feed.document"
                    ],
                    [feed_format],
                )

    def test_secret_bearing_config_redacts_values_in_summary_and_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            summary = ingest_feed_source(
                source_fixture("secret-bearing.toml"),
                repository_name="fixture",
                root_path=root,
                psql_args=(),
                fetcher=lambda _config: FeedFetchResponse(
                    status=200,
                    headers={"content-type": "application/feed+json"},
                    body=b'{"version":"https://jsonfeed.org/version/1.1","title":"S","items":[]}',
                ),
                loader=fake_loader,
                clock=fixed_clock,
            )

        payload = json.dumps(
            {
                "summary": summary.to_jsonable(),
                "observations": [
                    observation.to_dict()
                    for observation in summary.raw_observations
                ],
            },
            sort_keys=True,
        )
        self.assertIn("credentials.token", payload)
        self.assertNotIn("fixture-secret-placeholder", payload)

    def test_artifact_directory_must_stay_inside_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()

            with self.assertRaisesRegex(SourcePolicyError, "artifact_dir"):
                ingest_feed_source(
                    source_fixture("allowed-rss.toml"),
                    repository_name="fixture",
                    root_path=root,
                    artifact_dir=Path(tmpdir) / "outside",
                    psql_args=(),
                    fetcher=lambda _config: FeedFetchResponse(
                        status=200,
                        body=b"<rss />",
                    ),
                    loader=fake_loader,
                )


class FakeOpener:
    def __init__(self, response_or_error):
        self.response_or_error = response_or_error
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout):
        self.request = request
        self.timeout = timeout
        if isinstance(self.response_or_error, Exception):
            raise self.response_or_error
        return self.response_or_error


class FakeResponse:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body
        self.headers = headers

    def getcode(self):
        return self.status

    def read(self, limit):
        return self._body[:limit]


class FakeBody:
    def __init__(self, body):
        self.body = body

    def read(self, limit=-1):
        if limit < 0:
            return self.body
        return self.body[:limit]

    def close(self):
        return None


def fake_loader(_psql_args, _observations, **_kwargs):
    return LoadSummary(repository_id=1, run_id=1, files=1)


def fixed_clock() -> datetime:
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


def source_fixture(filename: str) -> Path:
    return (
        Path(__file__).parents[3]
        / "fixtures"
        / "source_ingestion"
        / "feed_sources"
        / filename
    )


def archive_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "archive_sources" / filename


def source_ingestion_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "source_ingestion"


if __name__ == "__main__":
    unittest.main()
