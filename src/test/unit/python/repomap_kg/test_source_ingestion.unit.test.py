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
    archive_observations_from_manifest,
    build_archive_manifest,
    fetch_feed_source,
    import_archive_source,
    ingest_feed_source,
    load_archive_source_config,
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

    def test_archive_config_policy_rejects_unknown_blocked_and_url_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            artifact = root / "reports" / "latest"
            artifact.mkdir(parents=True)
            (artifact / "index.html").write_text("<h1>Report</h1>", encoding="utf-8")
            allowed = self.write_archive_config(root / "archive.toml")
            unknown = self.write_archive_config(
                root / "unknown.toml",
                source_type="unknown",
            )
            blocked = self.write_archive_config(
                root / "blocked.toml",
                policy_status="blocked_terms_risk",
            )
            acquisition = self.write_archive_config(
                root / "acquisition.toml",
                extra="\n[acquisition]\nurl = \"https://example.invalid/archive\"\n",
            )

            config = load_archive_source_config(allowed)

            self.assertEqual(config.source_id, "example-test-report")
            self.assertEqual(config.source_type, "test_report.artifact")
            self.assertEqual(config.artifact_path, "reports/latest")
            with self.assertRaisesRegex(SourcePolicyError, "source type"):
                load_archive_source_config(unknown)
            with self.assertRaisesRegex(SourcePolicyError, "policy status"):
                load_archive_source_config(blocked)
            with self.assertRaisesRegex(SourcePolicyError, "network acquisition"):
                load_archive_source_config(acquisition)

    def test_archive_manifest_is_deterministic_and_skips_sensitive_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            artifact = self.write_archive_artifact(root)
            symlink_created = False
            try:
                (artifact / "linked.css").symlink_to("static/report.css")
                symlink_created = True
            except OSError:
                pass
            config = load_archive_source_config(
                self.write_archive_config(root / "archive.toml")
            )

            first = build_archive_manifest(config, root_path=root, clock=self.fixed_clock)
            second = build_archive_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )

        self.assertEqual(first.to_jsonable(), second.to_jsonable())
        self.assertEqual(
            [item.relative_path for item in first.included_files],
            [
                "assets/logo.svg",
                "config/settings.json",
                "index.html",
                "static/app.js",
                "static/report.css",
            ],
        )
        self.assertEqual(first.file_count, 5)
        expected_skips = 3 if symlink_created else 2
        self.assertEqual(first.skipped_file_count, expected_skips)
        self.assertTrue(all(len(item.sha256) == 64 for item in first.included_files))
        skipped = {item.relative_path: item.reason for item in first.skipped_files}
        self.assertEqual(skipped[".hidden-secret"], "hidden")
        self.assertEqual(skipped[".git"], "excluded-directory")
        if symlink_created:
            self.assertEqual(skipped["linked.css"], "symlink")

    def test_archive_observations_reuse_extractors_and_attach_safe_metadata(self):
        captured = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            self.write_archive_artifact(root)
            config_path = self.write_archive_config(
                root / "archive.toml",
                secret=True,
            )
            config = load_archive_source_config(config_path)
            manifest = build_archive_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )
            observations = archive_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )

            def capture_loader(_psql_args, observations, **_kwargs):
                captured["observations"] = tuple(observations)
                return self.fake_loader(_psql_args, observations, **_kwargs)

            summary = import_archive_source(
                config_path,
                repository_name="fixture",
                root_path=root,
                psql_args=(),
                loader=capture_loader,
                clock=self.fixed_clock,
            )

        kinds = {observation.kind for observation in observations}
        self.assertIn("file", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("css.selector_match", kinds)
        self.assertIn("config.document", kinds)
        self.assertNotIn("javascript.execution", kinds)
        loaded_observations = captured["observations"]
        payload = json.dumps(
            {
                "summary": summary.to_jsonable(),
                "observations": [
                    observation.to_dict()
                    for observation in loaded_observations
                ],
            },
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertIn('"source_type": "test_report.artifact"', payload)
        self.assertIn('"artifact_run_id": "20260630T120000Z"', payload)
        self.assertIn('"artifact_manifest_id"', payload)
        self.assertIn('"artifact_relative_path": "reports/latest/index.html"', payload)
        self.assertIn('"artifact_sha256"', payload)
        self.assertIn("credentials.token", payload)
        self.assertNotIn("fixture-secret", payload)

    def test_archive_manifest_rejects_repo_escaping_paths_and_limits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            (outside / "index.html").write_text("<h1>Outside</h1>", encoding="utf-8")
            escaping = self.write_archive_config(
                root / "escape.toml",
                artifact_path="../outside",
            )
            limited = self.write_archive_config(
                root / "limited.toml",
                max_file_count=1,
            )
            self.write_archive_artifact(root)

            with self.assertRaisesRegex(SourcePolicyError, "inside root_path"):
                build_archive_manifest(
                    load_archive_source_config(escaping),
                    root_path=root,
                    clock=self.fixed_clock,
                )
            manifest = build_archive_manifest(
                load_archive_source_config(limited),
                root_path=root,
                clock=self.fixed_clock,
            )

        self.assertEqual(manifest.file_count, 1)
        self.assertTrue(
            any(skipped.reason == "max_file_count" for skipped in manifest.skipped_files)
        )

    def test_archive_file_artifact_imports_one_local_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            (root / "saved.html").write_text("<h1>Saved</h1>", encoding="utf-8")
            config = load_archive_source_config(
                self.write_archive_config(
                    root / "file.toml",
                    source_type="local.file",
                    artifact_path="saved.html",
                    artifact_kind="file",
                )
            )

            manifest = build_archive_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )
            observations = archive_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )

        self.assertEqual(manifest.file_count, 1)
        self.assertEqual(manifest.included_files[0].relative_path, "saved.html")
        self.assertEqual(manifest.included_files[0].repository_path, "saved.html")
        self.assertIn("html.document", {observation.kind for observation in observations})

    def test_archive_config_rejects_browser_flags_and_url_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            browser_flag = self.write_archive_config(
                root / "browser.toml",
                extra="\nbrowser_automation = true\n",
            )
            url_path = self.write_archive_config(
                root / "url-path.toml",
                artifact_path="https://example.invalid/saved",
            )

            with self.assertRaisesRegex(SourcePolicyError, "browser_automation"):
                load_archive_source_config(browser_flag)
            with self.assertRaisesRegex(SourcePolicyError, "network acquisition"):
                load_archive_source_config(url_path)

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

    def write_archive_config(
        self,
        path: Path,
        *,
        source_id: str = "example-test-report",
        source_type: str = "test_report.artifact",
        policy_status: str = "allowed",
        artifact_path: str = "reports/latest",
        artifact_kind: str = "directory",
        max_artifact_bytes: int = 1048576,
        max_file_count: int = 100,
        max_depth: int = 10,
        secret: bool = False,
        extra: str = "",
    ) -> Path:
        secret_block = (
            '\n[credentials]\ntoken = "fixture-secret"\n' if secret else ""
        )
        path.write_text(
            "\n".join(
                [
                    "[source]",
                    f'id = "{source_id}"',
                    f'type = "{source_type}"',
                    'display_name = "Example Test Report"',
                    "",
                    "[policy]",
                    f'status = "{policy_status}"',
                    f"max_artifact_bytes = {max_artifact_bytes}",
                    f"max_file_count = {max_file_count}",
                    f"max_depth = {max_depth}",
                    'symlink_policy = "do_not_follow"',
                    "hidden_files = false",
                    'retention_policy = "retain-local-path-and-hash"',
                    "requires_manual_review = false",
                    "",
                    "[artifact]",
                    f'path = "{artifact_path}"',
                    f'kind = "{artifact_kind}"',
                    'profile = "test-report"',
                    'entry_document = "index.html"',
                    secret_block,
                    extra,
                ]
            ),
            encoding="utf-8",
        )
        return path

    def write_archive_artifact(self, root: Path) -> Path:
        artifact = root / "reports" / "latest"
        (artifact / "assets").mkdir(parents=True)
        (artifact / "config").mkdir()
        (artifact / "static").mkdir()
        (artifact / ".git").mkdir()
        (artifact / "index.html").write_text(
            """\
<!doctype html>
<html>
  <head>
    <title>Example Test Report</title>
    <link rel="stylesheet" href="static/report.css">
    <script src="static/app.js"></script>
  </head>
  <body>
    <header class="report-header">
      <h1 id="summary">Example Test Report</h1>
      <span class="status-badge status-passed">Passed</span>
    </header>
    <img src="assets/logo.svg" alt="logo">
    <a href="https://example.invalid/report">External</a>
    <a href="javascript:alert('nope')">No execution</a>
  </body>
</html>
""",
            encoding="utf-8",
        )
        (artifact / "static" / "report.css").write_text(
            """\
.report-header { color: #f8fafc; }
.status-badge.status-passed { background: #16a34a; }
.hero { background-image: url("../assets/logo.svg"); }
""",
            encoding="utf-8",
        )
        (artifact / "static" / "app.js").write_text(
            "console.log('inert fixture asset');\n",
            encoding="utf-8",
        )
        (artifact / "config" / "settings.json").write_text(
            json.dumps(
                {
                    "report": {"entry": "../index.html"},
                    "credentials": {"token": "fixture-secret"},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (artifact / "assets" / "logo.svg").write_text(
            "<svg><title>logo</title></svg>\n",
            encoding="utf-8",
        )
        (artifact / ".hidden-secret").write_text("fixture-secret\n", encoding="utf-8")
        (artifact / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        return artifact

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
