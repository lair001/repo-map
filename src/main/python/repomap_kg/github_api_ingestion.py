"""GitHub documented REST API acquisition for fixture and public REST modes."""

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
from pathlib import Path
from typing import Any

from repomap_kg import __version__
from repomap_kg.discovery import (
    classify_path,
    extract_config_file_observations_from_file,
)
from repomap_kg.observations import RawObservation
from repomap_kg.storage import LoadSummary, load_file_observations


EXTRACTOR = "github-api-fixture-ingestion"
EXTRACTOR_VERSION = "0.1.0"
DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_GITHUB_USER_AGENT = f"repomap-kg/{__version__}"
ALLOWED_SOURCE_TYPES = frozenset({"api.rest"})
ALLOWED_GITHUB_API_SOURCE_CLASSES = frozenset({"api.github.repository"})
ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
ALLOWED_REPOSITORY_VISIBILITIES = frozenset({"public", "private", "internal"})
ALLOWED_ACQUISITION_TRANSPORTS = frozenset({"fixture", "github_public_rest"})
ALLOWED_CREDENTIAL_MODES = frozenset(
    {"none_public_readonly", "pat_readonly_ref", "github_app_installation_ref"}
)
ALLOWED_CREDENTIAL_REF_PREFIXES = (
    "local_secret_ref:",
    "os_keychain_ref:",
    "env_ref:",
)
ALLOWED_ENDPOINT_PATHS = {
    "/repos/{owner}/{repo}": "repository_metadata",
    "/repos/{owner}/{repo}/issues": "issues",
    "/repos/{owner}/{repo}/pulls": "pull_requests",
    "/repos/{owner}/{repo}/releases": "releases",
    "/repos/{owner}/{repo}/actions/runs": "actions",
}
GITHUB_ENDPOINT_KINDS = {
    "repository": "github.repository",
    "issues": "github.issue",
    "pulls": "github.pull_request",
    "releases": "github.release",
    "actions_runs": "github.workflow_run",
}
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SECRET_MARKERS = frozenset(
    {
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
        "client_secret",
        "secret_key",
        "access_token",
        "id_token",
        "session",
        "cookie",
        "connection_string",
        "authorization",
        "set-cookie",
        "clone_url",
        "ssh_url",
        "git_url",
        "download_url",
        "archive_url",
        "tarball_url",
        "zipball_url",
        "patch_url",
        "diff_url",
        "logs_url",
        "artifacts_url",
    }
)
SENSITIVE_URL_MARKERS = (
    "token=",
    "access_token=",
    "authorization=",
    "signature=",
    "sig=",
    "X-Amz-Signature=",
)
RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-used",
    "x-ratelimit-reset",
    "x-ratelimit-resource",
)
BODY_FIELDS = frozenset({"body"})


class GitHubApiPolicyError(ValueError):
    """Raised when GitHub API fixture acquisition is not allowed and bounded."""


@dataclass(frozen=True)
class GitHubEndpointConfig:
    name: str
    method: str
    path: str
    purpose: str
    response_type: str
    max_page_size: int
    pagination: str
    downstream_route: str
    fixture_response_path: str | None
    data_class: str

    def plan_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "purpose": self.purpose,
            "response_type": self.response_type,
            "max_page_size": self.max_page_size,
            "pagination": self.pagination,
            "downstream_route": self.downstream_route,
            "data_class": self.data_class,
        }


@dataclass(frozen=True)
class GitHubApiSourceConfig:
    config_path: Path
    acquisition_transport: str
    base_url: str
    timeout_seconds: int
    follow_redirects: bool
    user_agent: str
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    owner: str
    repository: str
    repository_visibility: str
    read_only: bool
    mutation_allowed: bool
    credential_mode: str
    credentials_ref: str | None
    consent_ref: str
    authorized_operations: tuple[str, ...]
    authorized_data_classes: tuple[str, ...]
    consent_revoked: bool
    consent_mutation_allowed: bool
    max_requests_per_run: int
    max_requests_per_minute: int
    max_pages_per_endpoint: int
    max_items_per_endpoint: int
    max_bytes_per_run: int
    max_concurrent_requests: int
    max_retries: int
    retention_policy: str
    raw_response_retention: str
    redacted_response_retention: str
    redaction_profile: str
    sensitivity: str
    endpoints: tuple[GitHubEndpointConfig, ...]


@dataclass(frozen=True)
class GitHubRequestPlan:
    endpoint_name: str
    method: str
    path: str
    response_type: str
    downstream_route: str
    data_class: str
    request_id: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path": self.path,
            "response_type": self.response_type,
            "downstream_route": self.downstream_route,
            "data_class": self.data_class,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class GitHubApiPlanManifest:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    owner: str
    repository: str
    repository_visibility: str
    transport: str
    credential_mode: str
    api_run_id: str
    api_manifest_id: str
    requests: tuple[GitHubRequestPlan, ...]
    max_requests_per_run: int
    max_requests_per_minute: int
    max_pages_per_endpoint: int
    max_items_per_endpoint: int
    max_bytes_per_run: int
    max_concurrent_requests: int
    max_retries: int
    retention_policy: str
    redaction_profile: str
    sensitivity: str
    manifest_sha256: str = ""
    network_capable: bool = False
    no_network: bool = True
    no_mutation: bool = True
    no_credentials_resolved: bool = True
    no_scheduler: bool = True
    fixture_transport_only: bool = True

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "api_run_id": self.api_run_id,
            "api_manifest_id": self.api_manifest_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "api_source_class": self.api_source_class,
            "provider_name": self.provider_name,
            "provider_product": self.provider_product,
            "policy_status": self.policy_status,
            "owner": self.owner,
            "repository": self.repository,
            "repository_visibility": self.repository_visibility,
            "transport": self.transport,
            "credential_mode": self.credential_mode,
            "request_count": self.request_count,
            "requests": [request.to_jsonable() for request in self.requests],
            "limits": {
                "max_requests_per_run": self.max_requests_per_run,
                "max_requests_per_minute": self.max_requests_per_minute,
                "max_pages_per_endpoint": self.max_pages_per_endpoint,
                "max_items_per_endpoint": self.max_items_per_endpoint,
                "max_bytes_per_run": self.max_bytes_per_run,
                "max_concurrent_requests": self.max_concurrent_requests,
                "max_retries": self.max_retries,
            },
            "retention_policy": self.retention_policy,
            "redaction_profile": self.redaction_profile,
            "sensitivity": self.sensitivity,
            "manifest_sha256": self.manifest_sha256,
            "network_capable": self.network_capable,
            "no_network": self.no_network,
            "no_mutation": self.no_mutation,
            "no_credentials_resolved": self.no_credentials_resolved,
            "no_scheduler": self.no_scheduler,
            "fixture_transport_only": self.fixture_transport_only,
        }


