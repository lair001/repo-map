"""Explicit-policy-gated documented REST API acquisition skeleton."""

from __future__ import annotations

import hashlib
import json
import tomllib
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


EXTRACTOR = "api-documented-rest-ingestion"
EXTRACTOR_VERSION = "0.1.0"
ALLOWED_SOURCE_TYPES = frozenset({"api.rest"})
ALLOWED_API_SOURCE_CLASSES = frozenset({"api.custom_documented_api"})
ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
ALLOWED_CREDENTIAL_REF_PREFIXES = (
    "local_secret_ref:",
    "os_keychain_ref:",
    "env_ref:",
)
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
    }
)


class ApiPolicyError(ValueError):
    """Raised when an API source config is not explicitly allowed and bounded."""


@dataclass(frozen=True)
class ApiEndpointConfig:
    name: str
    method: str
    path: str
    purpose: str
    response_type: str
    max_page_size: int
    pagination: str
    downstream_route: str
    fixture_response_path: str

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
        }


@dataclass(frozen=True)
class ApiSourceConfig:
    config_path: Path
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    read_only: bool
    mutation_allowed: bool
    credentials_ref: str
    consent_ref: str
    authorized_operations: tuple[str, ...]
    authorized_data_classes: tuple[str, ...]
    consent_revoked: bool
    consent_mutation_allowed: bool
    max_requests_per_run: int
    max_requests_per_minute: int
    max_concurrent_requests: int
    max_bytes_per_run: int
    max_items_per_run: int
    max_retries: int
    retention_policy: str
    raw_response_retention: str
    redacted_response_retention: str
    redaction_profile: str
    sensitivity: str
    endpoints: tuple[ApiEndpointConfig, ...]


@dataclass(frozen=True)
class ApiRequestPlan:
    endpoint_name: str
    method: str
    path: str
    response_type: str
    downstream_route: str
    request_id: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path": self.path,
            "response_type": self.response_type,
            "downstream_route": self.downstream_route,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class ApiPlanManifest:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    api_run_id: str
    api_manifest_id: str
    requests: tuple[ApiRequestPlan, ...]
    max_requests_per_run: int
    max_requests_per_minute: int
    max_concurrent_requests: int
    max_bytes_per_run: int
    max_items_per_run: int
    max_retries: int
    retention_policy: str
    redaction_profile: str
    sensitivity: str
    manifest_sha256: str = ""
    no_network: bool = True
    no_mutation: bool = True
    no_credentials_resolved: bool = True
    no_scheduler: bool = True

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
            "request_count": self.request_count,
            "requests": [request.to_jsonable() for request in self.requests],
            "limits": {
                "max_requests_per_run": self.max_requests_per_run,
                "max_requests_per_minute": self.max_requests_per_minute,
                "max_concurrent_requests": self.max_concurrent_requests,
                "max_bytes_per_run": self.max_bytes_per_run,
                "max_items_per_run": self.max_items_per_run,
                "max_retries": self.max_retries,
            },
            "retention_policy": self.retention_policy,
            "redaction_profile": self.redaction_profile,
            "sensitivity": self.sensitivity,
            "manifest_sha256": self.manifest_sha256,
            "no_network": self.no_network,
            "no_mutation": self.no_mutation,
            "no_credentials_resolved": self.no_credentials_resolved,
            "no_scheduler": self.no_scheduler,
        }


@dataclass(frozen=True)
class ApiTransportResponse:
    status_code: int
    body: bytes
    response_type: str


@dataclass(frozen=True)
class ApiResponseRecord:
    endpoint_name: str
    method: str
    path_template: str
    response_type: str
    status_code: int
    response_byte_count: int
    response_sha256: str
    artifact_path: str
    redacted: bool
    redaction_profile: str
    retention_policy: str
    downstream_route: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path_template": self.path_template,
            "response_type": self.response_type,
            "status_code": self.status_code,
            "response_byte_count": self.response_byte_count,
            "response_sha256": self.response_sha256,
            "artifact_path": self.artifact_path,
            "redacted": self.redacted,
            "redaction_profile": self.redaction_profile,
            "retention_policy": self.retention_policy,
            "downstream_route": self.downstream_route,
        }


