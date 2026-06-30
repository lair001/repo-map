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
    fetch_feed_source,
    ingest_feed_source,
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


if __name__ == "__main__":
    unittest.main()