@dataclass(frozen=True)
class GitHubTransportResponse:
    status_code: int
    body: bytes
    response_type: str = "application/json"
    headers: Mapping[str, str] = field(default_factory=dict)
    rate_limit: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GitHubResponseRecord:
    endpoint_name: str
    method: str
    path_template: str
    response_type: str
    data_class: str
    status_code: int
    response_byte_count: int
    response_sha256: str
    artifact_path: str
    transport: str
    redacted: bool
    redaction_profile: str
    retention_policy: str
    downstream_route: str
    rate_limit: Mapping[str, str] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path_template": self.path_template,
            "response_type": self.response_type,
            "data_class": self.data_class,
            "status_code": self.status_code,
            "response_byte_count": self.response_byte_count,
            "response_sha256": self.response_sha256,
            "artifact_path": self.artifact_path,
            "transport": self.transport,
            "redacted": self.redacted,
            "redaction_profile": self.redaction_profile,
            "retention_policy": self.retention_policy,
            "downstream_route": self.downstream_route,
            "rate_limit": dict(self.rate_limit),
        }


@dataclass(frozen=True)
class GitHubApiAcquireSummary:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    owner: str
    repository: str
    repository_visibility: str
    transport: str
    credential_mode: str
    api_run_id: str
    api_manifest_id: str
    requests: int
    responses: int
    observations: int
    output_path: Path
    output_path_summary: str
    manifest: GitHubApiPlanManifest
    response_records: tuple[GitHubResponseRecord, ...]
    load_summary: LoadSummary
    no_network: bool = True
    no_mutation: bool = True
    no_credentials_resolved: bool = True
    no_scheduler: bool = True
    network_capable: bool = False
    fixture_transport_only: bool = True

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "api_source_class": self.api_source_class,
            "provider_name": self.provider_name,
            "provider_product": self.provider_product,
            "policy_status": self.policy_status,
            "owner": self.owner,
            "repository": self.repository,
            "repository_visibility": self.repository_visibility,
            "transport": self.transport,
            "credential_mode": self.credential_mode,
            "api_run_id": self.api_run_id,
            "api_manifest_id": self.api_manifest_id,
            "requests": self.requests,
            "responses": self.responses,
            "observations": self.observations,
            "output_path": self.output_path_summary,
            "repository_id": self.load_summary.repository_id,
            "run_id": self.load_summary.run_id,
            "loaded_files": self.load_summary.files,
            "response_records": [
                record.to_jsonable() for record in self.response_records
            ],
            "no_network": self.no_network,
            "no_mutation": self.no_mutation,
            "no_credentials_resolved": self.no_credentials_resolved,
            "no_scheduler": self.no_scheduler,
            "network_capable": self.network_capable,
            "fixture_transport_only": self.fixture_transport_only,
        }


class FixtureGitHubApiTransport:
    """Fixture-only GitHub transport that reads local response files."""

    def fetch(
        self,
        config: GitHubApiSourceConfig,
        request: GitHubRequestPlan,
    ) -> GitHubTransportResponse:
        endpoint = endpoint_by_name(config, request.endpoint_name)
        response_path = resolve_fixture_response_path(config, endpoint)
        body = response_path.read_bytes()
        return GitHubTransportResponse(
            status_code=200,
            body=body,
            response_type=endpoint.response_type,
        )


class PublicGitHubRestTransport:
    """Unauthenticated public GitHub REST transport for planned GET requests."""

    def __init__(self, *, opener: Any | None = None) -> None:
        self.opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    def fetch(
        self,
        config: GitHubApiSourceConfig,
        request: GitHubRequestPlan,
    ) -> GitHubTransportResponse:
        if config.acquisition_transport != "github_public_rest":
            raise GitHubApiPolicyError("PublicGitHubRestTransport requires github_public_rest")
        if request.method != "GET":
            raise GitHubApiPolicyError("GitHub REST transport only allows GET")
        url = github_public_rest_url(config, request)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": config.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        validate_no_auth_headers(headers)
        http_request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            response = self.opener.open(
                http_request,
                timeout=config.timeout_seconds,
            )
        except urllib.error.HTTPError as error:
            headers_map = header_mapping(error.headers)
            body = error.read(config.max_bytes_per_run + 1)
            return GitHubTransportResponse(
                status_code=error.code,
                body=body,
                response_type=content_type_from_headers(headers_map),
                headers=headers_map,
                rate_limit=rate_limit_headers(headers_map),
            )
        except urllib.error.URLError as error:
            raise GitHubApiPolicyError(
                f"GitHub REST acquisition failed: {error.reason}"
            ) from error
        headers_map = header_mapping(getattr(response, "headers", {}))
        body = response.read(config.max_bytes_per_run + 1)
        return GitHubTransportResponse(
            status_code=int(getattr(response, "status", response.getcode())),
            body=body,
            response_type=content_type_from_headers(headers_map),
            headers=headers_map,
            rate_limit=rate_limit_headers(headers_map),
        )