@dataclass(frozen=True)
class ApiAcquireSummary:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    api_run_id: str
    api_manifest_id: str
    requests: int
    responses: int
    observations: int
    output_path: Path
    output_path_summary: str
    manifest: ApiPlanManifest
    response_records: tuple[ApiResponseRecord, ...]
    load_summary: LoadSummary

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "api_source_class": self.api_source_class,
            "provider_name": self.provider_name,
            "provider_product": self.provider_product,
            "policy_status": self.policy_status,
            "api_run_id": self.api_run_id,
            "api_manifest_id": self.api_manifest_id,
            "requests": self.requests,
            "responses": self.responses,
            "observations": self.observations,
            "output_path": self.output_path_summary,
            "repository_id": self.load_summary.repository_id,
            "run_id": self.load_summary.run_id,
            "files": self.load_summary.files,
            "manifest": self.manifest.to_jsonable(),
            "response_records": [record.to_jsonable() for record in self.response_records],
            "no_network": True,
            "no_mutation": True,
            "no_credentials_resolved": True,
            "no_scheduler": True,
        }


class FixtureApiTransport:
    """Fixture-only API transport for API1; performs no network I/O."""

    def fetch(
        self,
        config: ApiSourceConfig,
        request: ApiRequestPlan,
    ) -> ApiTransportResponse:
        endpoint = endpoint_by_name(config, request.endpoint_name)
        response_path = resolve_fixture_response_path(
            config.config_path,
            endpoint.fixture_response_path,
        )
        try:
            body = response_path.read_bytes()
        except OSError as error:
            raise ApiPolicyError(
                f"fixture response is not readable for endpoint {endpoint.name}: {error}"
            ) from error
        return ApiTransportResponse(
            status_code=200,
            body=body,
            response_type=endpoint.response_type,
        )


def load_api_source_config(path: Path | str) -> ApiSourceConfig:
    config_path = Path(path).resolve()
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ApiPolicyError(f"invalid API config: {error}") from error

    source = required_table(payload, "source")
    credentials = required_table(payload, "credentials")
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
    read_only = required_bool(source, "read_only")
    mutation_allowed = required_bool(source, "mutation_allowed")

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ApiPolicyError(f"unsupported source_type: {source_type}")
    if api_source_class not in ALLOWED_API_SOURCE_CLASSES:
        raise ApiPolicyError(f"unsupported api_source_class: {api_source_class}")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise ApiPolicyError(f"source policy status is not allowed: {policy_status}")
    if not read_only:
        raise ApiPolicyError("source.read_only must be true")
    if mutation_allowed:
        raise ApiPolicyError("source.mutation_allowed must be false")

    credentials_ref = required_string(credentials, "credentials_ref")
    validate_credential_ref(credentials_ref)

    consent_ref = required_string(consent, "consent_ref")
    authorized_operations = string_tuple(consent.get("authorized_operations"))
    authorized_data_classes = string_tuple(consent.get("authorized_data_classes"))
    consent_revoked = required_bool(consent, "revoked")
    consent_mutation_allowed = required_bool(consent, "mutation_allowed")
    if consent_revoked:
        raise ApiPolicyError("consent is revoked")
    if consent_mutation_allowed:
        raise ApiPolicyError("consent mutation_allowed must be false")
    if authorized_operations != ("read",):
        raise ApiPolicyError("consent authorized_operations must be read-only")
    if not authorized_data_classes:
        raise ApiPolicyError("consent authorized_data_classes is required")

    max_requests_per_run = required_positive_int(limits, "max_requests_per_run")
    max_requests_per_minute = required_positive_int(limits, "max_requests_per_minute")
    max_concurrent_requests = required_positive_int(limits, "max_concurrent_requests")
    max_bytes_per_run = required_positive_int(limits, "max_bytes_per_run")
    max_items_per_run = required_positive_int(limits, "max_items_per_run")
    max_retries = required_nonnegative_int(limits, "max_retries")
    if max_concurrent_requests != 1:
        raise ApiPolicyError("max_concurrent_requests must be 1 in API1")
    if max_requests_per_run < len(endpoints):
        raise ApiPolicyError("max_requests_per_run is below endpoint count")

    retention_policy = required_string(retention, "policy")
    raw_response_retention = required_string(retention, "raw_response_retention")
    redacted_response_retention = required_string(
        retention,
        "redacted_response_retention",
    )
    redaction_profile = required_string(redaction, "profile")
    sensitivity = required_string(redaction, "sensitivity")

    parsed_endpoints = tuple(parse_endpoint(endpoint) for endpoint in endpoints)
    return ApiSourceConfig(
        config_path=config_path,
        source_id=source_id,
        source_type=source_type,
        api_source_class=api_source_class,
        provider_name=provider_name,
        provider_product=provider_product,
        policy_status=policy_status,
        read_only=read_only,
        mutation_allowed=mutation_allowed,
        credentials_ref=credentials_ref,
        consent_ref=consent_ref,
        authorized_operations=authorized_operations,
        authorized_data_classes=authorized_data_classes,
        consent_revoked=consent_revoked,
        consent_mutation_allowed=consent_mutation_allowed,
        max_requests_per_run=max_requests_per_run,
        max_requests_per_minute=max_requests_per_minute,
        max_concurrent_requests=max_concurrent_requests,
        max_bytes_per_run=max_bytes_per_run,
        max_items_per_run=max_items_per_run,
        max_retries=max_retries,
        retention_policy=retention_policy,
        raw_response_retention=raw_response_retention,
        redacted_response_retention=redacted_response_retention,
        redaction_profile=redaction_profile,
        sensitivity=sensitivity,
        endpoints=parsed_endpoints,
    )


