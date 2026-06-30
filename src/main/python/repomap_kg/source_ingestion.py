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