def load_github_api_source_config(path: Path | str) -> GitHubApiSourceConfig:
    config_path = Path(path).resolve()
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise GitHubApiPolicyError(f"invalid GitHub API config: {error}") from error

    source = required_table(payload, "source")
    consent = required_table(payload, "consent")
    limits = required_table(payload, "limits")
    retention = required_table(payload, "retention")
    redaction = required_table(payload, "redaction")
    endpoints = required_endpoint_list(payload)

    source_id = required_string(source, "source_id")
    source_type = required_string(source, "source_type")
    api_source_class = required_string(source, "api_source_class")
    provider_name = required_string(source, "provider_name")
    provider_product = required_string(source, "provider_product")
    policy_status = required_string(source, "policy_status")
    owner = required_string(source, "owner")
    repository = required_string(source, "repository")
    repository_visibility = required_string(source, "repository_visibility")
    read_only = required_bool(source, "read_only")
    mutation_allowed = required_bool(source, "mutation_allowed")
    credential_mode = required_string(source, "credential_mode")

    validate_source_identity(
        source_type=source_type,
        api_source_class=api_source_class,
        provider_name=provider_name,
        provider_product=provider_product,
        policy_status=policy_status,
        owner=owner,
        repository=repository,
        repository_visibility=repository_visibility,
        read_only=read_only,
        mutation_allowed=mutation_allowed,
        credential_mode=credential_mode,
    )
    (
        acquisition_transport,
        base_url,
        timeout_seconds,
        follow_redirects,
        user_agent,
    ) = acquisition_config_from_payload(
        payload,
        credential_mode=credential_mode,
        repository_visibility=repository_visibility,
    )
    credentials_ref = credentials_ref_from_payload(
        payload,
        credential_mode=credential_mode,
        repository_visibility=repository_visibility,
        acquisition_transport=acquisition_transport,
    )

    consent_ref = required_string(consent, "consent_ref")
    authorized_operations = string_tuple(consent.get("authorized_operations"))
    authorized_data_classes = string_tuple(consent.get("authorized_data_classes"))
    consent_revoked = required_bool(consent, "revoked")
    consent_mutation_allowed = required_bool(consent, "mutation_allowed")
    validate_consent(
        consent_ref=consent_ref,
        authorized_operations=authorized_operations,
        authorized_data_classes=authorized_data_classes,
        consent_revoked=consent_revoked,
        consent_mutation_allowed=consent_mutation_allowed,
    )

    max_requests_per_run = required_positive_int(limits, "max_requests_per_run")
    max_requests_per_minute = required_positive_int(
        limits,
        "max_requests_per_minute",
    )
    max_pages_per_endpoint = required_positive_int(limits, "max_pages_per_endpoint")
    max_items_per_endpoint = required_positive_int(limits, "max_items_per_endpoint")
    max_bytes_per_run = required_positive_int(limits, "max_bytes_per_run")
    max_concurrent_requests = required_positive_int(limits, "max_concurrent_requests")
    max_retries = required_nonnegative_int(limits, "max_retries")
    validate_limits(
        max_requests_per_run=max_requests_per_run,
        endpoint_count=len(endpoints),
        max_pages_per_endpoint=max_pages_per_endpoint,
        max_concurrent_requests=max_concurrent_requests,
        max_retries=max_retries,
    )

    retention_policy = required_string(retention, "policy")
    raw_response_retention = required_string(retention, "raw_response_retention")
    redacted_response_retention = required_string(
        retention,
        "redacted_response_retention",
    )
    redaction_profile = required_string(redaction, "profile")
    sensitivity = required_string(redaction, "sensitivity")
    validate_retention_and_redaction(
        retention_policy=retention_policy,
        raw_response_retention=raw_response_retention,
        redacted_response_retention=redacted_response_retention,
        redaction_profile=redaction_profile,
        sensitivity=sensitivity,
    )

    parsed_endpoints = tuple(
        parse_github_endpoint(
            endpoint,
            owner=owner,
            repository=repository,
            authorized_data_classes=authorized_data_classes,
            acquisition_transport=acquisition_transport,
        )
        for endpoint in endpoints
    )
    return GitHubApiSourceConfig(
        config_path=config_path,
        acquisition_transport=acquisition_transport,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        follow_redirects=follow_redirects,
        user_agent=user_agent,
        source_id=source_id,
        source_type=source_type,
        api_source_class=api_source_class,
        provider_name=provider_name,
        provider_product=provider_product,
        policy_status=policy_status,
        owner=owner,
        repository=repository,
        repository_visibility=repository_visibility,
        read_only=read_only,
        mutation_allowed=mutation_allowed,
        credential_mode=credential_mode,
        credentials_ref=credentials_ref,
        consent_ref=consent_ref,
        authorized_operations=authorized_operations,
        authorized_data_classes=authorized_data_classes,
        consent_revoked=consent_revoked,
        consent_mutation_allowed=consent_mutation_allowed,
        max_requests_per_run=max_requests_per_run,
        max_requests_per_minute=max_requests_per_minute,
        max_pages_per_endpoint=max_pages_per_endpoint,
        max_items_per_endpoint=max_items_per_endpoint,
        max_bytes_per_run=max_bytes_per_run,
        max_concurrent_requests=max_concurrent_requests,
        max_retries=max_retries,
        retention_policy=retention_policy,
        raw_response_retention=raw_response_retention,
        redacted_response_retention=redacted_response_retention,
        redaction_profile=redaction_profile,
        sensitivity=sensitivity,
        endpoints=parsed_endpoints,
    )


def build_github_api_plan_from_config(config_path: Path | str) -> GitHubApiPlanManifest:
    return build_github_api_plan(load_github_api_source_config(config_path))


