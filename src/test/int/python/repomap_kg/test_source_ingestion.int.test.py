import tempfile
import unittest
import urllib.error
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from repomap_kg.bulk_ingestion import (
    BulkPolicyError,
    bulk_observations_from_plan,
    build_bulk_plan,
    import_bulk_source,
    load_bulk_source_config,
)
from repomap_kg.source_ingestion import (
    FeedFetchResponse,
    SourceAcquisitionError,
    SourcePolicyError,
    archive_observations_from_manifest,
    build_archive_manifest,
    build_warc_manifest,
    fetch_feed_source,
    import_archive_source,
    import_warc_source,
    ingest_feed_source,
    load_archive_source_config,
    load_feed_source_config,
    load_warc_source_config,
    warc_observations_from_manifest,
)
from repomap_kg.storage import LoadSummary


class SourceIngestionIntegrationTests(unittest.TestCase):
    def test_bulk_fixture_policy_plan_and_observations(self):
        config = load_bulk_source_config(bulk_fixture_root() / "mixed_corpus" / "bulk.toml")
        manifest = build_bulk_plan(config, repository_root=bulk_fixture_root() / "mixed_corpus")
        observations = bulk_observations_from_plan(
            config,
            manifest,
            repository_root=bulk_fixture_root() / "mixed_corpus",
        )

        self.assertEqual(config.source_id, "fixture-mixed-corpus")
        self.assertEqual(manifest.corpus_kind, "mixed_corpus")
        self.assertEqual(
            [item.relative_path for item in manifest.included_files],
            [
                "config/settings.yaml",
                "docs/readme.md",
                "mail/single-message.eml",
                "src/example.py",
                "web/app.js",
                "web/index.html",
            ],
        )
        self.assertTrue(
            any(
                item.relative_path == "vendor/ignored.rb"
                and item.reason == "excluded_directory"
                for item in manifest.skipped_files
            )
        )
        kinds = {observation.kind for observation in observations}
        self.assertIn("email.message", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("python.module", kinds)
        self.assertIn("markdown.document", kinds)
        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertIn('"bulk_run_id"', payload)
        self.assertIn('"bulk_relative_path": "mail/single-message.eml"', payload)
        self.assertIn('"bulk_sensitivity": "private"', payload)
        self.assertIn('"no_provider_api": true', json.dumps(manifest.to_jsonable(), sort_keys=True))
        self.assertNotIn(str(bulk_fixture_root()), payload)
        self.assertNotIn("mixed-corpus-secret-value", payload)

    def test_bulk_email_export_fixture_routes_eml_and_mbox(self):
        config = load_bulk_source_config(bulk_fixture_root() / "email_export" / "bulk.toml")
        manifest = build_bulk_plan(config, repository_root=bulk_fixture_root() / "email_export")
        observations = bulk_observations_from_plan(
            config,
            manifest,
            repository_root=bulk_fixture_root() / "email_export",
        )

        routes = {item.relative_path: item.route for item in manifest.included_files}
        self.assertEqual(routes["messages/single-message.eml"], "eml")
        self.assertEqual(routes["messages/thread-reply.eml"], "eml")
        self.assertEqual(routes["archives/sample.mbox"], "mbox")
        skipped = {item.relative_path: item.reason for item in manifest.skipped_files}
        self.assertEqual(skipped[".hidden/hidden.eml"], "hidden_excluded")
        self.assertEqual(skipped["node_modules/ignored.js"], "excluded_directory")
        self.assertEqual(skipped["archive/export.zip"], "archive_deferred")
        self.assertEqual(skipped["unsupported/ignored.pdf"], "unsupported_extension")
        kinds = {observation.kind for observation in observations}
        self.assertIn("email.message", kinds)
        self.assertIn("email.mailbox", kinds)
        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertIn('"corpus_kind": "email_export"', payload)
        self.assertIn('"bulk_extractor_route": "mbox"', payload)
        self.assertNotIn("fake-mailbox-secret-value", payload)

    def test_bulk_blocked_policy_fails_closed(self):
        with self.assertRaises(BulkPolicyError):
            load_bulk_source_config(bulk_fixture_root() / "blocked_policy" / "bulk.toml")

    def test_bulk_import_uses_existing_loader_and_owned_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(bulk_fixture_root() / "mixed_corpus", root / "mixed_corpus")
            captured = {}

            def loader(_psql_args, observations, **kwargs):
                captured["observations"] = tuple(observations)
                captured["kwargs"] = dict(kwargs)
                return LoadSummary(repository_id=42, run_id=43, files=6)

            summary = import_bulk_source(
                root / "mixed_corpus" / "bulk.toml",
                repository_name="fixture",
                root_path=root / "mixed_corpus",
                psql_args=("--no-network-placeholder",),
                psql_command="psql",
                loader=loader,
            )

            source_text = (root / "mixed_corpus" / "mail" / "single-message.eml").read_text(
                encoding="utf-8"
            )
            self.assertTrue(summary.output_path.name)
            self.assertTrue((summary.output_path / "manifest.json").is_file())
            self.assertTrue((summary.output_path / "included-files.jsonl").is_file())
            self.assertTrue((summary.output_path / "skipped-files.jsonl").is_file())

        self.assertEqual(summary.source_id, "fixture-mixed-corpus")
        self.assertEqual(summary.load_summary.repository_id, 42)
        self.assertGreater(len(captured["observations"]), 6)
        self.assertEqual(captured["kwargs"]["repository_name"], "fixture")
        self.assertIn("mixed-corpus-secret-value", source_text)
        payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"no_source_mutation": true', payload)
        self.assertIn('"no_external_fetch": true', payload)
        self.assertNotIn(str(root), payload)

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
        self.assertEqual(manifest.file_count, 8)
        self.assertEqual(
            [item.relative_path for item in manifest.included_files],
            [
                "assets/logo.svg",
                "config/settings.json",
                "feed/feed.json",
                "index.html",
                "static/app.js",
                "static/app.js.map",
                "static/chunk.js",
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
        self.assertIn("js.file", kinds)
        self.assertIn("js.module", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.reference", kinds)
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertIn('"artifact_manifest_id"', payload)
        self.assertIn(
            '"artifact_relative_path": '
            '"archive_artifacts/example-test-report/index.html"',
            payload,
        )
        self.assertIn(
            "file:archive_artifacts/example-test-report/static/app.js.map",
            payload,
        )
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_archive_import_uses_existing_loader_path_without_network(self):
        captured = {}

        def loader(_psql_args, observations, **kwargs):
            captured["observations"] = tuple(observations)
            captured["kwargs"] = dict(kwargs)
            return LoadSummary(repository_id=42, run_id=43, files=8)

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
        self.assertEqual(summary.included_files, 8)
        self.assertEqual(summary.load_summary.repository_id, 42)
        self.assertEqual(captured["kwargs"]["repository_name"], "fixture")
        self.assertGreater(len(captured["observations"]), 6)
        self.assertIn("js.file", {item.kind for item in captured["observations"]})
        payload = json.dumps(
            [observation.to_dict() for observation in captured["observations"]],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-test-report"', payload)
        self.assertIn('"profile": "test_report_asset"', payload)
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_warc_source_fixture_policy_manifest_and_observations(self):
        allowed = load_warc_source_config(warc_source_fixture("allowed-warc.toml"))

        self.assertEqual(allowed.source_id, "example-warc-archive")
        self.assertEqual(allowed.source_type, "saved_page.archive")
        self.assertEqual(allowed.max_warc_records, 100)
        for filename in ("blocked-policy.toml", "manual-review.toml"):
            with self.subTest(filename=filename):
                with self.assertRaises(SourcePolicyError):
                    load_warc_source_config(warc_source_fixture(filename))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            config = load_warc_source_config(root / "warc_sources" / "allowed-warc.toml")
            record_limited = load_warc_source_config(
                root / "warc_sources" / "record-limit.toml"
            )
            byte_limited = load_warc_source_config(
                root / "warc_sources" / "byte-limit.toml"
            )
            malformed = load_warc_source_config(
                root / "warc_sources" / "malformed-warc.toml"
            )

            manifest = build_warc_manifest(config, root_path=root, clock=fixed_clock)
            observations = warc_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )
            record_limit_manifest = build_warc_manifest(
                record_limited,
                root_path=root,
                clock=fixed_clock,
            )
            byte_limit_manifest = build_warc_manifest(
                byte_limited,
                root_path=root,
                clock=fixed_clock,
            )
            malformed_manifest = build_warc_manifest(
                malformed,
                root_path=root,
                clock=fixed_clock,
            )

        kinds = {observation.kind for observation in observations}
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertEqual(manifest.record_count, 8)
        self.assertEqual(manifest.routed_payload_count, 4)
        self.assertEqual(manifest.skipped_record_count, 1)
        self.assertIn("warc.document", kinds)
        self.assertIn("warc.record", kinds)
        self.assertIn("warc.payload", kinds)
        self.assertIn("warc.reference", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("js.module", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.reference", kinds)
        self.assertIn('"source_id": "example-warc-archive"', payload)
        self.assertIn('"warc_record_key"', payload)
        self.assertIn('"warc_payload_path"', payload)
        self.assertIn('"artifact_extractor_route": "javascript"', payload)
        self.assertIn(
            "file:.repomap/source-artifacts/example-warc-archive/"
            "20260630T120000Z/warc-payloads/record-0005/payload.js.map",
            payload,
        )
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)
        self.assertTrue(
            any("max_warc_records" in error for error in record_limit_manifest.errors)
        )
        self.assertTrue(
            any("max_record_bytes" in error for error in byte_limit_manifest.errors)
        )
        self.assertTrue(malformed_manifest.errors)

    def test_warc_import_uses_existing_loader_path_without_network(self):
        captured = {}

        def loader(_psql_args, observations, **kwargs):
            captured["observations"] = tuple(observations)
            captured["kwargs"] = dict(kwargs)
            return LoadSummary(repository_id=44, run_id=45, files=4)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            summary = import_warc_source(
                root / "warc_sources" / "allowed-warc.toml",
                repository_name="fixture",
                root_path=root,
                psql_args=("--no-network-placeholder",),
                psql_command="psql",
                loader=loader,
                clock=fixed_clock,
            )

        self.assertEqual(summary.source_id, "example-warc-archive")
        self.assertEqual(summary.record_count, 8)
        self.assertEqual(summary.routed_payloads, 4)
        self.assertEqual(summary.load_summary.repository_id, 44)
        self.assertEqual(captured["kwargs"]["repository_name"], "fixture")
        self.assertGreater(len(captured["observations"]), 10)
        self.assertIn("js.file", {item.kind for item in captured["observations"]})
        payload = json.dumps(
            [observation.to_dict() for observation in captured["observations"]],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-warc-archive"', payload)
        self.assertIn('"artifact_extractor_route": "javascript"', payload)
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_warc_policy_parser_and_target_error_paths_are_local_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            write_warc_source_config(
                root / "warc_sources" / "network-field.toml",
                extra="\n[acquisition]\nurl = \"https://example.invalid/archive.warc\"\n",
            )
            write_warc_source_config(
                root / "warc_sources" / "missing-file.toml",
                artifact_path="warc_artifacts/missing.warc",
            )
            (root / "warc_artifacts" / "example.warc.gz").write_text(
                "not used",
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "gz.toml",
                artifact_path="warc_artifacts/example.warc.gz",
            )
            write_warc_source_config(
                root / "warc_sources" / "too-large.toml",
                max_artifact_bytes=1,
            )
            write_warc_source_config(
                root / "warc_sources" / "repo-escape.toml",
                artifact_path="../outside.warc",
            )
            target_warc = root / "warc_artifacts" / "target-branches.warc"
            target_warc.write_bytes(
                b"".join(
                    (
                        int_warc_record(
                            "resource",
                            "urn:uuid:javascript",
                            "javascript:alert(1)",
                            b"<html></html>",
                            content_type="text/html",
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:absolute",
                            "/Library/example.css",
                            b".absolute {}\n",
                            content_type="text/css",
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:local",
                            "assets/local.css",
                            b".local {}\n",
                            content_type="text/css",
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:unknown",
                            "../escape.css",
                            b".escape {}\n",
                            content_type="text/css",
                        ),
                    )
                )
            )
            write_warc_source_config(
                root / "warc_sources" / "target-branches.toml",
                artifact_path="warc_artifacts/target-branches.warc",
            )
            invalid_length = root / "warc_artifacts" / "invalid-length.warc"
            invalid_length.write_text(
                "\n".join(
                    [
                        "WARC/1.1",
                        "WARC-Type: resource",
                        "WARC-Record-ID: <urn:uuid:invalid>",
                        "WARC-Date: 2026-06-30T12:00:00Z",
                        "Content-Type: text/css",
                        "Content-Length: nope",
                        "",
                        ".bad {}",
                    ]
                ),
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "invalid-length.toml",
                artifact_path="warc_artifacts/invalid-length.warc",
            )
            missing_length = root / "warc_artifacts" / "missing-length.warc"
            missing_length.write_text(
                "WARC/1.1\nWARC-Type: resource\n\nbody",
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "missing-length.toml",
                artifact_path="warc_artifacts/missing-length.warc",
            )
            negative_length = root / "warc_artifacts" / "negative-length.warc"
            negative_length.write_text(
                "\n".join(
                    [
                        "WARC/1.1",
                        "WARC-Type: resource",
                        "Content-Length: -1",
                        "",
                        "body",
                    ]
                ),
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "negative-length.toml",
                artifact_path="warc_artifacts/negative-length.warc",
            )
            bad_version = root / "warc_artifacts" / "bad-version.warc"
            bad_version.write_text(
                "WARC/0.9\nWARC-Type: resource\nContent-Length: 0\n\n",
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "bad-version.toml",
                artifact_path="warc_artifacts/bad-version.warc",
            )
            unterminated = root / "warc_artifacts" / "unterminated.warc"
            unterminated.write_text("WARC/1.1\nWARC-Type: resource", encoding="utf-8")
            write_warc_source_config(
                root / "warc_sources" / "unterminated.toml",
                artifact_path="warc_artifacts/unterminated.warc",
            )
            fallback_warc = root / "warc_artifacts" / "fallback-identity.warc"
            fallback_warc.write_bytes(
                b"".join(
                    (
                        int_warc_record(
                            "resource",
                            None,
                            "https://example.invalid/fallback.css",
                            b".fallback {}\n",
                            content_type="text/css",
                        ),
                        int_warc_record(
                            "resource",
                            None,
                            None,
                            b".ordinal {}\n",
                            content_type="text/css",
                            include_date=False,
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:redacted-header",
                            "https://example.invalid/header.css",
                            b".header {}\n",
                            content_type="text/css",
                            extra_headers={"API-Key": "fixture-secret"},
                        ),
                    )
                )
            )
            write_warc_source_config(
                root / "warc_sources" / "fallback-identity.toml",
                artifact_path="warc_artifacts/fallback-identity.warc",
            )

            with self.assertRaisesRegex(SourcePolicyError, "network acquisition"):
                load_warc_source_config(root / "warc_sources" / "network-field.toml")
            for filename, message in (
                ("missing-file.toml", "existing WARC file"),
                ("gz.toml", "local .warc files only"),
                ("too-large.toml", "max_artifact_bytes"),
                ("repo-escape.toml", "inside root_path"),
            ):
                with self.subTest(filename=filename):
                    with self.assertRaisesRegex(SourcePolicyError, message):
                        build_warc_manifest(
                            load_warc_source_config(root / "warc_sources" / filename),
                            root_path=root,
                            clock=fixed_clock,
                        )

            target_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "target-branches.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            invalid_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "invalid-length.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            malformed_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "malformed-warc.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            error_manifests = {
                filename: build_warc_manifest(
                    load_warc_source_config(root / "warc_sources" / filename),
                    root_path=root,
                    clock=fixed_clock,
                )
                for filename in (
                    "missing-length.toml",
                    "negative-length.toml",
                    "bad-version.toml",
                    "unterminated.toml",
                )
            }
            fallback_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "fallback-identity.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            invalid_observations = warc_observations_from_manifest(
                load_warc_source_config(root / "warc_sources" / "invalid-length.toml"),
                invalid_manifest,
                root_path=root,
            )

        target_keys = {record.target_key for record in target_manifest.records}
        self.assertTrue(any(key and key.startswith("dynamic:") for key in target_keys))
        self.assertTrue(
            any(key == "external:file:absolute-warc-reference" for key in target_keys)
        )
        self.assertTrue(any(key == "file:assets/local.css" for key in target_keys))
        self.assertTrue(any(key and key.startswith("unknown:") for key in target_keys))
        self.assertTrue(any("invalid Content-Length" in error for error in invalid_manifest.errors))
        self.assertTrue(any("truncated payload" in error for error in malformed_manifest.errors))
        self.assertTrue(any(observation.kind == "warc.parse_error" for observation in invalid_observations))
        self.assertTrue(
            any("missing Content-Length" in error for error in error_manifests["missing-length.toml"].errors)
        )
        self.assertTrue(
            any("negative Content-Length" in error for error in error_manifests["negative-length.toml"].errors)
        )
        self.assertTrue(
            any("unsupported WARC version" in error for error in error_manifests["bad-version.toml"].errors)
        )
        self.assertTrue(
            any("missing header terminator" in error for error in error_manifests["unterminated.toml"].errors)
        )
        self.assertEqual(
            [record.identity_source for record in fallback_manifest.records[:2]],
            ["warc-date-target-uri-type", "record-ordinal"],
        )
        self.assertIn("<redacted>", json.dumps(fallback_manifest.to_jsonable()))

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


def warc_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "warc_sources" / filename


def copy_warc_fixture_root(parent: Path) -> Path:
    root = parent / "source_ingestion"
    root.mkdir()
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_artifacts",
        root / "warc_artifacts",
    )
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_sources",
        root / "warc_sources",
    )
    return root


def write_warc_source_config(
    path: Path,
    *,
    artifact_path: str = "warc_artifacts/example.warc",
    policy_status: str = "allowed",
    max_artifact_bytes: int = 1048576,
    extra: str = "",
) -> Path:
    path.write_text(
        "\n".join(
            [
                "[source]",
                'id = "example-warc-error-case"',
                'type = "saved_page.archive"',
                'display_name = "Example WARC Error Case"',
                "",
                "[policy]",
                f'status = "{policy_status}"',
                f"max_artifact_bytes = {max_artifact_bytes}",
                "max_file_count = 10",
                "max_warc_records = 100",
                "max_record_bytes = 1048576",
                "max_total_payload_bytes = 1048576",
                'retention_policy = "materialize-safe-payloads"',
                "requires_manual_review = false",
                "",
                "[artifact]",
                f'path = "{artifact_path}"',
                'kind = "warc"',
                'profile = "warc-local-archive"',
                extra,
            ]
        ),
        encoding="utf-8",
    )
    return path


def int_warc_record(
    record_type: str,
    record_id: str | None,
    target_uri: str | None,
    body: bytes,
    *,
    content_type: str,
    include_date: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    headers = {
        "WARC-Type": record_type,
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
    }
    if record_id is not None:
        headers["WARC-Record-ID"] = f"<{record_id}>"
    if include_date:
        headers["WARC-Date"] = "2026-06-30T12:00:00Z"
    if target_uri is not None:
        headers["WARC-Target-URI"] = target_uri
    if extra_headers:
        headers.update(extra_headers)
    return (
        b"WARC/1.1\r\n"
        + b"".join(f"{key}: {value}\r\n".encode("utf-8") for key, value in headers.items())
        + b"\r\n"
        + body
        + b"\r\n\r\n"
    )


def source_ingestion_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "source_ingestion"


def bulk_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "bulk"


if __name__ == "__main__":
    unittest.main()
