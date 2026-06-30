import json
import tempfile
import unittest
import urllib.error
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


RSS_BODY = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Fixture Feed</title>
    <link>https://example.invalid/feed-home</link>
    <description>Local fixture only</description>
    <item>
      <guid>rss-item-1</guid>
      <title>RSS Item One</title>
      <link>https://example.invalid/items/1</link>
      <enclosure url="https://example.invalid/media/1.mp3" type="audio/mpeg" />
    </item>
  </channel>
</rss>
"""


ATOM_BODY = b"""\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom Fixture</title>
  <id>urn:example:atom</id>
  <updated>2026-06-30T12:00:00Z</updated>
  <entry>
    <id>urn:example:atom:1</id>
    <title>Atom Item One</title>
    <link rel="alternate" href="https://example.invalid/atom/1" />
    <updated>2026-06-30T12:30:00Z</updated>
  </entry>
</feed>
"""


JSON_FEED_BODY = json.dumps(
    {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "Example JSON Fixture",
        "items": [
            {
                "id": "json-item-1",
                "title": "JSON Item One",
                "url": "https://example.invalid/json/1",
            }
        ],
    },
    sort_keys=True,
).encode("utf-8")


class SourceIngestionUnitTests(unittest.TestCase):
    def test_allowed_feed_source_fetches_configured_url_and_records_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "rss-source.toml")
            calls = []

            summary = ingest_feed_source(
                config,
                repository_name="fixture",
                root_path=root,
                psql_args=(),
                psql_command="psql",
                fetcher=self.fetcher_returning(RSS_BODY, calls=calls),
                loader=self.fake_loader,
                clock=self.fixed_clock,
            )

        self.assertEqual(calls, ["https://example.invalid/rss.xml"])
        self.assertEqual(summary.source_id, "example-news-feed")
        self.assertEqual(summary.source_type, "feed.rss")
        self.assertEqual(summary.policy_status, "allowed_with_limits")
        self.assertEqual(summary.observations, 7)
        self.assertEqual(summary.load_summary.repository_id, 7)
        self.assertTrue(summary.artifact_path.endswith("rss.xml"))
        self.assertEqual(summary.artifact_bytes, len(RSS_BODY))
        self.assertEqual(len(summary.artifact_sha256), 64)
        payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id_configured": "example-news-feed"', payload)
        self.assertIn('"source_run_id": "20260630T120000Z"', payload)
        self.assertIn('"source_artifact_sha256"', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_blocked_and_manual_review_sources_stop_before_fetch(self):
        for status in ("blocked_terms_risk", "manual_review_required"):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()
                    config = self.write_config(
                        root / f"{status}.toml",
                        policy_status=status,
                    )
                    calls = []

                    with self.assertRaises(SourcePolicyError):
                        ingest_feed_source(
                            config,
                            repository_name="fixture",
                            root_path=root,
                            psql_args=(),
                            fetcher=self.fetcher_returning(RSS_BODY, calls=calls),
                            loader=self.fake_loader,
                            clock=self.fixed_clock,
                        )

                self.assertEqual(calls, [])

    def test_policy_validation_rejects_unknown_source_type_and_missing_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unknown_type = self.write_config(
                root / "unknown-type.toml",
                source_type="unknown",
            )
            missing_timeout = self.write_config(
                root / "missing-timeout.toml",
                timeout_seconds=None,
            )
            zero_artifact_bytes = self.write_config(
                root / "zero-artifact-bytes.toml",
                max_artifact_bytes=0,
            )

            with self.assertRaisesRegex(SourcePolicyError, "source type"):
                load_feed_source_config(unknown_type)
            with self.assertRaisesRegex(SourcePolicyError, "timeout_seconds"):
                load_feed_source_config(missing_timeout)
            with self.assertRaisesRegex(SourcePolicyError, "positive integer"):
                load_feed_source_config(zero_artifact_bytes)

    def test_rejects_raw_url_as_source_id_and_secret_bearing_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_url_id = self.write_config(
                root / "raw-url-id.toml",
                source_id="https://example.invalid/rss.xml",
            )
            credential_url = self.write_config(
                root / "credential-url.toml",
                url="https://user:fixture-secret@example.invalid/rss.xml",
            )

            with self.assertRaisesRegex(SourcePolicyError, "source id"):
                load_feed_source_config(raw_url_id)
            with self.assertRaisesRegex(SourcePolicyError, "credentials"):
                load_feed_source_config(credential_url)

    def test_max_artifact_bytes_is_enforced_before_extraction_or_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "small.toml", max_artifact_bytes=8)
            loaded = []

            with self.assertRaises(SourceAcquisitionError):
                ingest_feed_source(
                    config,
                    repository_name="fixture",
                    root_path=root,
                    psql_args=(),
                    fetcher=self.fetcher_returning(RSS_BODY),
                    loader=lambda *args, **kwargs: loaded.append(args),
                    clock=self.fixed_clock,
                )

        self.assertEqual(loaded, [])

    def test_redirect_response_is_rejected_without_fetching_redirect_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "redirect.toml")

            with self.assertRaisesRegex(SourceAcquisitionError, "redirect"):
                ingest_feed_source(
                    config,
                    repository_name="fixture",
                    root_path=root,
                    psql_args=(),
                    fetcher=self.fetcher_returning(b"", status=302),
                    loader=self.fake_loader,
                    clock=self.fixed_clock,
                )

    def test_default_fetcher_uses_configured_timeout_method_and_user_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_feed_source_config(self.write_config(root / "rss.toml"))
            opener = FakeOpener(
                FakeResponse(200, b"<rss />", {"content-type": "text/xml"}),
            )

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

    def test_default_fetcher_captures_http_error_without_following_redirect(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_feed_source_config(self.write_config(root / "rss.toml"))
            opener = FakeOpener(
                urllib.error.HTTPError(
                    config.url,
                    302,
                    "Found",
                    {"location": "https://example.invalid/redirect"},
                    FakeBody(b"redirect"),
                ),
            )

            response = fetch_feed_source(config, opener=opener)

        self.assertEqual(response.status, 302)
        self.assertEqual(response.body, b"redirect")
        self.assertEqual(
            response.headers["location"],
            "https://example.invalid/redirect",
        )

    def test_default_fetcher_wraps_url_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_feed_source_config(self.write_config(root / "rss.toml"))
            opener = FakeOpener(urllib.error.URLError("network unavailable"))

            with self.assertRaisesRegex(SourceAcquisitionError, "network unavailable"):
                fetch_feed_source(config, opener=opener)

    def test_fetched_atom_and_json_feed_artifacts_use_rss1_extractor(self):
        cases = (
            ("feed.atom", "atom.xml", ATOM_BODY, "atom"),
            ("feed.json", "feed.json", JSON_FEED_BODY, "json-feed"),
        )
        for source_type, artifact_name, body, expected_format in cases:
            with self.subTest(source_type=source_type):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()
                    config = self.write_config(
                        root / f"{source_type}.toml",
                        source_type=source_type,
                    )
                    summary = ingest_feed_source(
                        config,
                        repository_name="fixture",
                        root_path=root,
                        psql_args=(),
                        fetcher=self.fetcher_returning(body),
                        loader=self.fake_loader,
                        clock=self.fixed_clock,
                    )

                self.assertTrue(summary.artifact_path.endswith(artifact_name))
                documents = [
                    observation
                    for observation in summary.raw_observations
                    if observation.kind == "feed.document"
                ]
                self.assertEqual(documents[0].metadata["feed_format"], expected_format)

    def test_malformed_fetched_feed_remains_safe_parse_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "malformed.toml")
            summary = ingest_feed_source(
                config,
                repository_name="fixture",
                root_path=root,
                psql_args=(),
                fetcher=self.fetcher_returning(b"<rss><channel>"),
                loader=self.fake_loader,
                clock=self.fixed_clock,
            )

        self.assertIn(
            "feed.parse_error",
            {observation.kind for observation in summary.raw_observations},
        )

    def test_item_limit_stops_before_load_after_retaining_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "limited.toml", max_items_per_run=0)
            loaded = []

            with self.assertRaisesRegex(SourcePolicyError, "max_items_per_run"):
                ingest_feed_source(
                    config,
                    repository_name="fixture",
                    root_path=root,
                    psql_args=(),
                    fetcher=self.fetcher_returning(RSS_BODY),
                    loader=lambda *args, **kwargs: loaded.append(args),
                    clock=self.fixed_clock,
                )

            artifacts = list((root / ".repomap" / "source-artifacts").rglob("rss.xml"))

        self.assertEqual(loaded, [])
        self.assertEqual(len(artifacts), 1)

    def test_secret_config_values_are_not_added_to_summary_or_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "secret.toml", secret=True)
            summary = ingest_feed_source(
                config,
                repository_name="fixture",
                root_path=root,
                psql_args=(),
                fetcher=self.fetcher_returning(JSON_FEED_BODY),
                loader=self.fake_loader,
                clock=self.fixed_clock,
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
        self.assertNotIn("fixture-secret", payload)

    def test_artifact_directory_must_stay_inside_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "rss.toml")

            with self.assertRaisesRegex(SourcePolicyError, "artifact_dir"):
                ingest_feed_source(
                    config,
                    repository_name="fixture",
                    root_path=root,
                    artifact_dir=Path(tmpdir) / "outside",
                    psql_args=(),
                    fetcher=self.fetcher_returning(RSS_BODY),
                    loader=self.fake_loader,
                    clock=self.fixed_clock,
                )

    def write_config(
        self,
        path: Path,
        *,
        source_id: str = "example-news-feed",
        source_type: str = "feed.rss",
        policy_status: str = "allowed_with_limits",
        url: str = "https://example.invalid/rss.xml",
        timeout_seconds: int | None = 10,
        max_artifact_bytes: int = 1048576,
        max_items_per_run: int | None = 100,
        secret: bool = False,
    ) -> Path:
        policy_lines = [
            f'status = "{policy_status}"',
            'preferred_method = "rss"',
            'rate_limit = "1 request per 15 minutes"',
            f"max_artifact_bytes = {max_artifact_bytes}",
            'robots_policy = "fixture"',
            'terms_policy = "fixture"',
            "requires_manual_review = false",
        ]
        if timeout_seconds is not None:
            policy_lines.append(f"timeout_seconds = {timeout_seconds}")
        if max_items_per_run is not None:
            policy_lines.append(f"max_items_per_run = {max_items_per_run}")
        secret_block = (
            '\n[credentials]\ntoken = "fixture-secret"\n' if secret else ""
        )
        path.write_text(
            "\n".join(
                [
                    "[source]",
                    f'id = "{source_id}"',
                    f'type = "{source_type}"',
                    'display_name = "Example News Feed"',
                    "",
                    "[policy]",
                    *policy_lines,
                    "",
                    "[acquisition]",
                    f'url = "{url}"',
                    'method = "GET"',
                    'user_agent = "RepoMap feed ingestion test fixture"',
                    secret_block,
                ]
            ),
            encoding="utf-8",
        )
        return path

    def fetcher_returning(
        self,
        body: bytes,
        *,
        status: int = 200,
        calls: list[str] | None = None,
    ):
        def fetcher(config):
            if calls is not None:
                calls.append(config.url)
            return FeedFetchResponse(
                status=status,
                headers={"content-type": "application/xml"},
                body=body,
            )

        return fetcher

    def fake_loader(self, _psql_args, observations, **_kwargs):
        from repomap_kg.storage import LoadSummary

        self.assertGreater(len(observations), 0)
        return LoadSummary(repository_id=7, run_id=11, files=1)

    @staticmethod
    def fixed_clock():
        return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


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

    def read(self, _limit):
        return self._body


class FakeBody:
    def __init__(self, body):
        self.body = body

    def read(self, _limit):
        return self.body

    def close(self):
        return None


if __name__ == "__main__":
    unittest.main()