def build_api_plan_from_config(config_path: Path | str) -> ApiPlanManifest:
    return build_api_plan(load_api_source_config(config_path))


def build_api_plan(config: ApiSourceConfig) -> ApiPlanManifest:
    requests = tuple(
        ApiRequestPlan(
            endpoint_name=endpoint.name,
            method=endpoint.method,
            path=endpoint.path,
            response_type=endpoint.response_type,
            downstream_route=endpoint.downstream_route,
            request_id=sha256_json(
                {
                    "source_id": config.source_id,
                    "endpoint": endpoint.plan_payload(),
                }
            )[:24],
        )
        for endpoint in config.endpoints
    )
    run_id = deterministic_api_run_id(config, requests)
    manifest_id = sha256_text(f"{config.source_id}:{run_id}")[:24]
    manifest = ApiPlanManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
        api_run_id=run_id,
        api_manifest_id=manifest_id,
        requests=requests,
        max_requests_per_run=config.max_requests_per_run,
        max_requests_per_minute=config.max_requests_per_minute,
        max_concurrent_requests=config.max_concurrent_requests,
        max_bytes_per_run=config.max_bytes_per_run,
        max_items_per_run=config.max_items_per_run,
        max_retries=config.max_retries,
        retention_policy=config.retention_policy,
        redaction_profile=config.redaction_profile,
        sensitivity=config.sensitivity,
    )
    return replace(manifest, manifest_sha256=manifest_digest(manifest))


def acquire_api_source(
    config_path: Path | str,
    *,
    repository_name: str,
    root_path: Path | str,
    psql_args: Sequence[str],
    git_commit: str | None = None,
    psql_command: str = "psql",
    loader: Callable[..., LoadSummary] = load_file_observations,
    transport: FixtureApiTransport | None = None,
) -> ApiAcquireSummary:
    config = load_api_source_config(config_path)
    repo_root = Path(root_path).resolve()
    manifest = build_api_plan(config)
    fixture_transport = transport or FixtureApiTransport()
    fetched: list[tuple[ApiRequestPlan, ApiTransportResponse, Any]] = []
    total_bytes = 0
    total_items = 0
    for request in manifest.requests:
        response = fixture_transport.fetch(config, request)
        if response.status_code < 200 or response.status_code >= 300:
            raise ApiPolicyError(
                f"endpoint {request.endpoint_name} returned status {response.status_code}"
            )
        total_bytes += len(response.body)
        if total_bytes > config.max_bytes_per_run:
            raise ApiPolicyError("response bytes exceed max_bytes_per_run")
        parsed = parse_json_response(response.body, request.endpoint_name)
        total_items += count_response_items(parsed)
        if total_items > config.max_items_per_run:
            raise ApiPolicyError("response items exceed max_items_per_run")
        fetched.append((request, response, parsed))

    output_path, records = write_api_run_files(
        config,
        manifest,
        fetched=fetched,
        repository_root=repo_root,
    )
    observations = api_observations_from_records(
        config,
        manifest,
        response_records=records,
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
    return ApiAcquireSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
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
    )


def api_observations_from_records(
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    *,
    response_records: Sequence[ApiResponseRecord],
    repository_root: Path,
    output_path: Path,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(api_provenance_observations(config, manifest, response_records))
    for record in response_records:
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
            annotate_observation(
                observation,
                config=config,
                manifest=manifest,
                record=record,
            )
            for observation in routed
        )
    return tuple(observations)