def build_github_api_plan(config: GitHubApiSourceConfig) -> GitHubApiPlanManifest:
    requests = tuple(
        GitHubRequestPlan(
            endpoint_name=endpoint.name,
            method=endpoint.method,
            path=endpoint.path,
            response_type=endpoint.response_type,
            downstream_route=endpoint.downstream_route,
            data_class=endpoint.data_class,
            request_id=sha256_json(
                {
                    "source_id": config.source_id,
                    "owner": config.owner,
                    "repository": config.repository,
                    "transport": config.acquisition_transport,
                    "endpoint": endpoint.plan_payload(),
                }
            )[:24],
        )
        for endpoint in config.endpoints
    )
    run_id = deterministic_github_api_run_id(config, requests)
    manifest_id = sha256_text(f"{config.source_id}:{run_id}")[:24]
    manifest = GitHubApiPlanManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
        owner=config.owner,
        repository=config.repository,
        repository_visibility=config.repository_visibility,
        transport=config.acquisition_transport,
        credential_mode=config.credential_mode,
        api_run_id=run_id,
        api_manifest_id=manifest_id,
        requests=requests,
        max_requests_per_run=config.max_requests_per_run,
        max_requests_per_minute=config.max_requests_per_minute,
        max_pages_per_endpoint=config.max_pages_per_endpoint,
        max_items_per_endpoint=config.max_items_per_endpoint,
        max_bytes_per_run=config.max_bytes_per_run,
        max_concurrent_requests=config.max_concurrent_requests,
        max_retries=config.max_retries,
        retention_policy=config.retention_policy,
        redaction_profile=config.redaction_profile,
        sensitivity=config.sensitivity,
        network_capable=config.acquisition_transport == "github_public_rest",
        no_network=config.acquisition_transport == "fixture",
        fixture_transport_only=config.acquisition_transport == "fixture",
    )
    return replace(manifest, manifest_sha256=manifest_digest(manifest))


def acquire_github_api_source(
    config_path: Path | str,
    *,
    repository_name: str,
    root_path: Path | str,
    psql_args: Sequence[str],
    git_commit: str | None = None,
    psql_command: str = "psql",
    loader: Callable[..., LoadSummary] = load_file_observations,
    transport: Any | None = None,
) -> GitHubApiAcquireSummary:
    config = load_github_api_source_config(config_path)
    repo_root = Path(root_path).resolve()
    manifest = build_github_api_plan(config)
    selected_transport = transport or github_transport_for_config(config)
    fetched: list[tuple[GitHubRequestPlan, GitHubTransportResponse, Any]] = []
    total_bytes = 0
    for request in manifest.requests:
        response = selected_transport.fetch(config, request)
        validate_transport_response(config, request, response)
        total_bytes += len(response.body)
        if total_bytes > config.max_bytes_per_run:
            raise GitHubApiPolicyError("response bytes exceed max_bytes_per_run")
        parsed = parse_json_response(response.body, request.endpoint_name)
        item_count = count_response_items(parsed)
        if item_count > config.max_items_per_endpoint:
            raise GitHubApiPolicyError("response items exceed max_items_per_endpoint")
        fetched.append((request, response, parsed))

    output_path, records, redacted_payloads = write_github_api_run_files(
        config,
        manifest,
        fetched=fetched,
        repository_root=repo_root,
    )
    observations = github_api_observations_from_records(
        config,
        manifest,
        response_records=records,
        redacted_payloads=redacted_payloads,
        repository_root=repo_root,
        output_path=output_path,
    )
    load_summary = loader(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=str(repo_root),
        git_commit=git_commit,
        psql_command=psql_command,
    )
    return GitHubApiAcquireSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
        owner=config.owner,
        repository=config.repository,
        repository_visibility=config.repository_visibility,
        transport=config.acquisition_transport,
        credential_mode=config.credential_mode,
        api_run_id=manifest.api_run_id,
        api_manifest_id=manifest.api_manifest_id,
        requests=manifest.request_count,
        responses=len(records),
        observations=len(observations),
        output_path=output_path,
        output_path_summary=output_path.relative_to(repo_root).as_posix(),
        manifest=manifest,
        response_records=tuple(records),
        load_summary=load_summary,
        no_network=config.acquisition_transport == "fixture",
        network_capable=config.acquisition_transport == "github_public_rest",
        fixture_transport_only=config.acquisition_transport == "fixture",
    )


def write_github_api_run_files(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    *,
    fetched: Sequence[tuple[GitHubRequestPlan, GitHubTransportResponse, Any]],
    repository_root: Path,
) -> tuple[Path, tuple[GitHubResponseRecord, ...], dict[str, Any]]:
    output_path = (
        repository_root
        / ".repomap"
        / "api-runs"
        / config.source_id
        / manifest.api_run_id
    ).resolve()
    ensure_contained(output_path, repository_root, "GitHub API output path")
    artifacts_path = output_path / "artifacts"
    artifacts_path.mkdir(parents=True, exist_ok=True)
    records: list[GitHubResponseRecord] = []
    redacted_payloads: dict[str, Any] = {}
    for request, response, parsed in fetched:
        redacted_payload = redact_github_value(parsed)
        redacted_payloads[request.endpoint_name] = redacted_payload
        artifact_name = github_artifact_name(request.endpoint_name)
        artifact_path = artifacts_path / artifact_name
        write_json(artifact_path, redacted_payload)
        relative_artifact = artifact_path.relative_to(output_path).as_posix()
        records.append(
            GitHubResponseRecord(
                endpoint_name=request.endpoint_name,
                method=request.method,
                path_template=request.path,
                response_type=request.response_type,
                data_class=request.data_class,
                status_code=response.status_code,
                response_byte_count=len(response.body),
                response_sha256=sha256_bytes(response.body),
                artifact_path=relative_artifact,
                transport=config.acquisition_transport,
                redacted=True,
                redaction_profile=config.redaction_profile,
                retention_policy=config.retention_policy,
                downstream_route=request.downstream_route,
                rate_limit=dict(response.rate_limit),
            )
        )
    write_json(output_path / "plan.json", manifest.to_jsonable())
    write_json(
        output_path / "manifest.json",
        {
            **manifest.to_jsonable(),
            "responses": [record.to_jsonable() for record in records],
        },
    )
    write_jsonl(
        output_path / "requests.jsonl",
        [request.to_jsonable() for request in manifest.requests],
    )
    write_jsonl(
        output_path / "redacted-responses.jsonl",
        [record.to_jsonable() for record in records],
    )
    write_jsonl(output_path / "diagnostics.jsonl", [])
    return output_path, tuple(records), redacted_payloads


