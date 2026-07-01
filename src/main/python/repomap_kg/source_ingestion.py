"""Policy-gated source ingestion helpers."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repomap_kg.css_html_matching import extract_css_selector_match_observations
from repomap_kg.discovery import (
    FileInfo,
    classify_path,
    extract_config_file_observations_from_file,
    extract_css_file_observations_from_file,
    extract_feed_file_observations_from_file,
    extract_html_file_observations_from_file,
    extract_markdown_file_observations_from_file,
    extract_nix_file_observations_from_file,
    extract_python_file_observations_from_file,
    extract_shell_file_observations,
    markdown_anchor_index,
)
from repomap_kg.feed import extract_feed_file_observations
from repomap_kg.graph_keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
    warc_document_key,
    warc_record_key,
)
from repomap_kg.observations import RawObservation
from repomap_kg.python_extractor import PythonModuleIndex
from repomap_kg.storage import LoadSummary, load_file_observations


EXTRACTOR = "source-ingestion"
EXTRACTOR_VERSION = "0.1.0"
FEED_SOURCE_TYPES = frozenset({"feed.rss", "feed.atom", "feed.json"})
ARCHIVE_SOURCE_TYPES = frozenset(
    {
        "saved_page.archive",
        "test_report.artifact",
        "fixture.corpus",
        "manual.import",
        "static_artifact",
        "local.directory",
        "local.file",
    }
)
WARC_SOURCE_TYPES = ARCHIVE_SOURCE_TYPES
ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
BLOCKED_POLICY_STATUSES = frozenset(
    {
        "manual_review_required",
        "blocked_login_required",
        "blocked_anti_bot_circumvention",
        "blocked_terms_risk",
        "blocked_privacy_risk",
        "blocked_circumvention_required",
        "blocked_unknown",
    }
)
SECRET_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "access_key",
    "refresh_token",
    "bearer",
    "auth",
)
DISALLOWED_TRUE_FLAGS = (
    "requires_login",
    "login_required",
    "requires_captcha",
    "captcha_required",
    "uses_proxy_rotation",
    "proxy_rotation",
    "requires_browser",
    "browser_automation",
    "circumvention_required",
    "anti_bot_bypass",
    "stealth",
)
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ARCHIVE_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".gnupg",
        ".hg",
        ".mail",
        ".mypy_cache",
        ".password-store",
        ".pytest_cache",
        ".ruff_cache",
        ".ssh",
        ".svn",
        "__pycache__",
        "build",
        "cache",
        "Caches",
        "dist",
        "Mail",
        "mail",
        "node_modules",
        "tmp",
        "temp",
    }
)
SAFE_WARC_HEADER_NAMES = frozenset(
    {
        "content-length",
        "content-type",
        "etag",
        "last-modified",
        "warc-block-digest",
        "warc-concurrent-to",
        "warc-date",
        "warc-payload-digest",
        "warc-record-id",
        "warc-refers-to",
        "warc-target-uri",
        "warc-type",
    }
)
SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "proxy-authorization",
        "x-api-key",
        "api-key",
    }
)


class SourcePolicyError(ValueError):
    """Raised when a source definition is not policy-approved."""


class SourceAcquisitionError(ValueError):
    """Raised when configured source acquisition fails safely."""


@dataclass(frozen=True)
class FeedSourceConfig:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    preferred_method: str | None
    rate_limit: str | None
    timeout_seconds: int
    max_artifact_bytes: int
    max_items_per_run: int
    robots_policy: str | None
    terms_policy: str | None
    requires_manual_review: bool
    url: str
    method: str
    user_agent: str | None
    redacted_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedFetchResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass(frozen=True)
class FeedArtifact:
    source_id: str
    source_type: str
    source_run_id: str
    artifact_id: str
    path: Path
    relative_path: str
    byte_length: int
    sha256: str
    acquired_at: str
    http_status: int
    content_type: str | None
    policy_status: str
    configured_url_summary: str


@dataclass(frozen=True)
class FeedIngestionSummary:
    source_id: str
    source_type: str
    policy_status: str
    source_run_id: str
    artifact_path: str
    artifact_sha256: str
    artifact_bytes: int
    observations: int
    feed_observations: int
    raw_observations: tuple[RawObservation, ...]
    load_summary: LoadSummary

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "source_run_id": self.source_run_id,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "artifact_bytes": self.artifact_bytes,
            "observations": self.observations,
            "feed_observations": self.feed_observations,
            "repository_id": self.load_summary.repository_id,
            "run_id": self.load_summary.run_id,
            "files": self.load_summary.files,
        }


@dataclass(frozen=True)
class ArchiveSourceConfig:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    max_artifact_bytes: int
    max_file_count: int
    max_depth: int
    symlink_policy: str
    hidden_files: bool
    retention_policy: str
    requires_manual_review: bool
    artifact_path: str
    artifact_kind: str
    artifact_profile: str
    entry_document: str | None
    redacted_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchiveIncludedFile:
    relative_path: str
    repository_path: str
    byte_length: int
    sha256: str
    extractor_route: str
    media_type: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "repository_path": self.repository_path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "extractor_route": self.extractor_route,
            "media_type": self.media_type,
        }


@dataclass(frozen=True)
class ArchiveSkippedFile:
    relative_path: str
    reason: str

    def to_jsonable(self) -> dict[str, Any]:
        return {"relative_path": self.relative_path, "reason": self.reason}


@dataclass(frozen=True)
class ArchiveManifest:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    artifact_profile: str
    artifact_root: str
    entry_document: str | None
    included_files: tuple[ArchiveIncludedFile, ...]
    skipped_files: tuple[ArchiveSkippedFile, ...]
    policy_snapshot: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def file_count(self) -> int:
        return len(self.included_files)

    @property
    def total_byte_count(self) -> int:
        return sum(item.byte_length for item in self.included_files)

    @property
    def skipped_file_count(self) -> int:
        return len(self.skipped_files)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "artifact_profile": self.artifact_profile,
            "artifact_root": self.artifact_root,
            "entry_document": self.entry_document,
            "file_count": self.file_count,
            "total_byte_count": self.total_byte_count,
            "skipped_file_count": self.skipped_file_count,
            "included_files": [
                item.to_jsonable() for item in self.included_files
            ],
            "skipped_files": [item.to_jsonable() for item in self.skipped_files],
            "policy_snapshot": dict(self.policy_snapshot),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ArchiveImportSummary:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    included_files: int
    skipped_files: int
    observations: int
    raw_observations: tuple[RawObservation, ...]
    manifest: ArchiveManifest
    load_summary: LoadSummary

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "included_files": self.included_files,
            "skipped_files": self.skipped_files,
            "observations": self.observations,
            "repository_id": self.load_summary.repository_id,
            "run_id": self.load_summary.run_id,
            "files": self.load_summary.files,
        }


@dataclass(frozen=True)
class WarcSourceConfig:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    max_artifact_bytes: int
    max_file_count: int
    max_warc_records: int
    max_record_bytes: int
    max_total_payload_bytes: int
    retention_policy: str
    requires_manual_review: bool
    artifact_path: str
    artifact_kind: str
    artifact_profile: str
    redacted_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class WarcRecordSummary:
    ordinal: int
    record_type: str
    record_id: str
    record_key: str
    identity_source: str
    identity_strength: str
    duplicate_identity: bool
    target_uri_summary: str | None
    target_key: str | None
    target_uri_redacted: bool
    warc_date: str | None
    content_type: str | None
    payload_byte_length: int
    payload_sha256: str | None
    extractor_route: str | None
    materialized_path: str | None
    skip_reason: str | None
    safe_headers: Mapping[str, Any]
    duplicate_disambiguator: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "record_key": self.record_key,
            "identity_source": self.identity_source,
            "identity_strength": self.identity_strength,
            "duplicate_identity": self.duplicate_identity,
            "duplicate_disambiguator": self.duplicate_disambiguator,
            "target_uri_summary": self.target_uri_summary,
            "target_key": self.target_key,
            "target_uri_redacted": self.target_uri_redacted,
            "warc_date": self.warc_date,
            "content_type": self.content_type,
            "payload_byte_length": self.payload_byte_length,
            "payload_sha256": self.payload_sha256,
            "extractor_route": self.extractor_route,
            "materialized_path": self.materialized_path,
            "skip_reason": self.skip_reason,
            "safe_headers": dict(self.safe_headers),
        }


@dataclass(frozen=True)
class WarcManifest:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    artifact_profile: str
    artifact_path: str
    warc_version: str | None
    records: tuple[WarcRecordSummary, ...]
    policy_snapshot: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def parsed_record_count(self) -> int:
        return len(self.records)

    @property
    def skipped_record_count(self) -> int:
        return sum(
            1
            for record in self.records
            if record.skip_reason is not None
            and record.record_type
            not in {"warcinfo", "request", "revisit", "conversion"}
        )

    @property
    def routed_payload_count(self) -> int:
        return sum(1 for record in self.records if record.materialized_path is not None)

    @property
    def total_payload_bytes(self) -> int:
        return sum(record.payload_byte_length for record in self.records)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "artifact_profile": self.artifact_profile,
            "artifact_path": self.artifact_path,
            "warc_version": self.warc_version,
            "record_count": self.record_count,
            "parsed_record_count": self.parsed_record_count,
            "skipped_record_count": self.skipped_record_count,
            "routed_payload_count": self.routed_payload_count,
            "total_payload_bytes": self.total_payload_bytes,
            "records": [record.to_jsonable() for record in self.records],
            "policy_snapshot": dict(self.policy_snapshot),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class WarcImportSummary:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    record_count: int
    parsed_records: int
    skipped_records: int
    routed_payloads: int
    observations: int
    raw_observations: tuple[RawObservation, ...]
    manifest: WarcManifest | None
    load_summary: LoadSummary

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "record_count": self.record_count,
            "parsed_records": self.parsed_records,
            "skipped_records": self.skipped_records,
            "routed_payloads": self.routed_payloads,
            "observations": self.observations,
            "repository_id": self.load_summary.repository_id,
            "run_id": self.load_summary.run_id,
            "files": self.load_summary.files,
        }


FetchFeed = Callable[[FeedSourceConfig], FeedFetchResponse]
LoadObservations = Callable[..., LoadSummary]
Clock = Callable[[], datetime]


def load_feed_source_config(path: Path | str) -> FeedSourceConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, Mapping):
        raise SourcePolicyError("source config must be a TOML object")
    source = _mapping(payload, "source")
    policy = _mapping(payload, "policy")
    acquisition = _mapping(payload, "acquisition")

    source_id = _required_text(source, "id", "source.id")
    source_type = _required_text(source, "type", "source.type")
    display_name = _optional_text(source, "display_name")
    policy_status = _required_text(policy, "status", "policy.status")
    timeout_seconds = _required_positive_int(
        policy,
        "timeout_seconds",
        "policy.timeout_seconds",
    )
    max_artifact_bytes = _required_positive_int(
        policy,
        "max_artifact_bytes",
        "policy.max_artifact_bytes",
    )
    max_items_per_run = _positive_int_or_default(
        policy.get("max_items_per_run"),
        "policy.max_items_per_run",
        default=100,
    )
    url = _required_text(acquisition, "url", "acquisition.url")
    method = _optional_text(acquisition, "method") or "GET"
    user_agent = _optional_text(acquisition, "user_agent")
    requires_manual_review = _optional_bool(
        policy.get("requires_manual_review"),
        "policy.requires_manual_review",
        default=False,
    )

    _validate_source_id(source_id)
    _validate_source_type(source_type)
    _validate_policy_status(policy_status)
    _validate_url(url)
    _validate_method(method)
    _validate_disallowed_flags(payload)
    if requires_manual_review:
        raise SourcePolicyError("source requires manual review before acquisition")

    return FeedSourceConfig(
        source_id=source_id,
        source_type=source_type,
        display_name=display_name,
        policy_status=policy_status,
        preferred_method=_optional_text(policy, "preferred_method"),
        rate_limit=_optional_text(policy, "rate_limit"),
        timeout_seconds=timeout_seconds,
        max_artifact_bytes=max_artifact_bytes,
        max_items_per_run=max_items_per_run,
        robots_policy=_optional_text(policy, "robots_policy"),
        terms_policy=_optional_text(policy, "terms_policy"),
        requires_manual_review=requires_manual_review,
        url=url,
        method=method.upper(),
        user_agent=user_agent,
        redacted_config_keys=tuple(_secret_key_paths(payload)),
    )


def load_archive_source_config(path: Path | str) -> ArchiveSourceConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, Mapping):
        raise SourcePolicyError("source config must be a TOML object")
    _reject_archive_network_fields(payload)
    source = _mapping(payload, "source")
    policy = _mapping(payload, "policy")
    artifact = _mapping(payload, "artifact")

    source_id = _required_text(source, "id", "source.id")
    source_type = _required_text(source, "type", "source.type")
    display_name = _optional_text(source, "display_name")
    policy_status = _required_text(policy, "status", "policy.status")
    max_artifact_bytes = _required_positive_int(
        policy,
        "max_artifact_bytes",
        "policy.max_artifact_bytes",
    )
    max_file_count = _required_positive_int(
        policy,
        "max_file_count",
        "policy.max_file_count",
    )
    max_depth = _required_positive_int(policy, "max_depth", "policy.max_depth")
    symlink_policy = _required_text(policy, "symlink_policy", "policy.symlink_policy")
    hidden_files = _required_bool(policy, "hidden_files", "policy.hidden_files")
    retention_policy = _required_text(
        policy,
        "retention_policy",
        "policy.retention_policy",
    )
    requires_manual_review = _optional_bool(
        policy.get("requires_manual_review"),
        "policy.requires_manual_review",
        default=False,
    )
    artifact_path = _required_text(artifact, "path", "artifact.path")
    artifact_kind = _required_text(artifact, "kind", "artifact.kind")
    artifact_profile = _required_text(artifact, "profile", "artifact.profile")

    _validate_source_id(source_id)
    _validate_archive_source_type(source_type)
    _validate_policy_status(policy_status)
    _validate_disallowed_flags(payload)
    if requires_manual_review:
        raise SourcePolicyError("source requires manual review before import")
    if symlink_policy != "do_not_follow":
        raise SourcePolicyError("policy.symlink_policy must be do_not_follow")
    if artifact_kind not in {"directory", "file"}:
        raise SourcePolicyError("artifact.kind must be directory or file")
    _validate_local_artifact_path(artifact_path)

    return ArchiveSourceConfig(
        source_id=source_id,
        source_type=source_type,
        display_name=display_name,
        policy_status=policy_status,
        max_artifact_bytes=max_artifact_bytes,
        max_file_count=max_file_count,
        max_depth=max_depth,
        symlink_policy=symlink_policy,
        hidden_files=hidden_files,
        retention_policy=retention_policy,
        requires_manual_review=requires_manual_review,
        artifact_path=artifact_path,
        artifact_kind=artifact_kind,
        artifact_profile=artifact_profile,
        entry_document=_optional_text(artifact, "entry_document"),
        redacted_config_keys=tuple(_secret_key_paths(payload)),
    )


def load_warc_source_config(path: Path | str) -> WarcSourceConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, Mapping):
        raise SourcePolicyError("source config must be a TOML object")
    _reject_archive_network_fields(payload)
    source = _mapping(payload, "source")
    policy = _mapping(payload, "policy")
    artifact = _mapping(payload, "artifact")

    source_id = _required_text(source, "id", "source.id")
    source_type = _required_text(source, "type", "source.type")
    display_name = _optional_text(source, "display_name")
    policy_status = _required_text(policy, "status", "policy.status")
    max_artifact_bytes = _required_positive_int(
        policy,
        "max_artifact_bytes",
        "policy.max_artifact_bytes",
    )
    max_file_count = _required_positive_int(
        policy,
        "max_file_count",
        "policy.max_file_count",
    )
    max_warc_records = _required_positive_int(
        policy,
        "max_warc_records",
        "policy.max_warc_records",
    )
    max_record_bytes = _required_positive_int(
        policy,
        "max_record_bytes",
        "policy.max_record_bytes",
    )
    max_total_payload_bytes = _required_positive_int(
        policy,
        "max_total_payload_bytes",
        "policy.max_total_payload_bytes",
    )
    retention_policy = _required_text(
        policy,
        "retention_policy",
        "policy.retention_policy",
    )
    requires_manual_review = _optional_bool(
        policy.get("requires_manual_review"),
        "policy.requires_manual_review",
        default=False,
    )
    artifact_path = _required_text(artifact, "path", "artifact.path")
    artifact_kind = _required_text(artifact, "kind", "artifact.kind")
    artifact_profile = _required_text(artifact, "profile", "artifact.profile")

    _validate_source_id(source_id)
    _validate_warc_source_type(source_type)
    _validate_policy_status(policy_status)
    _validate_disallowed_flags(payload)
    if requires_manual_review:
        raise SourcePolicyError("source requires manual review before WARC import")
    if artifact_kind != "warc":
        raise SourcePolicyError("artifact.kind must be warc")
    _validate_local_artifact_path(artifact_path)

    return WarcSourceConfig(
        source_id=source_id,
        source_type=source_type,
        display_name=display_name,
        policy_status=policy_status,
        max_artifact_bytes=max_artifact_bytes,
        max_file_count=max_file_count,
        max_warc_records=max_warc_records,
        max_record_bytes=max_record_bytes,
        max_total_payload_bytes=max_total_payload_bytes,
        retention_policy=retention_policy,
        requires_manual_review=requires_manual_review,
        artifact_path=artifact_path,
        artifact_kind=artifact_kind,
        artifact_profile=artifact_profile,
        redacted_config_keys=tuple(_secret_key_paths(payload)),
    )


def fetch_feed_source(
    config: FeedSourceConfig,
    *,
    opener: Any | None = None,
) -> FeedFetchResponse:
    opener = opener or urllib.request.build_opener(_NoRedirectHandler())
    headers = {}
    if config.user_agent:
        headers["User-Agent"] = config.user_agent
    request = urllib.request.Request(
        config.url,
        headers=headers,
        method=config.method,
    )
    try:
        response = opener.open(request, timeout=config.timeout_seconds)
    except urllib.error.HTTPError as error:
        body = error.read(config.max_artifact_bytes + 1)
        return FeedFetchResponse(
            status=error.code,
            headers=_header_mapping(error.headers),
            body=body,
        )
    except urllib.error.URLError as error:
        raise SourceAcquisitionError(
            f"feed acquisition failed: {error.reason}"
        ) from error
    body = response.read(config.max_artifact_bytes + 1)
    return FeedFetchResponse(
        status=int(getattr(response, "status", response.getcode())),
        headers=_header_mapping(getattr(response, "headers", {})),
        body=body,
    )


def ingest_feed_source(
    config_path: Path | str,
    *,
    repository_name: str,
    root_path: Path | str,
    psql_args: Sequence[str],
    git_commit: str | None = None,
    psql_command: str = "psql",
    artifact_dir: Path | str | None = None,
    fetcher: FetchFeed = fetch_feed_source,
    loader: LoadObservations = load_file_observations,
    clock: Clock | None = None,
) -> FeedIngestionSummary:
    config = load_feed_source_config(config_path)
    response = fetcher(config)
    _validate_fetch_response(config, response)
    artifact = retain_feed_artifact(
        config,
        response,
        root_path=Path(root_path),
        artifact_dir=Path(artifact_dir) if artifact_dir is not None else None,
        clock=clock or _utc_now,
    )
    feed_observations = tuple(
        extract_feed_file_observations(
            artifact.relative_path,
            artifact.path.read_text(encoding="utf-8"),
        )
    )
    if not feed_observations:
        raise SourceAcquisitionError("acquired artifact is not a recognized feed")
    _validate_item_limit(config, feed_observations)
    observations = (
        _artifact_file_observation(artifact),
        *_annotate_observations(feed_observations, config, artifact),
    )
    load_summary = loader(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=str(root_path),
        git_commit=git_commit,
        psql_command=psql_command,
    )
    return FeedIngestionSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        source_run_id=artifact.source_run_id,
        artifact_path=artifact.relative_path,
        artifact_sha256=artifact.sha256,
        artifact_bytes=artifact.byte_length,
        observations=len(observations),
        feed_observations=len(feed_observations),
        raw_observations=tuple(observations),
        load_summary=load_summary,
    )


def build_archive_manifest(
    config: ArchiveSourceConfig,
    *,
    root_path: Path | str,
    clock: Clock | None = None,
) -> ArchiveManifest:
    root = Path(root_path).resolve()
    artifact_root = _resolve_archive_artifact_path(root, config.artifact_path)
    if config.artifact_kind == "directory":
        if not artifact_root.is_dir():
            raise SourcePolicyError("artifact.path must be an existing directory")
        included, skipped = _scan_archive_directory(config, root, artifact_root)
    else:
        if artifact_root.is_symlink():
            raise SourcePolicyError("artifact.path must not be a symlink")
        if not artifact_root.is_file():
            raise SourcePolicyError("artifact.path must be an existing file")
        included, skipped = _scan_archive_file(config, root, artifact_root)
    now = clock() if clock is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    artifact_run_id = now.strftime("%Y%m%dT%H%M%SZ")
    policy_snapshot = _archive_policy_snapshot(config)
    manifest_payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "policy_status": config.policy_status,
        "artifact_run_id": artifact_run_id,
        "artifact_profile": config.artifact_profile,
        "artifact_root": config.artifact_path,
        "entry_document": config.entry_document,
        "included_files": [item.to_jsonable() for item in included],
        "skipped_files": [item.to_jsonable() for item in skipped],
        "policy_snapshot": policy_snapshot,
    }
    artifact_manifest_id = hashlib.sha256(
        json_dumps_stable(manifest_payload).encode("utf-8")
    ).hexdigest()[:16]
    return ArchiveManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=artifact_run_id,
        artifact_manifest_id=artifact_manifest_id,
        artifact_profile=config.artifact_profile,
        artifact_root=config.artifact_path,
        entry_document=config.entry_document,
        included_files=included,
        skipped_files=skipped,
        policy_snapshot=policy_snapshot,
    )


def archive_observations_from_manifest(
    config: ArchiveSourceConfig,
    manifest: ArchiveManifest,
    *,
    root_path: Path | str,
) -> tuple[RawObservation, ...]:
    repository_root = Path(root_path).resolve()
    file_infos = [
        classify_path(repository_root, repository_root / item.repository_path)
        for item in manifest.included_files
    ]
    file_infos = sorted(file_infos, key=lambda file_info: file_info.path)
    module_index = PythonModuleIndex.from_python_paths(
        (file_info.path for file_info in file_infos if file_info.language == "python"),
        repository_root=repository_root,
    )
    repository_paths = frozenset(file_info.path for file_info in file_infos)
    markdown_anchors = markdown_anchor_index(repository_root, file_infos)
    observations: list[RawObservation] = []
    for file_info in file_infos:
        observations.extend(
            _observations_for_archive_file(
                repository_root,
                file_info,
                module_index=module_index,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
            )
        )
    observations.extend(extract_css_selector_match_observations(observations))
    return _annotate_archive_observations(observations, config, manifest)


def import_archive_source(
    config_path: Path | str,
    *,
    repository_name: str,
    root_path: Path | str,
    psql_args: Sequence[str],
    git_commit: str | None = None,
    psql_command: str = "psql",
    loader: LoadObservations = load_file_observations,
    clock: Clock | None = None,
) -> ArchiveImportSummary:
    config = load_archive_source_config(config_path)
    manifest = build_archive_manifest(config, root_path=root_path, clock=clock)
    observations = archive_observations_from_manifest(
        config,
        manifest,
        root_path=root_path,
    )
    load_summary = loader(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=str(root_path),
        git_commit=git_commit,
        psql_command=psql_command,
    )
    return ArchiveImportSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=manifest.artifact_run_id,
        artifact_manifest_id=manifest.artifact_manifest_id,
        included_files=manifest.file_count,
        skipped_files=manifest.skipped_file_count,
        observations=len(observations),
        raw_observations=tuple(observations),
        manifest=manifest,
        load_summary=load_summary,
    )


def build_warc_manifest(
    config: WarcSourceConfig,
    *,
    root_path: Path | str,
    clock: Clock | None = None,
) -> WarcManifest:
    root = Path(root_path).resolve()
    artifact_path = _resolve_archive_artifact_path(root, config.artifact_path)
    if artifact_path.is_symlink():
        raise SourcePolicyError("artifact.path must not be a symlink")
    if not artifact_path.is_file():
        raise SourcePolicyError("artifact.path must be an existing WARC file")
    if artifact_path.suffix != ".warc":
        raise SourcePolicyError("WARC1 supports local .warc files only")
    artifact_bytes = artifact_path.stat().st_size
    if artifact_bytes > config.max_artifact_bytes:
        raise SourcePolicyError("artifact exceeds policy.max_artifact_bytes")
    now = clock() if clock is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    artifact_run_id = now.strftime("%Y%m%dT%H%M%SZ")
    document_key = warc_document_key(config.artifact_path)
    materialization_root = (
        root
        / ".repomap"
        / "source-artifacts"
        / config.source_id
        / artifact_run_id
        / "warc-payloads"
    )
    records, warc_version, warnings, errors = _parse_warc_records(
        config=config,
        root=root,
        artifact_path=artifact_path,
        document_key=document_key,
        materialization_root=materialization_root,
    )
    policy_snapshot = _warc_policy_snapshot(config)
    manifest_payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "policy_status": config.policy_status,
        "artifact_run_id": artifact_run_id,
        "artifact_profile": config.artifact_profile,
        "artifact_path": config.artifact_path,
        "warc_version": warc_version,
        "records": [record.to_jsonable() for record in records],
        "policy_snapshot": policy_snapshot,
        "warnings": list(warnings),
        "errors": list(errors),
    }
    artifact_manifest_id = hashlib.sha256(
        json_dumps_stable(manifest_payload).encode("utf-8")
    ).hexdigest()[:16]
    return WarcManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=artifact_run_id,
        artifact_manifest_id=artifact_manifest_id,
        artifact_profile=config.artifact_profile,
        artifact_path=config.artifact_path,
        warc_version=warc_version,
        records=tuple(records),
        policy_snapshot=policy_snapshot,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def warc_observations_from_manifest(
    config: WarcSourceConfig,
    manifest: WarcManifest,
    *,
    root_path: Path | str,
) -> tuple[RawObservation, ...]:
    root = Path(root_path).resolve()
    document_key = warc_document_key(manifest.artifact_path)
    observations: list[RawObservation] = [
        RawObservation(
            kind="warc.document",
            source_id=f"{manifest.artifact_path}#warc-document",
            path=manifest.artifact_path,
            target=document_key,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            metadata={
                "format": "warc",
                "warc_version": manifest.warc_version,
                "parser": "stdlib-bytes",
                "parser_mode": "plain-warc-local-only",
                "record_count": manifest.record_count,
                "parsed_record_count": manifest.parsed_record_count,
                "skipped_record_count": manifest.skipped_record_count,
                "routed_payload_count": manifest.routed_payload_count,
                "artifact_manifest_id": manifest.artifact_manifest_id,
            },
        )
    ]
    record_by_materialized_path = {
        record.materialized_path: record
        for record in manifest.records
        if record.materialized_path is not None
    }
    for record in manifest.records:
        observations.extend(_warc_record_observations(manifest, record, document_key))
    for index, message in enumerate(manifest.errors):
        observations.append(
            RawObservation(
                kind="warc.parse_error",
                source_id=f"{manifest.artifact_path}#warc-parse-error:{index}",
                path=manifest.artifact_path,
                confidence="unknown",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                metadata={"error_kind": "warc-parse", "message": message},
            )
        )
    routed_infos = [
        classify_path(root, root / relative_path)
        for relative_path in sorted(record_by_materialized_path)
    ]
    module_index = PythonModuleIndex.from_python_paths((), repository_root=root)
    repository_paths = frozenset(file_info.path for file_info in routed_infos)
    markdown_anchors: dict[str, frozenset[str]] = {}
    routed_observations: list[RawObservation] = []
    for file_info in routed_infos:
        routed_observations.extend(
            _observations_for_archive_file(
                root,
                file_info,
                module_index=module_index,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
            )
        )
    routed_observations.extend(
        extract_css_selector_match_observations(routed_observations)
    )
    observations.extend(routed_observations)
    return _annotate_warc_observations(
        observations,
        config,
        manifest,
        record_by_materialized_path,
    )


def import_warc_source(
    config_path: Path | str,
    *,
    repository_name: str,
    root_path: Path | str,
    psql_args: Sequence[str],
    git_commit: str | None = None,
    psql_command: str = "psql",
    loader: LoadObservations = load_file_observations,
    clock: Clock | None = None,
) -> WarcImportSummary:
    config = load_warc_source_config(config_path)
    manifest = build_warc_manifest(config, root_path=root_path, clock=clock)
    observations = warc_observations_from_manifest(
        config,
        manifest,
        root_path=root_path,
    )
    load_summary = loader(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=str(root_path),
        git_commit=git_commit,
        psql_command=psql_command,
    )
    return WarcImportSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=manifest.artifact_run_id,
        artifact_manifest_id=manifest.artifact_manifest_id,
        record_count=manifest.record_count,
        parsed_records=manifest.parsed_record_count,
        skipped_records=manifest.skipped_record_count,
        routed_payloads=manifest.routed_payload_count,
        observations=len(observations),
        raw_observations=tuple(observations),
        manifest=manifest,
        load_summary=load_summary,
    )


def _parse_warc_records(
    *,
    config: WarcSourceConfig,
    root: Path,
    artifact_path: Path,
    document_key: str,
    materialization_root: Path,
) -> tuple[list[WarcRecordSummary], str | None, list[str], list[str]]:
    data = artifact_path.read_bytes()
    offset = 0
    records: list[WarcRecordSummary] = []
    warnings: list[str] = []
    errors: list[str] = []
    warc_version: str | None = None
    total_payload_bytes = 0
    routed_files = 0
    seen_identity_counts: dict[str, int] = {}

    while offset < len(data):
        while offset < len(data) and data[offset : offset + 1] in (b"\r", b"\n"):
            offset += 1
        if offset >= len(data):
            break
        if len(records) >= config.max_warc_records:
            errors.append(f"max_warc_records exceeded: {config.max_warc_records}")
            break

        parsed = _next_warc_record(data, offset)
        if isinstance(parsed, str):
            errors.append(parsed)
            break
        (
            next_offset,
            version,
            headers,
            raw_header_bytes,
            block,
        ) = parsed
        if warc_version is None:
            warc_version = version

        total_record_bytes = len(raw_header_bytes) + len(block)
        if total_record_bytes > config.max_record_bytes:
            errors.append(
                f"max_record_bytes exceeded at record {len(records) + 1}: "
                f"{total_record_bytes} > {config.max_record_bytes}"
            )
            offset = next_offset
            continue

        record, payload_bytes = _warc_record_summary(
            config=config,
            root=root,
            document_key=document_key,
            materialization_root=materialization_root,
            ordinal=len(records) + 1,
            headers=headers,
            block=block,
            seen_identity_counts=seen_identity_counts,
            total_payload_bytes=total_payload_bytes,
            routed_files=routed_files,
        )
        if record.materialized_path is not None:
            routed_files += 1
            total_payload_bytes += payload_bytes
        records.append(record)
        offset = next_offset

    return records, warc_version, warnings, errors


def _next_warc_record(
    data: bytes,
    offset: int,
) -> tuple[int, str, dict[str, str], bytes, bytes] | str:
    crlf_header_end = data.find(b"\r\n\r\n", offset)
    lf_header_end = data.find(b"\n\n", offset)
    candidates = [
        (position, 4)
        for position in (crlf_header_end,)
        if position >= 0
    ] + [
        (position, 2)
        for position in (lf_header_end,)
        if position >= 0
    ]
    if not candidates:
        return f"malformed WARC record at byte {offset}: missing header terminator"
    header_end, separator_length = min(candidates, key=lambda item: item[0])
    raw_header_bytes = data[offset:header_end]
    header_text = raw_header_bytes.decode("utf-8", errors="replace")
    lines = header_text.splitlines()
    if not lines or lines[0] not in {"WARC/1.0", "WARC/1.1"}:
        return f"malformed WARC record at byte {offset}: unsupported WARC version"
    headers = _parse_header_lines(lines[1:])
    content_length_text = headers.get("content-length")
    if content_length_text is None:
        return f"malformed WARC record at byte {offset}: missing Content-Length"
    try:
        content_length = int(content_length_text)
    except ValueError:
        return f"malformed WARC record at byte {offset}: invalid Content-Length"
    if content_length < 0:
        return f"malformed WARC record at byte {offset}: negative Content-Length"
    payload_start = header_end + separator_length
    payload_end = payload_start + content_length
    if payload_end > len(data):
        return f"malformed WARC record at byte {offset}: truncated payload"
    next_offset = payload_end
    if data[next_offset : next_offset + 2] == b"\r\n":
        next_offset += 2
    elif data[next_offset : next_offset + 1] == b"\n":
        next_offset += 1
    return next_offset, lines[0], headers, raw_header_bytes, data[payload_start:payload_end]


def _parse_header_lines(lines: Sequence[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    current_key: str | None = None
    for line in lines:
        if not line:
            continue
        if line[:1] in {" ", "\t"} and current_key is not None:
            headers[current_key] = f"{headers[current_key]} {line.strip()}"
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        current_key = key.strip().lower()
        headers[current_key] = value.strip()
    return headers


def _warc_record_summary(
    *,
    config: WarcSourceConfig,
    root: Path,
    document_key: str,
    materialization_root: Path,
    ordinal: int,
    headers: Mapping[str, str],
    block: bytes,
    seen_identity_counts: dict[str, int],
    total_payload_bytes: int,
    routed_files: int,
) -> tuple[WarcRecordSummary, int]:
    record_type = headers.get("warc-type", "unknown").strip().lower() or "unknown"
    target_summary, target_key, target_redacted = _warc_target(headers.get("warc-target-uri"))
    identity, identity_source, identity_strength = _warc_record_identity(
        headers=headers,
        record_type=record_type,
        target_uri_summary=target_summary,
        ordinal=ordinal,
    )
    seen_identity_counts[identity] = seen_identity_counts.get(identity, 0) + 1
    duplicate_count = seen_identity_counts[identity]
    duplicate = duplicate_count > 1
    duplicate_disambiguator: str | None = None
    record_identity = identity
    if duplicate:
        duplicate_disambiguator = f"duplicate-{duplicate_count}"
        record_identity = f"{identity}:{duplicate_disambiguator}"
    record_key = warc_record_key(document_key, record_identity)
    content_type = headers.get("content-type")
    payload = b""
    payload_content_type = content_type
    extractor_route: str | None = None
    materialized_path: str | None = None
    skip_reason: str | None = None

    if record_type == "response":
        http_headers, payload = _parse_http_message_payload(block, response=True)
        payload_content_type = _http_content_type(http_headers) or content_type
        extractor_route = _warc_payload_route(payload_content_type)
    elif record_type == "resource":
        payload = block
        extractor_route = _warc_payload_route(payload_content_type)
    elif record_type in {
        "warcinfo",
        "request",
        "metadata",
        "revisit",
        "conversion",
    }:
        skip_reason = "metadata-only"
    elif record_type == "continuation":
        skip_reason = "continuation-deferred"
    else:
        skip_reason = "unsupported-record-type"

    payload_sha256: str | None = None
    routed_payload_bytes = 0
    if extractor_route is not None:
        if not payload:
            skip_reason = "empty-payload"
        elif total_payload_bytes + len(payload) > config.max_total_payload_bytes:
            skip_reason = "max_total_payload_bytes"
        elif routed_files >= config.max_file_count:
            skip_reason = "max_file_count"
        else:
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            materialized_path = _materialize_warc_payload(
                config=config,
                root=root,
                materialization_root=materialization_root,
                ordinal=ordinal,
                extractor_route=extractor_route,
                payload=payload,
            )
            routed_payload_bytes = len(payload)

    if materialized_path is None and skip_reason is None and extractor_route is None:
        skip_reason = "metadata-only"

    return (
        WarcRecordSummary(
            ordinal=ordinal,
            record_type=record_type,
            record_id=_normalise_warc_record_id(headers.get("warc-record-id")),
            record_key=record_key,
            identity_source=identity_source,
            identity_strength=identity_strength,
            duplicate_identity=duplicate,
            duplicate_disambiguator=duplicate_disambiguator,
            target_uri_summary=target_summary,
            target_key=target_key,
            target_uri_redacted=target_redacted,
            warc_date=headers.get("warc-date"),
            content_type=payload_content_type,
            payload_byte_length=len(payload),
            payload_sha256=payload_sha256,
            extractor_route=extractor_route,
            materialized_path=materialized_path,
            skip_reason=skip_reason,
            safe_headers=_safe_warc_headers(headers),
        ),
        routed_payload_bytes,
    )


def _warc_record_identity(
    *,
    headers: Mapping[str, str],
    record_type: str,
    target_uri_summary: str | None,
    ordinal: int,
) -> tuple[str, str, str]:
    record_id = _normalise_warc_record_id(headers.get("warc-record-id"))
    if record_id:
        return record_id, "warc_record_id", "strong"
    warc_date = headers.get("warc-date")
    if warc_date and target_uri_summary:
        digest = hashlib.sha256(
            f"{warc_date}\0{target_uri_summary}\0{record_type}".encode("utf-8")
        ).hexdigest()[:16]
        return f"date-target-type:{digest}", "warc-date-target-uri-type", "fallback"
    return f"ordinal:{ordinal:04d}", "record-ordinal", "structural"


def _normalise_warc_record_id(record_id: str | None) -> str:
    if not record_id:
        return ""
    return f"record:{record_id.strip()}"


def _parse_http_message_payload(
    block: bytes,
    *,
    response: bool,
) -> tuple[dict[str, str], bytes]:
    delimiter = b"\r\n\r\n"
    separator_length = 4
    header_end = block.find(delimiter)
    if header_end < 0:
        delimiter = b"\n\n"
        separator_length = 2
        header_end = block.find(delimiter)
    if header_end < 0:
        return {}, b""
    header_text = block[:header_end].decode("utf-8", errors="replace")
    lines = header_text.splitlines()
    if not lines:
        return {}, b""
    if response and not lines[0].upper().startswith("HTTP/"):
        return {}, b""
    return (
        _parse_header_lines(lines[1:]),
        block[header_end + separator_length :],
    )


def _http_content_type(headers: Mapping[str, str]) -> str | None:
    return headers.get("content-type")


def _warc_payload_route(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    if media_type == "text/css":
        return "css"
    if media_type in {
        "application/json",
        "application/feed+json",
        "application/jsonfeed+json",
    }:
        return "json"
    if media_type in {
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
    }:
        return "xml"
    return None


def _materialize_warc_payload(
    *,
    config: WarcSourceConfig,
    root: Path,
    materialization_root: Path,
    ordinal: int,
    extractor_route: str,
    payload: bytes,
) -> str:
    extension = _warc_payload_extension(extractor_route)
    directory = materialization_root / f"record-{ordinal:04d}"
    directory.mkdir(parents=True, exist_ok=True)
    payload_path = directory / f"payload{extension}"
    payload_path.write_bytes(payload)
    return payload_path.relative_to(root).as_posix()


def _warc_payload_extension(extractor_route: str) -> str:
    if extractor_route == "html":
        return ".html"
    if extractor_route == "css":
        return ".css"
    if extractor_route == "json":
        return ".json"
    if extractor_route == "xml":
        return ".xml"
    return ".bin"


def _safe_warc_headers(headers: Mapping[str, str]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in sorted(headers.items()):
        key_lower = key.lower()
        if key_lower == "warc-target-uri":
            safe[key_lower] = _warc_target(value)[0]
            continue
        if _is_sensitive_header_name(key_lower):
            safe[key_lower] = "<redacted>"
            continue
        if key_lower in SAFE_WARC_HEADER_NAMES:
            safe[key_lower] = _redact_header_value(key_lower, value)
    return safe


def _is_sensitive_header_name(name: str) -> bool:
    name_lower = name.lower()
    return name_lower in SENSITIVE_HEADER_NAMES or _is_secret_marker(name_lower)


def _redact_header_value(key: str, value: str) -> str:
    if _is_secret_marker(key) or _is_secret_marker(value):
        return "<redacted>"
    return value


def _warc_target(uri: str | None) -> tuple[str | None, str | None, bool]:
    if not uri:
        return None, None, False
    summary, redacted = _redact_warc_target_uri(uri)
    return summary, _warc_target_key(summary), redacted


def _redact_warc_target_uri(uri: str) -> tuple[str, bool]:
    parsed = urllib.parse.urlsplit(uri)
    redacted = False
    if parsed.username or parsed.password:
        redacted = True
    netloc = parsed.hostname or parsed.netloc
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    query_items = urllib.parse.parse_qsl(
        parsed.query,
        keep_blank_values=True,
        strict_parsing=False,
    )
    sanitized_items: list[tuple[str, str]] = []
    for key, value in query_items:
        if _is_secret_marker(key) or _is_secret_marker(value):
            sanitized_items.append((key, "<redacted>"))
            redacted = True
        else:
            sanitized_items.append((key, value))
    query = "&".join(
        f"{urllib.parse.quote(key, safe='')}="
        f"{value if value == '<redacted>' else urllib.parse.quote(value, safe='')}"
        for key, value in sanitized_items
    )
    fragment = "" if _is_secret_marker(parsed.fragment) else parsed.fragment
    if fragment != parsed.fragment:
        redacted = True
    return (
        urllib.parse.urlunsplit(
            (parsed.scheme, netloc, parsed.path, query, fragment)
        ),
        redacted,
    )


def _warc_target_key(uri_summary: str | None) -> str | None:
    if not uri_summary:
        return None
    parsed = urllib.parse.urlsplit(uri_summary)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https", "mailto"}:
        return external_url_key(uri_summary)
    if scheme == "javascript":
        return dynamic_key("warc.target-uri", "javascript")
    if "$" in uri_summary or "{" in uri_summary or "}" in uri_summary:
        return dynamic_key("warc.target-uri", "template")
    if scheme == "file" or uri_summary.startswith("/"):
        return external_key("file", "absolute-warc-reference")
    if not scheme and uri_summary and not uri_summary.startswith("../"):
        return file_key(uri_summary)
    return unknown_key("warc.target-uri", "unsupported-scheme")


def _warc_record_observations(
    manifest: WarcManifest,
    record: WarcRecordSummary,
    document_key: str,
) -> list[RawObservation]:
    path = manifest.artifact_path
    metadata = _warc_record_metadata(manifest, record, document_key)
    observations = [
        RawObservation(
            kind="warc.record",
            source_id=f"{path}#warc-record:{record.ordinal}",
            path=path,
            target=record.record_key,
            name=f"{record.record_type} record {record.ordinal}",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            metadata=metadata,
        ),
        RawObservation(
            kind="warc.header",
            source_id=f"{path}#warc-header:{record.ordinal}",
            path=path,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            metadata={
                **metadata,
                "safe_headers": dict(record.safe_headers),
            },
        ),
    ]
    if record.target_key is not None:
        observations.append(
            RawObservation(
                kind="warc.reference",
                source_id=f"{path}#warc-reference:{record.ordinal}",
                path=path,
                target=record.target_key,
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                metadata={
                    **metadata,
                    "source_key": record.record_key,
                    "target_key": record.target_key,
                    "reference_kind": "warc-target-uri",
                    "target_kind": record.target_key.split(":", 1)[0],
                    "not_fetched": True,
                },
            )
        )
    if record.payload_byte_length or record.materialized_path is not None:
        observations.append(
            RawObservation(
                kind="warc.payload",
                source_id=f"{path}#warc-payload:{record.ordinal}",
                path=record.materialized_path or path,
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                metadata={
                    **metadata,
                    "warc_payload_path": record.materialized_path,
                    "payload_sha256": record.payload_sha256,
                    "payload_materialized": record.materialized_path is not None,
                    "not_executed": True,
                    "not_rendered": True,
                },
            )
        )
    return observations


def _warc_record_metadata(
    manifest: WarcManifest,
    record: WarcRecordSummary,
    document_key: str,
) -> dict[str, Any]:
    return {
        "format": "warc",
        "warc_version": manifest.warc_version,
        "document_key": document_key,
        "record_key": record.record_key,
        "warc_record_key": record.record_key,
        "record_ordinal": record.ordinal,
        "record_type": record.record_type,
        "record_id": record.record_id,
        "identity_source": record.identity_source,
        "identity_strength": record.identity_strength,
        "duplicate_identity": record.duplicate_identity,
        "duplicate_disambiguator": record.duplicate_disambiguator,
        "target_uri_summary": record.target_uri_summary,
        "target_uri_redacted": record.target_uri_redacted,
        "warc_date": record.warc_date,
        "content_type": record.content_type,
        "payload_byte_length": record.payload_byte_length,
        "extractor_route": record.extractor_route,
        "skip_reason": record.skip_reason,
        "artifact_manifest_id": manifest.artifact_manifest_id,
        "artifact_run_id": manifest.artifact_run_id,
    }


def _annotate_warc_observations(
    observations: Sequence[RawObservation],
    config: WarcSourceConfig,
    manifest: WarcManifest,
    record_by_materialized_path: Mapping[str, WarcRecordSummary],
) -> tuple[RawObservation, ...]:
    annotated: list[RawObservation] = []
    for observation in observations:
        record = record_by_materialized_path.get(observation.path or "")
        metadata = {
            **dict(observation.metadata),
            "source_id": config.source_id,
            "source_id_configured": config.source_id,
            "source_type": config.source_type,
            "source_display_name": config.display_name,
            "source_policy_status": config.policy_status,
            "source_run_id": manifest.artifact_run_id,
            "source_artifact_id": manifest.artifact_manifest_id,
            "artifact_policy_status": config.policy_status,
            "artifact_run_id": manifest.artifact_run_id,
            "artifact_manifest_id": manifest.artifact_manifest_id,
            "artifact_profile": config.artifact_profile,
            "artifact_relative_path": observation.path,
            "source_artifact_path": observation.path,
            "artifact_retention_policy": config.retention_policy,
            "retention_policy": config.retention_policy,
            "config_redacted_keys": list(config.redacted_config_keys),
        }
        if record is not None:
            metadata.update(
                {
                    "warc_record_ordinal": record.ordinal,
                    "warc_record_key": record.record_key,
                    "warc_record_type": record.record_type,
                    "warc_payload_path": record.materialized_path,
                    "artifact_byte_length": record.payload_byte_length,
                    "source_artifact_bytes": record.payload_byte_length,
                    "artifact_sha256": record.payload_sha256,
                    "source_artifact_sha256": record.payload_sha256,
                    "artifact_extractor_route": record.extractor_route,
                }
            )
        annotated.append(replace(observation, metadata=metadata))
    return tuple(annotated)


def _warc_policy_snapshot(config: WarcSourceConfig) -> dict[str, Any]:
    return {
        "status": config.policy_status,
        "max_artifact_bytes": config.max_artifact_bytes,
        "max_file_count": config.max_file_count,
        "max_warc_records": config.max_warc_records,
        "max_record_bytes": config.max_record_bytes,
        "max_total_payload_bytes": config.max_total_payload_bytes,
        "retention_policy": config.retention_policy,
        "requires_manual_review": config.requires_manual_review,
    }


def _is_secret_marker(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in SECRET_MARKERS)


def retain_feed_artifact(
    config: FeedSourceConfig,
    response: FeedFetchResponse,
    *,
    root_path: Path,
    artifact_dir: Path | None,
    clock: Clock,
) -> FeedArtifact:
    root = root_path.resolve()
    base_dir = (
        artifact_dir.resolve()
        if artifact_dir is not None
        else root / ".repomap" / "source-artifacts"
    )
    try:
        base_dir.relative_to(root)
    except ValueError as error:
        raise SourcePolicyError("artifact_dir must be inside root_path") from error
    now = clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    source_run_id = now.strftime("%Y%m%dT%H%M%SZ")
    acquired_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    sha256 = hashlib.sha256(response.body).hexdigest()
    artifact_id = sha256[:16]
    target_dir = base_dir / config.source_id / source_run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / _artifact_filename(config.source_type)
    artifact_path.write_bytes(response.body)
    return FeedArtifact(
        source_id=config.source_id,
        source_type=config.source_type,
        source_run_id=source_run_id,
        artifact_id=artifact_id,
        path=artifact_path,
        relative_path=artifact_path.relative_to(root).as_posix(),
        byte_length=len(response.body),
        sha256=sha256,
        acquired_at=acquired_at,
        http_status=response.status,
        content_type=_content_type(response.headers),
        policy_status=config.policy_status,
        configured_url_summary=_safe_url_summary(config.url),
    )


def _validate_fetch_response(
    config: FeedSourceConfig,
    response: FeedFetchResponse,
) -> None:
    if 300 <= response.status < 400:
        raise SourceAcquisitionError("feed acquisition redirect responses are not followed")
    if response.status < 200 or response.status >= 300:
        raise SourceAcquisitionError(
            f"feed acquisition failed with HTTP status {response.status}"
        )
    if len(response.body) > config.max_artifact_bytes:
        raise SourceAcquisitionError("feed artifact exceeds max_artifact_bytes")


def _validate_item_limit(
    config: FeedSourceConfig,
    observations: Sequence[RawObservation],
) -> None:
    item_count = sum(1 for observation in observations if observation.kind == "feed.item")
    if item_count > config.max_items_per_run:
        raise SourcePolicyError("feed item count exceeds max_items_per_run")


def _artifact_file_observation(artifact: FeedArtifact) -> RawObservation:
    language = "json" if artifact.source_type == "feed.json" else "xml"
    return RawObservation(
        kind="file",
        source_id=artifact.relative_path,
        path=artifact.relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=EXTRACTOR_VERSION,
        metadata={
            "language": language,
            "role": "source",
            "source_artifact_role": "source-artifact",
            "content_hash": artifact.sha256,
            "generated": False,
            "executable": False,
            **_artifact_metadata(artifact),
        },
    )


def _annotate_observations(
    observations: Sequence[RawObservation],
    config: FeedSourceConfig,
    artifact: FeedArtifact,
) -> tuple[RawObservation, ...]:
    metadata = _artifact_metadata(artifact)
    metadata.update(
        {
            "source_display_name": config.display_name,
            "source_rate_limit": config.rate_limit,
            "source_preferred_method": config.preferred_method,
            "source_max_items_per_run": config.max_items_per_run,
            "config_redacted_keys": list(config.redacted_config_keys),
        }
    )
    return tuple(
        replace(
            observation,
            metadata={**dict(observation.metadata), **metadata},
        )
        for observation in observations
    )


def _artifact_metadata(artifact: FeedArtifact) -> dict[str, Any]:
    return {
        "source_id_configured": artifact.source_id,
        "source_type": artifact.source_type,
        "source_policy_status": artifact.policy_status,
        "source_run_id": artifact.source_run_id,
        "source_artifact_id": artifact.artifact_id,
        "source_artifact_path": artifact.relative_path,
        "source_artifact_sha256": artifact.sha256,
        "source_artifact_bytes": artifact.byte_length,
        "source_acquired_at": artifact.acquired_at,
        "acquisition_method": "GET",
        "acquisition_http_status": artifact.http_status,
        "acquisition_content_type": artifact.content_type,
        "acquisition_url_summary": artifact.configured_url_summary,
        "artifact_retention_policy": "local-artifact",
    }


def _observations_for_archive_file(
    repository_root: Path,
    file_info: FileInfo,
    *,
    module_index: PythonModuleIndex,
    repository_paths: frozenset[str],
    markdown_anchors: dict[str, frozenset[str]],
) -> tuple[RawObservation, ...]:
    observations = [file_info.to_observation()]
    if file_info.language == "markdown":
        observations.extend(
            extract_markdown_file_observations_from_file(
                repository_root,
                file_info,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
            )
        )
    if file_info.language == "shell":
        observations.extend(extract_shell_file_observations(repository_root, file_info.path))
    if file_info.language == "python":
        observations.extend(
            extract_python_file_observations_from_file(
                repository_root,
                file_info.path,
                module_index=module_index,
            )
        )
    if file_info.language == "nix":
        observations.extend(
            extract_nix_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language in ("json", "xml"):
        feed_observations = extract_feed_file_observations_from_file(
            repository_root,
            file_info.path,
        )
        if feed_observations:
            observations.extend(feed_observations)
            return tuple(observations)
    if file_info.language in ("json", "jsonc", "jsonl", "toml", "plist", "xml"):
        observations.extend(
            extract_config_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "html":
        observations.extend(
            extract_html_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "css":
        observations.extend(
            extract_css_file_observations_from_file(repository_root, file_info.path)
        )
    return tuple(observations)


def _annotate_archive_observations(
    observations: Sequence[RawObservation],
    config: ArchiveSourceConfig,
    manifest: ArchiveManifest,
) -> tuple[RawObservation, ...]:
    by_repository_path = {
        item.repository_path: item for item in manifest.included_files
    }
    return tuple(
        replace(
            observation,
            metadata={
                **dict(observation.metadata),
                **_archive_observation_metadata(
                    observation,
                    config,
                    manifest,
                    by_repository_path,
                ),
            },
        )
        for observation in observations
    )


def _archive_observation_metadata(
    observation: RawObservation,
    config: ArchiveSourceConfig,
    manifest: ArchiveManifest,
    by_repository_path: Mapping[str, ArchiveIncludedFile],
) -> dict[str, Any]:
    included = by_repository_path.get(observation.path or "")
    artifact_relative_path = (
        included.repository_path
        if included is not None
        else observation.path or observation.source_id
    )
    metadata: dict[str, Any] = {
        "source_id": config.source_id,
        "source_id_configured": config.source_id,
        "source_type": config.source_type,
        "source_display_name": config.display_name,
        "source_policy_status": config.policy_status,
        "source_run_id": manifest.artifact_run_id,
        "source_artifact_id": manifest.artifact_manifest_id,
        "artifact_policy_status": config.policy_status,
        "artifact_run_id": manifest.artifact_run_id,
        "artifact_manifest_id": manifest.artifact_manifest_id,
        "artifact_profile": config.artifact_profile,
        "artifact_relative_path": artifact_relative_path,
        "source_artifact_path": artifact_relative_path,
        "artifact_retention_policy": config.retention_policy,
        "retention_policy": config.retention_policy,
        "config_redacted_keys": list(config.redacted_config_keys),
    }
    if included is not None:
        metadata.update(
            {
                "artifact_byte_length": included.byte_length,
                "source_artifact_bytes": included.byte_length,
                "artifact_sha256": included.sha256,
                "source_artifact_sha256": included.sha256,
                "artifact_extractor_route": included.extractor_route,
            }
        )
    return metadata


def _scan_archive_directory(
    config: ArchiveSourceConfig,
    root: Path,
    artifact_root: Path,
) -> tuple[tuple[ArchiveIncludedFile, ...], tuple[ArchiveSkippedFile, ...]]:
    included: list[ArchiveIncludedFile] = []
    skipped: list[ArchiveSkippedFile] = []
    total_bytes = 0

    def scan(directory: Path) -> None:
        nonlocal total_bytes
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            relative_path = child.relative_to(artifact_root).as_posix()
            if child.name in ARCHIVE_EXCLUDED_DIR_NAMES and child.is_dir():
                skipped.append(ArchiveSkippedFile(relative_path, "excluded-directory"))
                continue
            if _is_hidden_relative_path(relative_path) and not config.hidden_files:
                skipped.append(ArchiveSkippedFile(relative_path, "hidden"))
                continue
            if child.is_symlink():
                skipped.append(ArchiveSkippedFile(relative_path, "symlink"))
                continue
            if len(Path(relative_path).parts) > config.max_depth:
                skipped.append(ArchiveSkippedFile(relative_path, "max_depth"))
                continue
            if child.is_dir():
                scan(child)
                continue
            if not child.is_file():
                skipped.append(ArchiveSkippedFile(relative_path, "special-file"))
                continue
            if len(included) >= config.max_file_count:
                skipped.append(ArchiveSkippedFile(relative_path, "max_file_count"))
                continue
            byte_length = child.stat().st_size
            if total_bytes + byte_length > config.max_artifact_bytes:
                skipped.append(ArchiveSkippedFile(relative_path, "max_artifact_bytes"))
                continue
            included.append(_archive_included_file(root, artifact_root, child, byte_length))
            total_bytes += byte_length

    scan(artifact_root)
    return tuple(included), tuple(skipped)


def _scan_archive_file(
    config: ArchiveSourceConfig,
    root: Path,
    artifact_path: Path,
) -> tuple[tuple[ArchiveIncludedFile, ...], tuple[ArchiveSkippedFile, ...]]:
    if artifact_path.stat().st_size > config.max_artifact_bytes:
        return (), (ArchiveSkippedFile(artifact_path.name, "max_artifact_bytes"),)
    return (
        (
            _archive_included_file(
                root,
                artifact_path.parent,
                artifact_path,
                artifact_path.stat().st_size,
            ),
        ),
        (),
    )


def _archive_included_file(
    root: Path,
    artifact_root: Path,
    file_path: Path,
    byte_length: int,
) -> ArchiveIncludedFile:
    return ArchiveIncludedFile(
        relative_path=file_path.relative_to(artifact_root).as_posix(),
        repository_path=file_path.relative_to(root).as_posix(),
        byte_length=byte_length,
        sha256=hashlib.sha256(file_path.read_bytes()).hexdigest(),
        extractor_route=_archive_extractor_route(file_path),
        media_type=_archive_media_type(file_path),
    )


def _archive_extractor_route(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".css":
        return "css"
    if suffix in {".json", ".jsonc", ".jsonl", ".toml", ".plist", ".xml"}:
        return "config-or-feed"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".sh", ".bash", ".zsh"}:
        return "shell"
    if suffix == ".py":
        return "python"
    if suffix == ".nix":
        return "nix"
    if suffix in {".js", ".mjs", ".cjs"}:
        return "static-asset"
    return "file"


def _archive_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".css":
        return "text/css"
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonc":
        return "application/jsonc"
    if suffix == ".jsonl":
        return "application/jsonl"
    if suffix == ".toml":
        return "application/toml"
    if suffix in {".xml", ".plist"}:
        return "application/xml"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix in {".js", ".mjs", ".cjs"}:
        return "text/javascript"
    return "application/octet-stream"


def _resolve_archive_artifact_path(root: Path, artifact_path: str) -> Path:
    candidate = (root / artifact_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise SourcePolicyError("artifact.path must normalize inside root_path") from error
    return candidate


def _archive_policy_snapshot(config: ArchiveSourceConfig) -> dict[str, Any]:
    return {
        "status": config.policy_status,
        "max_artifact_bytes": config.max_artifact_bytes,
        "max_file_count": config.max_file_count,
        "max_depth": config.max_depth,
        "symlink_policy": config.symlink_policy,
        "hidden_files": config.hidden_files,
        "retention_policy": config.retention_policy,
        "requires_manual_review": config.requires_manual_review,
    }


def _is_hidden_relative_path(relative_path: str) -> bool:
    return any(part.startswith(".") for part in Path(relative_path).parts)


def json_dumps_stable(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise SourcePolicyError(f"{key} table is required")
    return value


def _required_text(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourcePolicyError(f"{label} is required")
    return value.strip()


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourcePolicyError(f"{key} must be a string")
    value = value.strip()
    return value or None


def _required_positive_int(
    payload: Mapping[str, Any],
    key: str,
    label: str,
) -> int:
    if key not in payload:
        raise SourcePolicyError(f"{label} is required")
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SourcePolicyError(f"{label} must be a positive integer")
    return value


def _positive_int_or_default(value: Any, label: str, *, default: int | None) -> int:
    if value is None:
        if default is None:
            raise SourcePolicyError(f"{label} is required")
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SourcePolicyError(f"{label} must be a non-negative integer")
    return value


def _required_bool(payload: Mapping[str, Any], key: str, label: str) -> bool:
    if key not in payload:
        raise SourcePolicyError(f"{label} is required")
    return _optional_bool(payload[key], label, default=False)


def _optional_bool(value: Any, label: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SourcePolicyError(f"{label} must be a boolean")
    return value


def _validate_source_id(source_id: str) -> None:
    if "://" in source_id or not SOURCE_ID_RE.fullmatch(source_id):
        raise SourcePolicyError("source id must be an explicit safe identifier")


def _validate_source_type(source_type: str) -> None:
    if source_type not in FEED_SOURCE_TYPES:
        raise SourcePolicyError("source type must be feed.rss, feed.atom, or feed.json")


def _validate_archive_source_type(source_type: str) -> None:
    if source_type not in ARCHIVE_SOURCE_TYPES:
        raise SourcePolicyError(
            "source type must be a supported local artifact source type"
        )


def _validate_warc_source_type(source_type: str) -> None:
    if source_type not in WARC_SOURCE_TYPES:
        raise SourcePolicyError("source type must be a supported local WARC source type")


def _validate_policy_status(policy_status: str) -> None:
    if policy_status in BLOCKED_POLICY_STATUSES:
        raise SourcePolicyError(f"source policy status blocks ingestion: {policy_status}")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise SourcePolicyError(
            "source policy status must be allowed or allowed_with_limits"
        )


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise SourcePolicyError("acquisition.url must use http or https")
    if not parsed.netloc:
        raise SourcePolicyError("acquisition.url must include a host")
    if parsed.username or parsed.password:
        raise SourcePolicyError("acquisition.url must not contain credentials")


def _validate_method(method: str) -> None:
    if method.upper() != "GET":
        raise SourcePolicyError("feed acquisition method must be GET")


def _validate_local_artifact_path(path: str) -> None:
    parsed = urllib.parse.urlparse(path)
    if parsed.scheme or path.startswith("//"):
        raise SourcePolicyError("artifact.path must be a local filesystem path")


def _reject_archive_network_fields(payload: Mapping[str, Any]) -> None:
    if "acquisition" in payload:
        raise SourcePolicyError("network acquisition fields are not allowed")
    for dotted_key, value in _flatten_mapping(payload):
        field = dotted_key.rsplit(".", 1)[-1].lower()
        if field in {"url", "urls", "method", "user_agent"}:
            raise SourcePolicyError("network acquisition fields are not allowed")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            raise SourcePolicyError("network acquisition fields are not allowed")


def _validate_disallowed_flags(payload: Mapping[str, Any]) -> None:
    for dotted_key, value in _flatten_mapping(payload):
        field = dotted_key.rsplit(".", 1)[-1]
        if field in DISALLOWED_TRUE_FLAGS and value is True:
            raise SourcePolicyError(f"{dotted_key} is not allowed for feed ingestion")


def _secret_key_paths(payload: Mapping[str, Any]) -> list[str]:
    paths = []
    for dotted_key, _value in _flatten_mapping(payload):
        field = dotted_key.rsplit(".", 1)[-1].lower()
        if any(marker in field for marker in SECRET_MARKERS):
            paths.append(dotted_key)
    return sorted(set(paths))


def _flatten_mapping(
    payload: Mapping[str, Any],
    *,
    prefix: str = "",
) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for key, value in payload.items():
        dotted_key = f"{prefix}.{key}" if prefix else str(key)
        items.append((dotted_key, value))
        if isinstance(value, Mapping):
            items.extend(_flatten_mapping(value, prefix=dotted_key))
    return items


def _artifact_filename(source_type: str) -> str:
    if source_type == "feed.json":
        return "feed.json"
    if source_type == "feed.atom":
        return "atom.xml"
    return "rss.xml"


def _safe_url_summary(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _content_type(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value
    return None


def _header_mapping(headers: Any) -> dict[str, str]:
    if hasattr(headers, "items"):
        return {str(key).lower(): str(value) for key, value in headers.items()}
    return {}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None