def api_provenance_observations(
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    response_records: Sequence[ApiResponseRecord],
) -> tuple[RawObservation, ...]:
    base_metadata = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "api_source_class": config.api_source_class,
        "provider_name": config.provider_name,
        "provider_product": config.provider_product,
        "api_run_id": manifest.api_run_id,
        "api_manifest_id": manifest.api_manifest_id,
        "api_policy_status": config.policy_status,
        "api_retention_policy": config.retention_policy,
        "api_sensitivity": config.sensitivity,
        "redaction_profile": config.redaction_profile,
        "no_network": True,
        "no_mutation": True,
        "no_credentials_resolved": True,
    }
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
    for record in response_records:
        observations.append(
            RawObservation(
                kind="api.response",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}"
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
    return tuple(observations)


def annotate_observation(
    observation: RawObservation,
    *,
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    record: ApiResponseRecord,
) -> RawObservation:
    metadata = dict(observation.metadata)
    metadata.update(
        {
            "source_id": config.source_id,
            "source_type": config.source_type,
            "api_source_class": config.api_source_class,
            "provider_name": config.provider_name,
            "provider_product": config.provider_product,
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


def write_api_run_files(
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    *,
    fetched: Sequence[tuple[ApiRequestPlan, ApiTransportResponse, Any]],
    repository_root: Path,
) -> tuple[Path, tuple[ApiResponseRecord, ...]]:
    output_path = (
        repository_root
        / ".repomap"
        / "api-runs"
        / config.source_id
        / manifest.api_run_id
    ).resolve()
    ensure_contained(output_path, repository_root, "api output path")
    artifacts_path = output_path / "artifacts"
    artifacts_path.mkdir(parents=True, exist_ok=True)
    records: list[ApiResponseRecord] = []
    for request, response, parsed in fetched:
        redacted_payload = redact_value(parsed)
        artifact_name = safe_artifact_name(request.endpoint_name, request.response_type)
        artifact_path = artifacts_path / artifact_name
        write_json(artifact_path, redacted_payload)
        relative_artifact = artifact_path.relative_to(output_path).as_posix()
        records.append(
            ApiResponseRecord(
                endpoint_name=request.endpoint_name,
                method=request.method,
                path_template=request.path,
                response_type=request.response_type,
                status_code=response.status_code,
                response_byte_count=len(response.body),
                response_sha256=sha256_bytes(response.body),
                artifact_path=relative_artifact,
                redacted=True,
                redaction_profile=config.redaction_profile,
                retention_policy=config.retention_policy,
                downstream_route=request.downstream_route,
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
    return output_path, tuple(records)


def parse_endpoint(payload: Mapping[str, Any]) -> ApiEndpointConfig:
    name = required_string(payload, "name")
    method = required_string(payload, "method").upper()
    path = required_string(payload, "path")
    purpose = required_string(payload, "purpose")
    response_type = required_string(payload, "response_type")
    max_page_size = required_positive_int(payload, "max_page_size")
    pagination = required_string(payload, "pagination")
    downstream_route = required_string(payload, "downstream_route")
    fixture_response_path = required_string(payload, "fixture_response_path")
    if method != "GET":
        raise ApiPolicyError("API1 only allows GET endpoints")
    if not path.startswith("/") or "://" in path:
        raise ApiPolicyError("endpoint path must be an allowlisted relative API path")
    if pagination != "none":
        raise ApiPolicyError("API1 only supports pagination = none")
    if downstream_route != "config":
        raise ApiPolicyError("API1 only supports downstream_route = config")
    validate_fixture_response_path(fixture_response_path)
    return ApiEndpointConfig(
        name=name,
        method=method,
        path=path,
        purpose=purpose,
        response_type=response_type,
        max_page_size=max_page_size,
        pagination=pagination,
        downstream_route=downstream_route,
        fixture_response_path=fixture_response_path,
    )


def required_endpoint_list(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = payload.get("endpoints")
    if not isinstance(value, list) or not value:
        raise ApiPolicyError("at least one [[endpoints]] entry is required")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ApiPolicyError("[[endpoints]] entries must be objects")
        result.append(item)
    return tuple(result)


def validate_credential_ref(value: str) -> None:
    if not any(value.startswith(prefix) for prefix in ALLOWED_CREDENTIAL_REF_PREFIXES):
        raise ApiPolicyError("credentials_ref must use an allowed opaque reference shape")
    _, _, name = value.partition(":")
    if not name.strip():
        raise ApiPolicyError("credentials_ref must include a non-empty opaque name")


def validate_fixture_response_path(value: str) -> None:
    path = Path(value)
    if path.is_absolute() or "://" in value:
        raise ApiPolicyError("fixture_response_path must be a local relative path")
    if ".." in path.parts:
        raise ApiPolicyError("fixture_response_path must not escape the config root")


def resolve_fixture_response_path(config_path: Path, configured: str) -> Path:
    path = (config_path.parent / configured).resolve()
    ensure_contained(path, config_path.parent.resolve(), "fixture response path")
    return path


def endpoint_by_name(config: ApiSourceConfig, name: str) -> ApiEndpointConfig:
    for endpoint in config.endpoints:
        if endpoint.name == name:
            return endpoint
    raise ApiPolicyError(f"request endpoint is not allowlisted: {name}")


def parse_json_response(body: bytes, endpoint_name: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApiPolicyError(
            f"endpoint {endpoint_name} did not return safe JSON: {error}"
        ) from error


def count_response_items(payload: Any) -> int:
    if isinstance(payload, Mapping):
        items = payload.get("items")
        if isinstance(items, list):
            return len(items)
        return 1
    if isinstance(payload, list):
        return len(payload)
    return 1


def redact_value(value: Any, *, key_name: str | None = None) -> Any:
    if key_name and is_secret_key(key_name):
        return {
            "redacted": True,
            "redaction_reason": "secret-prone-key",
            "literal_type": literal_type(value),
        }
    if isinstance(value, Mapping):
        return {str(key): redact_value(item, key_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return any(marker in normalized for marker in SECRET_MARKERS)


def literal_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "unknown"


def deterministic_api_run_id(
    config: ApiSourceConfig,
    requests: Sequence[ApiRequestPlan],
) -> str:
    payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "api_source_class": config.api_source_class,
        "provider_name": config.provider_name,
        "provider_product": config.provider_product,
        "policy_status": config.policy_status,
        "limits": {
            "max_requests_per_run": config.max_requests_per_run,
            "max_requests_per_minute": config.max_requests_per_minute,
            "max_concurrent_requests": config.max_concurrent_requests,
            "max_bytes_per_run": config.max_bytes_per_run,
            "max_items_per_run": config.max_items_per_run,
            "max_retries": config.max_retries,
        },
        "retention": {
            "policy": config.retention_policy,
            "raw_response_retention": config.raw_response_retention,
            "redacted_response_retention": config.redacted_response_retention,
        },
        "redaction": {
            "profile": config.redaction_profile,
            "sensitivity": config.sensitivity,
        },
        "requests": [request.to_jsonable() for request in requests],
    }
    return "api-" + sha256_json(payload)[:24]


def manifest_digest(manifest: ApiPlanManifest) -> str:
    payload = manifest.to_jsonable()
    payload["manifest_sha256"] = ""
    return sha256_json(payload)


def safe_artifact_name(endpoint_name: str, response_type: str) -> str:
    suffix = ".json" if response_type == "application/json" else ".jsonl"
    safe = "".join(
        character if character.isalnum() or character in ("-", "_") else "-"
        for character in endpoint_name
    ).strip("-")
    return f"{safe or 'response'}{suffix}"


def required_table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ApiPolicyError(f"{key} table is required")
    return value


def required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiPolicyError(f"{key} is required")
    return value.strip()


def required_positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ApiPolicyError(f"{key} must be a positive integer")
    return value


def required_nonnegative_int(payload: Mapping[str, Any], key: str) -> int:
    if key not in payload:
        raise ApiPolicyError(f"{key} is required")
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApiPolicyError(f"{key} must be a non-negative integer")
    return value


def required_bool(payload: Mapping[str, Any], key: str) -> bool:
    if key not in payload:
        raise ApiPolicyError(f"{key} is required")
    value = payload[key]
    if not isinstance(value, bool):
        raise ApiPolicyError(f"{key} must be a boolean")
    return value


def string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ApiPolicyError("consent list fields must be arrays")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ApiPolicyError("consent list values must be non-empty strings")
        result.append(item.strip())
    return tuple(result)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def ensure_contained(path: Path, root: Path, name: str) -> None:
    if not is_contained(path, root):
        raise ApiPolicyError(f"{name} escapes repository root")


def is_contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