def github_api_observations_from_records(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    *,
    response_records: Sequence[GitHubResponseRecord],
    redacted_payloads: Mapping[str, Any],
    repository_root: Path,
    output_path: Path,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(github_api_provenance_observations(config, manifest, response_records))
    for record in response_records:
        payload = redacted_payloads.get(record.endpoint_name)
        observations.extend(
            github_provider_observations(
                config,
                manifest,
                record=record,
                payload=payload,
            )
        )
        if record.downstream_route != "config":
            continue
        artifact_path = output_path / record.artifact_path
        file_info = classify_path(repository_root, artifact_path)
        routed: list[RawObservation] = [file_info.to_observation()]
        routed.extend(
            extract_config_file_observations_from_file(
                repository_root,
                file_info.path,
            )
        )
        observations.extend(
            annotate_github_observation(
                observation,
                config=config,
                manifest=manifest,
                record=record,
            )
            for observation in routed
        )
    return tuple(observations)


def github_api_provenance_observations(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    response_records: Sequence[GitHubResponseRecord],
) -> tuple[RawObservation, ...]:
    base_metadata = github_base_metadata(config, manifest)
    observations = [
        RawObservation(
            kind="api.source",
            source_id=f"{config.source_id}#api-source",
            path=".repomap/api-runs",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            name=config.source_id,
            metadata=base_metadata,
        ),
        RawObservation(
            kind="api.run",
            source_id=f"{config.source_id}#{manifest.api_run_id}",
            path=".repomap/api-runs",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            name=manifest.api_run_id,
            metadata={**base_metadata, "request_count": manifest.request_count},
        ),
    ]
    for request in manifest.requests:
        observations.append(
            RawObservation(
                kind="api.request",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{request.endpoint_name}#request"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=request.endpoint_name,
                metadata={**base_metadata, **request.to_jsonable()},
            )
        )
    for record in response_records:
        observations.append(
            RawObservation(
                kind="api.response",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}#response"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=record.endpoint_name,
                metadata={
                    **base_metadata,
                    **record.to_jsonable(),
                },
            )
        )
        observations.append(
            RawObservation(
                kind="api.artifact",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}#artifact"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=record.artifact_path,
                metadata={
                    **base_metadata,
                    "endpoint_name": record.endpoint_name,
                    "artifact_path": record.artifact_path,
                    "redacted": record.redacted,
                    "downstream_route": record.downstream_route,
                },
            )
        )
    return tuple(observations)


def github_provider_observations(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    *,
    record: GitHubResponseRecord,
    payload: Any,
) -> tuple[RawObservation, ...]:
    kind = GITHUB_ENDPOINT_KINDS.get(record.endpoint_name)
    if kind is None:
        return ()
    items = github_observation_items(record.endpoint_name, payload)
    observations: list[RawObservation] = []
    base_metadata = {
        **github_base_metadata(config, manifest),
        **record.to_jsonable(),
    }
    for index, item in enumerate(items):
        item_metadata = item if isinstance(item, dict) else {"value": item}
        safe_name = github_item_name(record.endpoint_name, item, index)
        observations.append(
            RawObservation(
                kind=kind,
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}#{index}"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=safe_name,
                metadata={**base_metadata, "github_item": item_metadata},
            )
        )
    return tuple(observations)


def github_observation_items(endpoint_name: str, payload: Any) -> tuple[Any, ...]:
    if endpoint_name == "repository":
        return (payload,)
    if endpoint_name == "actions_runs" and isinstance(payload, dict):
        runs = payload.get("workflow_runs")
        if isinstance(runs, list):
            return tuple(runs)
    if isinstance(payload, list):
        return tuple(payload)
    return (payload,)


def github_item_name(endpoint_name: str, item: Any, index: int) -> str:
    if isinstance(item, dict):
        for key in ("full_name", "number", "tag_name", "id", "name"):
            value = item.get(key)
            if isinstance(value, (str, int)):
                return str(value)
    return f"{endpoint_name}:{index}"


def annotate_github_observation(
    observation: RawObservation,
    *,
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    record: GitHubResponseRecord,
) -> RawObservation:
    metadata = dict(observation.metadata)
    metadata.update(
        {
            "source_id": config.source_id,
            "source_type": config.source_type,
            "api_source_class": config.api_source_class,
            "provider_name": config.provider_name,
            "provider_product": config.provider_product,
            "owner": config.owner,
            "repository": config.repository,
            "repository_visibility": config.repository_visibility,
            "transport": config.acquisition_transport,
            "api_run_id": manifest.api_run_id,
            "api_manifest_id": manifest.api_manifest_id,
            "endpoint_name": record.endpoint_name,
            "method": record.method,
            "path_template": record.path_template,
            "downstream_route": record.downstream_route,
            "api_policy_status": config.policy_status,
            "api_retention_policy": config.retention_policy,
            "api_sensitivity": config.sensitivity,
        }
    )
    return replace(observation, metadata=metadata)


def github_base_metadata(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
) -> dict[str, Any]:
    return {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "api_source_class": config.api_source_class,
        "provider_name": config.provider_name,
        "provider_product": config.provider_product,
        "owner": config.owner,
        "repository": config.repository,
        "repository_visibility": config.repository_visibility,
        "transport": config.acquisition_transport,
        "credential_mode": config.credential_mode,
        "api_run_id": manifest.api_run_id,
        "api_manifest_id": manifest.api_manifest_id,
        "api_policy_status": config.policy_status,
        "api_retention_policy": config.retention_policy,
        "api_sensitivity": config.sensitivity,
        "redaction_profile": config.redaction_profile,
        "network_capable": config.acquisition_transport == "github_public_rest",
        "no_network": config.acquisition_transport == "fixture",
        "no_mutation": True,
        "no_credentials_resolved": True,
        "no_scheduler": True,
        "fixture_transport_only": config.acquisition_transport == "fixture",
    }


def validate_source_identity(
    *,
    source_type: str,
    api_source_class: str,
    provider_name: str,
    provider_product: str,
    policy_status: str,
    owner: str,
    repository: str,
    repository_visibility: str,
    read_only: bool,
    mutation_allowed: bool,
    credential_mode: str,
) -> None:
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise GitHubApiPolicyError(f"unsupported source_type: {source_type}")
    if api_source_class not in ALLOWED_GITHUB_API_SOURCE_CLASSES:
        raise GitHubApiPolicyError(f"unsupported api_source_class: {api_source_class}")
    if provider_name != "GitHub":
        raise GitHubApiPolicyError("source.provider_name must be GitHub")
    if provider_product != "GitHub REST API":
        raise GitHubApiPolicyError("source.provider_product must be GitHub REST API")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise GitHubApiPolicyError(
            f"source policy status is not allowed: {policy_status}"
        )
    if not owner or not OWNER_RE.fullmatch(owner):
        raise GitHubApiPolicyError("source.owner must be a safe GitHub owner")
    if not repository or not REPOSITORY_RE.fullmatch(repository):
        raise GitHubApiPolicyError(
            "source.repository must be a safe GitHub repository"
        )
    if repository_visibility not in ALLOWED_REPOSITORY_VISIBILITIES:
        raise GitHubApiPolicyError(
            "source.repository_visibility must be public, private, or internal"
        )
    if not read_only:
        raise GitHubApiPolicyError("source.read_only must be true")
    if mutation_allowed:
        raise GitHubApiPolicyError("source.mutation_allowed must be false")
    if credential_mode not in ALLOWED_CREDENTIAL_MODES:
        raise GitHubApiPolicyError(f"unsupported credential_mode: {credential_mode}")
    if credential_mode == "none_public_readonly" and repository_visibility != "public":
        raise GitHubApiPolicyError(
            "credential_mode none_public_readonly is allowed only for public repositories"
        )


def acquisition_config_from_payload(
    payload: Mapping[str, Any],
    *,
    credential_mode: str,
    repository_visibility: str,
) -> tuple[str, str, int, bool, str]:
    acquisition = payload.get("acquisition")
    if acquisition is None:
        return ("fixture", DEFAULT_GITHUB_API_BASE_URL, 10, False, DEFAULT_GITHUB_USER_AGENT)
    if not isinstance(acquisition, Mapping):
        raise GitHubApiPolicyError("acquisition table is required when present")
    transport = str(acquisition.get("transport") or "fixture")
    if transport not in ALLOWED_ACQUISITION_TRANSPORTS:
        raise GitHubApiPolicyError(f"unsupported acquisition.transport: {transport}")
    base_url = str(acquisition.get("base_url") or DEFAULT_GITHUB_API_BASE_URL).rstrip("/")
    timeout_seconds = optional_positive_int(acquisition, "timeout_seconds", default=10)
    follow_redirects = optional_bool(acquisition, "follow_redirects", default=False)
    user_agent = str(acquisition.get("user_agent") or DEFAULT_GITHUB_USER_AGENT)
    if not user_agent or "\n" in user_agent or "\r" in user_agent:
        raise GitHubApiPolicyError("acquisition.user_agent must be a safe header value")
    if transport == "github_public_rest":
        if repository_visibility != "public":
            raise GitHubApiPolicyError("github_public_rest requires a public repository")
        if credential_mode != "none_public_readonly":
            raise GitHubApiPolicyError(
                "github_public_rest requires credential_mode none_public_readonly"
            )
        if base_url != DEFAULT_GITHUB_API_BASE_URL:
            raise GitHubApiPolicyError("acquisition.base_url must be https://api.github.com")
        if follow_redirects:
            raise GitHubApiPolicyError("github_public_rest must not follow redirects")
    return (transport, base_url, timeout_seconds, follow_redirects, user_agent)


def credentials_ref_from_payload(
    payload: Mapping[str, Any],
    *,
    credential_mode: str,
    repository_visibility: str,
    acquisition_transport: str,
) -> str | None:
    credentials = payload.get("credentials")
    if acquisition_transport == "github_public_rest" and credentials is not None:
        raise GitHubApiPolicyError(
            "credentials table is not allowed for github_public_rest"
        )
    if credential_mode == "none_public_readonly":
        if repository_visibility != "public":
            raise GitHubApiPolicyError("public unauthenticated mode requires public repo")
        return None
    if not isinstance(credentials, Mapping):
        raise GitHubApiPolicyError("credentials.credentials_ref is required")
    credentials_ref = required_string(credentials, "credentials_ref")
    validate_credential_ref(credentials_ref)
    return credentials_ref


def validate_credential_ref(credentials_ref: str) -> None:
    if not any(
        credentials_ref.startswith(prefix)
        and len(credentials_ref) > len(prefix)
        and not credentials_ref[len(prefix) :].isspace()
        for prefix in ALLOWED_CREDENTIAL_REF_PREFIXES
    ):
        raise GitHubApiPolicyError("credentials_ref must be an opaque local ref")


def validate_consent(
    *,
    consent_ref: str,
    authorized_operations: tuple[str, ...],
    authorized_data_classes: tuple[str, ...],
    consent_revoked: bool,
    consent_mutation_allowed: bool,
) -> None:
    if not consent_ref:
        raise GitHubApiPolicyError("consent_ref is required")
    if consent_revoked:
        raise GitHubApiPolicyError("consent is revoked")
    if consent_mutation_allowed:
        raise GitHubApiPolicyError("consent mutation_allowed must be false")
    if authorized_operations != ("read",):
        raise GitHubApiPolicyError("consent authorized_operations must be read-only")
    if not authorized_data_classes:
        raise GitHubApiPolicyError("consent authorized_data_classes is required")


def validate_limits(
    *,
    max_requests_per_run: int,
    endpoint_count: int,
    max_pages_per_endpoint: int,
    max_concurrent_requests: int,
    max_retries: int,
) -> None:
    if max_requests_per_run < endpoint_count:
        raise GitHubApiPolicyError("max_requests_per_run is below endpoint count")
    if max_pages_per_endpoint != 1:
        raise GitHubApiPolicyError("max_pages_per_endpoint must be 1 in GITHUB_API1")
    if max_concurrent_requests != 1:
        raise GitHubApiPolicyError("max_concurrent_requests must be 1 in GITHUB_API1")
    if max_retries != 0:
        raise GitHubApiPolicyError("max_retries must be 0 in GITHUB_API1")


def validate_retention_and_redaction(
    *,
    retention_policy: str,
    raw_response_retention: str,
    redacted_response_retention: str,
    redaction_profile: str,
    sensitivity: str,
) -> None:
    if retention_policy != "local_user_controlled":
        raise GitHubApiPolicyError("retention.policy must be local_user_controlled")
    if raw_response_retention != "minimized":
        raise GitHubApiPolicyError("retention.raw_response_retention must be minimized")
    if redacted_response_retention != "retain":
        raise GitHubApiPolicyError(
            "retention.redacted_response_retention must be retain"
        )
    if redaction_profile != "strict":
        raise GitHubApiPolicyError("redaction.profile must be strict")
    if not sensitivity:
        raise GitHubApiPolicyError("redaction.sensitivity is required")


def parse_github_endpoint(
    payload: Mapping[str, Any],
    *,
    owner: str,
    repository: str,
    authorized_data_classes: tuple[str, ...],
    acquisition_transport: str,
) -> GitHubEndpointConfig:
    name = required_string(payload, "name")
    method = required_string(payload, "method").upper()
    path = required_string(payload, "path")
    purpose = required_string(payload, "purpose")
    response_type = required_string(payload, "response_type")
    max_page_size = required_positive_int(payload, "max_page_size")
    pagination = required_string(payload, "pagination")
    downstream_route = required_string(payload, "downstream_route")
    fixture_response_path = optional_string(payload, "fixture_response_path")
    if method != "GET":
        raise GitHubApiPolicyError("GITHUB_API1 only allows GET endpoints")
    if not path.startswith("/") or "://" in path:
        raise GitHubApiPolicyError("endpoint path must be a relative API path")
    if path not in ALLOWED_ENDPOINT_PATHS:
        if path.startswith("/repos/") and "/contents" in path:
            raise GitHubApiPolicyError("endpoint path is not allowlisted")
        raise GitHubApiPolicyError("endpoint path must remain under owner/repository")
    if "{owner}" not in path or "{repo}" not in path:
        raise GitHubApiPolicyError("endpoint path must remain under owner/repository")
    if owner in path or repository in path:
        raise GitHubApiPolicyError("endpoint path must use owner/repo placeholders")
    if pagination != "none":
        raise GitHubApiPolicyError(
            "GitHub API acquisition only supports pagination = none in this phase"
        )
    if downstream_route != "config":
        raise GitHubApiPolicyError(
            "GitHub API acquisition only supports downstream_route = config"
        )
    if response_type != "application/json":
        raise GitHubApiPolicyError("GitHub API acquisition only supports JSON responses")
    if acquisition_transport == "fixture":
        if fixture_response_path is None:
            raise GitHubApiPolicyError("fixture_response_path is required for fixture transport")
        validate_fixture_response_path(fixture_response_path)
    elif fixture_response_path is not None:
        validate_fixture_response_path(fixture_response_path)
    data_class = ALLOWED_ENDPOINT_PATHS[path]
    if data_class not in authorized_data_classes:
        raise GitHubApiPolicyError(f"endpoint data class is not authorized: {data_class}")
    return GitHubEndpointConfig(
        name=name,
        method=method,
        path=path,
        purpose=purpose,
        response_type=response_type,
        max_page_size=max_page_size,
        pagination=pagination,
        downstream_route=downstream_route,
        fixture_response_path=fixture_response_path,
        data_class=data_class,
    )


def validate_fixture_response_path(fixture_response_path: str) -> None:
    path = Path(fixture_response_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "://" in fixture_response_path
        or not fixture_response_path
    ):
        raise GitHubApiPolicyError(
            "fixture_response_path must be a contained relative path"
        )


def resolve_fixture_response_path(
    config: GitHubApiSourceConfig,
    endpoint: GitHubEndpointConfig,
) -> Path:
    if endpoint.fixture_response_path is None:
        raise GitHubApiPolicyError("fixture_response_path is required for fixture transport")
    config_dir = config.config_path.parent
    response_path = (config_dir / endpoint.fixture_response_path).resolve()
    ensure_contained(response_path, config_dir, "fixture_response_path")
    if not response_path.is_file():
        raise GitHubApiPolicyError(
            f"fixture response does not exist: {endpoint.fixture_response_path}"
        )
    return response_path


def github_public_rest_url(
    config: GitHubApiSourceConfig,
    request: GitHubRequestPlan,
) -> str:
    if config.base_url != DEFAULT_GITHUB_API_BASE_URL:
        raise GitHubApiPolicyError("acquisition.base_url must be https://api.github.com")
    if not request.path.startswith("/") or "://" in request.path:
        raise GitHubApiPolicyError("endpoint path must be a relative API path")
    owner = urllib.parse.quote(config.owner, safe="")
    repository = urllib.parse.quote(config.repository, safe="")
    path = request.path.replace("{owner}", owner).replace("{repo}", repository)
    parsed = urllib.parse.urlsplit(f"{config.base_url}{path}")
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise GitHubApiPolicyError("GitHub REST URL must stay under api.github.com")
    if parsed.query or parsed.fragment:
        raise GitHubApiPolicyError("GitHub REST URL must not include raw query data")
    repo_prefix = f"/repos/{owner}/{repository}"
    if not parsed.path.startswith(repo_prefix):
        raise GitHubApiPolicyError("GitHub REST URL must stay under owner/repository")
    return urllib.parse.urlunsplit(parsed)


def validate_no_auth_headers(headers: Mapping[str, str]) -> None:
    for key in headers:
        if key.lower() in {"authorization", "cookie", "set-cookie"}:
            raise GitHubApiPolicyError("GitHub REST transport must not send auth headers")


def header_mapping(headers: Any) -> dict[str, str]:
    if hasattr(headers, "items"):
        items = headers.items()
    else:
        items = headers or ()
    return {str(key).lower(): str(value) for key, value in items}


def content_type_from_headers(headers: Mapping[str, str]) -> str:
    return headers.get("content-type", "application/octet-stream").split(";", 1)[0]


def rate_limit_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: headers[name]
        for name in RATE_LIMIT_HEADERS
        if name in headers
    }


def endpoint_by_name(
    config: GitHubApiSourceConfig,
    endpoint_name: str,
) -> GitHubEndpointConfig:
    for endpoint in config.endpoints:
        if endpoint.name == endpoint_name:
            return endpoint
    raise GitHubApiPolicyError(f"unknown endpoint: {endpoint_name}")


def github_transport_for_config(config: GitHubApiSourceConfig) -> Any:
    if config.acquisition_transport == "fixture":
        return FixtureGitHubApiTransport()
    if config.acquisition_transport == "github_public_rest":
        return PublicGitHubRestTransport()
    raise GitHubApiPolicyError(
        f"unsupported acquisition.transport: {config.acquisition_transport}"
    )


def validate_transport_response(
    config: GitHubApiSourceConfig,
    request: GitHubRequestPlan,
    response: GitHubTransportResponse,
) -> None:
    if 300 <= response.status_code < 400:
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} returned redirect status "
            f"{response.status_code}; redirects are not followed"
        )
    if response.rate_limit.get("x-ratelimit-remaining") == "0":
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} hit GitHub API rate limit"
        )
    if response.status_code < 200 or response.status_code >= 300:
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} returned HTTP status "
            f"{response.status_code}"
        )
    if "json" not in response.response_type.lower():
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} did not return a JSON response"
        )
    if len(response.body) > config.max_bytes_per_run:
        raise GitHubApiPolicyError("response bytes exceed max_bytes_per_run")


def parse_json_response(body: bytes, endpoint_name: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GitHubApiPolicyError(
            f"endpoint {endpoint_name} returned invalid JSON"
        ) from error


def count_response_items(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        workflow_runs = payload.get("workflow_runs")
        if isinstance(workflow_runs, list):
            return len(workflow_runs)
        return 1
    return 1


def redact_github_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and key.lower() in BODY_FIELDS:
        body = "" if value is None else str(value)
        return {
            "body_present": bool(body),
            "body_length": len(body),
            "body_sha256": sha256_text(body) if body else "",
            "body_redacted": True,
        }
    if key is not None and is_secret_key(key):
        return {
            "redacted": True,
            "redaction_reason": "secret_key",
            "literal_type": literal_type(value),
        }
    if isinstance(value, str) and contains_sensitive_url_marker(value):
        return {
            "redacted": True,
            "redaction_reason": "sensitive_url",
            "literal_type": "string",
        }
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_github_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_github_value(item) for item in value]
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in SECRET_MARKERS)


def contains_sensitive_url_marker(value: str) -> bool:
    return value.startswith("http") and any(
        marker.lower() in value.lower() for marker in SENSITIVE_URL_MARKERS
    )


def literal_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def deterministic_github_api_run_id(
    config: GitHubApiSourceConfig,
    requests: Sequence[GitHubRequestPlan],
) -> str:
    digest = sha256_json(
        {
            "source_id": config.source_id,
            "owner": config.owner,
            "repository": config.repository,
            "transport": config.acquisition_transport,
            "policy_status": config.policy_status,
            "credential_mode": config.credential_mode,
            "endpoints": [request.to_jsonable() for request in requests],
            "limits": {
                "max_requests_per_run": config.max_requests_per_run,
                "max_requests_per_minute": config.max_requests_per_minute,
                "max_pages_per_endpoint": config.max_pages_per_endpoint,
                "max_items_per_endpoint": config.max_items_per_endpoint,
                "max_bytes_per_run": config.max_bytes_per_run,
                "max_concurrent_requests": config.max_concurrent_requests,
                "max_retries": config.max_retries,
            },
        }
    )[:24]
    return f"github-api-{digest}"


def manifest_digest(manifest: GitHubApiPlanManifest) -> str:
    payload = dict(manifest.to_jsonable())
    payload.pop("manifest_sha256", None)
    return sha256_json(payload)


def github_artifact_name(endpoint_name: str) -> str:
    return f"{endpoint_name.replace('_', '-')}.json"


def required_table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise GitHubApiPolicyError(f"{key} table is required")
    return value


def required_endpoint_list(payload: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise GitHubApiPolicyError("at least one [[endpoints]] entry is required")
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping):
            raise GitHubApiPolicyError("endpoint entries must be tables")
    return endpoints


def required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GitHubApiPolicyError(f"{key} is required")
    return value


def optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GitHubApiPolicyError(f"{key} must be a non-empty string")
    return value


def required_positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise GitHubApiPolicyError(f"{key} must be a positive integer")
    return value


def optional_positive_int(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise GitHubApiPolicyError(f"{key} must be a positive integer")
    return value


def required_nonnegative_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GitHubApiPolicyError(f"{key} must be a non-negative integer")
    return value


def required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise GitHubApiPolicyError(f"{key} must be a boolean")
    return value


def optional_bool(payload: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise GitHubApiPolicyError(f"{key} must be a boolean")
    return value


def string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GitHubApiPolicyError("expected a list of strings")
    return tuple(value)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(payload: str) -> str:
    return sha256_bytes(payload.encode("utf-8"))


def sha256_json(payload: Any) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def ensure_contained(path: Path, parent: Path, label: str) -> None:
    if not is_contained(path, parent):
        raise GitHubApiPolicyError(f"{label} escapes its configured root")


def is_contained(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None
