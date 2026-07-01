"""Explicit-policy-gated local bulk corpus ingestion."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from repomap_kg.css_html_matching import extract_css_selector_match_observations
from repomap_kg.discovery import (
    FileInfo,
    classify_path,
    extract_config_file_observations_from_file,
    extract_css_file_observations_from_file,
    extract_document_file_observations_from_file,
    extract_eml_file_observations_from_file,
    extract_feed_file_observations_from_file,
    extract_html_file_observations_from_file,
    extract_javascript_file_observations_from_file,
    extract_markdown_file_observations_from_file,
    extract_mbox_file_observations_from_file,
    extract_nix_file_observations_from_file,
    extract_python_file_observations_from_file,
    extract_ruby_file_observations_from_file,
    extract_shell_file_observations,
    markdown_anchor_index,
)
from repomap_kg.observations import RawObservation
from repomap_kg.python_extractor import PythonModuleIndex
from repomap_kg.storage import LoadSummary, load_file_observations


EXTRACTOR = "bulk-local-ingestion"
EXTRACTOR_VERSION = "0.1.0"
ALLOWED_SOURCE_TYPES = frozenset({"local.directory"})
ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
ALLOWED_CORPUS_KINDS = frozenset(
    {
        "generic_local_corpus",
        "email_export",
        "eml_export",
        "mbox_export",
        "document_corpus",
        "source_code_corpus",
        "saved_page_corpus",
        "static_artifact_corpus",
        "report_corpus",
        "warc_corpus",
        "feed_corpus",
        "mixed_corpus",
    }
)
DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".gradle",
        "target",
        "build",
        "dist",
        ".next",
        ".nuxt",
        ".cache",
        ".Trash",
        "Mail",
        "Maildir",
        "Thunderbird",
        "Outlook",
        "Apple Mail",
        "Gmail",
        "Profiles",
    }
)
ARCHIVE_EXTENSIONS = frozenset(
    {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz"}
)
WARC_EXTENSIONS = frozenset({".warc", ".warc.gz"})
EXTENSION_ROUTES = {
    ".eml": "eml",
    ".mbox": "mbox",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "config",
    ".jsonl": "config",
    ".jsonc": "config",
    ".toml": "config",
    ".yaml": "config",
    ".yml": "config",
    ".xml": "config",
    ".plist": "config",
    ".txt": "document",
    ".csv": "document",
    ".tsv": "document",
    ".tex": "document",
    ".latex": "document",
    ".odt": "document",
    ".ods": "document",
    ".ott": "document",
    ".ots": "document",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".mts": "javascript",
    ".cts": "javascript",
    ".tsx": "javascript",
    ".rb": "ruby",
    ".rake": "ruby",
    ".gemspec": "ruby",
    ".py": "python",
    ".nix": "nix",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".rss": "feed",
    ".atom": "feed",
}
SPECIAL_FILENAME_ROUTES = {
    "Rakefile": "ruby",
    "Gemfile": "ruby",
    "Vagrantfile": "ruby",
}


class BulkPolicyError(ValueError):
    """Raised when a bulk source config is not explicitly allowed and bounded."""


@dataclass(frozen=True)
class BulkSourceConfig:
    config_path: Path
    source_id: str
    source_type: str
    corpus_kind: str
    policy_status: str
    root_path_configured: str
    resolved_root: Path
    max_files: int
    max_total_bytes: int
    max_file_bytes: int
    max_depth: int
    follow_symlinks: bool
    include_hidden: bool
    include_extensions: tuple[str, ...]
    excluded_directories: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    retention_policy: str | None
    redaction_profile: str | None
    sensitivity: str | None


@dataclass(frozen=True)
class BulkIncludedFile:
    relative_path: str
    repository_path: str
    route: str
    byte_count: int
    sha256: str
    skipped: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "repository_path": self.repository_path,
            "route": self.route,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class BulkSkippedFile:
    relative_path: str
    reason: str
    byte_count: int | None = None
    route: str | None = None
    skipped: bool = True

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "relative_path": self.relative_path,
            "reason": self.reason,
            "skipped": self.skipped,
        }
        if self.byte_count is not None:
            payload["byte_count"] = self.byte_count
        if self.route is not None:
            payload["route"] = self.route
        return payload


@dataclass(frozen=True)
class BulkManifest:
    source_id: str
    source_type: str
    corpus_kind: str
    policy_status: str
    root_path_summary: str
    bulk_run_id: str
    bulk_manifest_id: str
    included_files: tuple[BulkIncludedFile, ...]
    skipped_files: tuple[BulkSkippedFile, ...]
    total_bytes_seen: int
    total_bytes_included: int
    limit_hit: bool
    limit_reason: str | None
    extractor_counts: Mapping[str, int]
    diagnostic_counts: Mapping[str, int]
    redaction_counts: Mapping[str, int] = field(default_factory=dict)
    manifest_sha256: str = ""
    no_provider_api: bool = True
    no_external_fetch: bool = True
    no_source_mutation: bool = True
    no_archive_decompression: bool = True

    @property
    def file_count_seen(self) -> int:
        return len(self.included_files) + len(self.skipped_files)

    @property
    def file_count_included(self) -> int:
        return len(self.included_files)

    @property
    def file_count_skipped(self) -> int:
        return len(self.skipped_files)

    def to_jsonable(self) -> dict[str, Any]:
        payload = {
            "bulk_run_id": self.bulk_run_id,
            "bulk_manifest_id": self.bulk_manifest_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "corpus_kind": self.corpus_kind,
            "policy_status": self.policy_status,
            "root_path_summary": self.root_path_summary,
            "file_count_seen": self.file_count_seen,
            "file_count_included": self.file_count_included,
            "file_count_skipped": self.file_count_skipped,
            "total_bytes_seen": self.total_bytes_seen,
            "total_bytes_included": self.total_bytes_included,
            "limit_hit": self.limit_hit,
            "limit_reason": self.limit_reason,
            "extractor_counts": dict(sorted(self.extractor_counts.items())),
            "diagnostic_counts": dict(sorted(self.diagnostic_counts.items())),
            "redaction_counts": dict(sorted(self.redaction_counts.items())),
            "manifest_sha256": self.manifest_sha256,
            "included_files": [item.to_jsonable() for item in self.included_files],
            "skipped_files": [item.to_jsonable() for item in self.skipped_files],
            "no_provider_api": self.no_provider_api,
            "no_external_fetch": self.no_external_fetch,
            "no_source_mutation": self.no_source_mutation,
            "no_archive_decompression": self.no_archive_decompression,
        }
        return payload


@dataclass(frozen=True)
class BulkImportSummary:
    source_id: str
    source_type: str
    corpus_kind: str
    policy_status: str
    bulk_run_id: str
    bulk_manifest_id: str
    observations: int
    included_files: int
    skipped_files: int
    output_path: Path
    output_path_summary: str
    manifest: BulkManifest
    load_summary: LoadSummary

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "corpus_kind": self.corpus_kind,
            "policy_status": self.policy_status,
            "bulk_run_id": self.bulk_run_id,
            "bulk_manifest_id": self.bulk_manifest_id,
            "observations": self.observations,
            "included_files": self.included_files,
            "skipped_files": self.skipped_files,
            "output_path": self.output_path_summary,
            "repository_id": self.load_summary.repository_id,
            "run_id": self.load_summary.run_id,
            "files": self.load_summary.files,
            "manifest": self.manifest.to_jsonable(),
            "no_provider_api": True,
            "no_external_fetch": True,
            "no_source_mutation": True,
            "no_archive_decompression": True,
        }


def load_bulk_source_config(path: Path | str) -> BulkSourceConfig:
    config_path = Path(path).resolve()
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise BulkPolicyError(f"invalid bulk config: {error}") from error

    source = required_table(payload, "source")
    limits = required_table(payload, "limits")
    include = table(payload, "include")
    exclude = table(payload, "exclude")
    retention = table(payload, "retention")
    redaction = table(payload, "redaction")

    source_id = required_string(source, "source_id")
    source_type = required_string(source, "source_type")
    corpus_kind = required_string(source, "corpus_kind")
    policy_status = required_string(source, "policy_status")
    root_path_configured = required_string(source, "root_path")

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise BulkPolicyError(f"unsupported source_type: {source_type}")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise BulkPolicyError(f"source policy status is not allowed: {policy_status}")
    if corpus_kind not in ALLOWED_CORPUS_KINDS:
        raise BulkPolicyError(f"unsupported corpus_kind: {corpus_kind}")
    if "://" in root_path_configured:
        raise BulkPolicyError("root_path must be a local filesystem path")

    resolved_root = resolve_config_root(config_path, root_path_configured)
    if not resolved_root.exists():
        raise BulkPolicyError("root_path does not exist")
    if not resolved_root.is_dir():
        raise BulkPolicyError("root_path must be a directory for local.directory")

    return BulkSourceConfig(
        config_path=config_path,
        source_id=source_id,
        source_type=source_type,
        corpus_kind=corpus_kind,
        policy_status=policy_status,
        root_path_configured=root_path_configured,
        resolved_root=resolved_root,
        max_files=required_positive_int(limits, "max_files"),
        max_total_bytes=required_positive_int(limits, "max_total_bytes"),
        max_file_bytes=required_positive_int(limits, "max_file_bytes"),
        max_depth=required_positive_int(limits, "max_depth"),
        follow_symlinks=required_bool(limits, "follow_symlinks"),
        include_hidden=bool_value(limits.get("include_hidden", False), "include_hidden"),
        include_extensions=string_tuple(include.get("extensions", ())),
        excluded_directories=string_tuple(exclude.get("directories", ())),
        excluded_paths=normalized_path_tuple(exclude.get("paths", ())),
        retention_policy=optional_string(retention.get("policy")),
        redaction_profile=optional_string(redaction.get("profile")),
        sensitivity=optional_string(redaction.get("sensitivity")),
    )


def build_bulk_plan_from_config(config_path: Path | str) -> BulkManifest:
    config = load_bulk_source_config(config_path)
    return build_bulk_plan(config, repository_root=config.resolved_root)


def build_bulk_plan(
    config: BulkSourceConfig,
    *,
    repository_root: Path | str | None = None,
) -> BulkManifest:
    source_root = config.resolved_root
    repo_root = Path(repository_root).resolve() if repository_root else source_root
    ensure_contained(source_root, repo_root, "root_path")
    included: list[BulkIncludedFile] = []
    skipped: list[BulkSkippedFile] = []
    state = {
        "total_seen": 0,
        "total_included": 0,
        "limit_reasons": [],
    }
    excluded_directories = DEFAULT_EXCLUDED_DIRECTORIES | frozenset(
        config.excluded_directories
    )

    def add_skipped(
        path: Path,
        reason: str,
        *,
        byte_count: int | None = None,
        route: str | None = None,
    ) -> None:
        relative = relative_to_root(source_root, path)
        skipped.append(
            BulkSkippedFile(
                relative_path=relative,
                reason=reason,
                byte_count=byte_count,
                route=route,
            )
        )
        if reason.startswith("max_") and reason not in state["limit_reasons"]:
            state["limit_reasons"].append(reason)

    def add_skipped_tree(path: Path, reason: str) -> None:
        if path.is_file() or path.is_symlink():
            add_skipped(path, reason, byte_count=safe_size(path))
            state["total_seen"] += safe_size(path) or 0
            return
        for directory, dirnames, filenames in os.walk(path, followlinks=False):
            dirnames[:] = sorted(dirnames)
            for filename in sorted(filenames):
                file_path = Path(directory) / filename
                byte_count = safe_size(file_path)
                state["total_seen"] += byte_count or 0
                add_skipped(file_path, reason, byte_count=byte_count)

    def walk(directory: Path) -> None:
        for entry in sorted(directory.iterdir(), key=lambda item: relative_to_root(source_root, item)):
            relative = relative_to_root(source_root, entry)
            if is_excluded_path(relative, config.excluded_paths):
                add_skipped_tree(entry, "excluded_path")
                continue
            if entry.name.startswith(".") and not config.include_hidden:
                add_skipped_tree(entry, "hidden_excluded")
                continue
            if entry.is_symlink():
                if not config.follow_symlinks:
                    add_skipped(entry, "symlink_excluded", byte_count=safe_size(entry))
                    continue
                target = entry.resolve()
                if not is_contained(target, source_root):
                    add_skipped(entry, "symlink_escapes_root", byte_count=safe_size(entry))
                    continue
            if entry.is_dir():
                if entry.name in excluded_directories:
                    add_skipped_tree(entry, "excluded_directory")
                    continue
                if depth(relative) > config.max_depth:
                    add_skipped_tree(entry, "max_depth_exceeded")
                    continue
                walk(entry)
                continue
            try:
                mode = entry.stat().st_mode
            except OSError:
                add_skipped(entry, "special_file")
                continue
            if not stat.S_ISREG(mode):
                add_skipped(entry, "special_file")
                continue
            state["total_seen"] += entry.stat().st_size
            process_file(entry)

    def process_file(path: Path) -> None:
        relative = relative_to_root(source_root, path)
        file_depth = depth(relative)
        route = classify_bulk_route(path)
        byte_count = path.stat().st_size
        if file_depth > config.max_depth:
            add_skipped(path, "max_depth_exceeded", byte_count=byte_count, route=route)
            return
        if route is None or not route_included(config, path, route):
            add_skipped(path, "unsupported_extension", byte_count=byte_count, route=route)
            return
        if route == "archive":
            add_skipped(path, "archive_deferred", byte_count=byte_count, route=route)
            return
        if route == "warc":
            add_skipped(path, "warc_deferred", byte_count=byte_count, route=route)
            return
        if byte_count > config.max_file_bytes:
            add_skipped(path, "max_file_bytes_exceeded", byte_count=byte_count, route=route)
            return
        if state["total_included"] + byte_count > config.max_total_bytes:
            add_skipped(path, "max_total_bytes_exceeded", byte_count=byte_count, route=route)
            return
        if len(included) >= config.max_files:
            add_skipped(path, "max_files_exceeded", byte_count=byte_count, route=route)
            return
        repository_path = path.resolve().relative_to(repo_root).as_posix()
        digest = sha256_file(path)
        included.append(
            BulkIncludedFile(
                relative_path=relative,
                repository_path=repository_path,
                route=route,
                byte_count=byte_count,
                sha256=digest,
            )
        )
        state["total_included"] += byte_count

    walk(source_root)
    included.sort(key=lambda item: item.relative_path)
    skipped.sort(key=lambda item: item.relative_path)
    extractor_counts = Counter(item.route for item in included)
    diagnostic_counts = Counter(item.reason for item in skipped)
    run_id = deterministic_run_id(config, included)
    manifest_id = sha256_text(f"{config.source_id}:{run_id}")[:24]
    manifest = BulkManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        corpus_kind=config.corpus_kind,
        policy_status=config.policy_status,
        root_path_summary=root_path_summary(config),
        bulk_run_id=run_id,
        bulk_manifest_id=manifest_id,
        included_files=tuple(included),
        skipped_files=tuple(skipped),
        total_bytes_seen=state["total_seen"],
        total_bytes_included=state["total_included"],
        limit_hit=bool(state["limit_reasons"]),
        limit_reason=",".join(state["limit_reasons"]) or None,
        extractor_counts=dict(extractor_counts),
        diagnostic_counts=dict(diagnostic_counts),
    )
    digest = manifest_digest(manifest)
    return replace(manifest, manifest_sha256=digest)


def bulk_observations_from_plan(
    config: BulkSourceConfig,
    manifest: BulkManifest,
    *,
    repository_root: Path | str,
) -> tuple[RawObservation, ...]:
    repo_root = Path(repository_root).resolve()
    file_infos = [
        classify_path(repo_root, repo_root / item.repository_path)
        for item in manifest.included_files
    ]
    module_index = PythonModuleIndex.from_python_paths(
        (info.path for info in file_infos if info.language == "python"),
        repository_root=repo_root,
    )
    repository_paths = frozenset(info.path for info in file_infos)
    markdown_anchors = markdown_anchor_index(repo_root, file_infos)
    included_by_repository_path = {item.repository_path: item for item in manifest.included_files}
    observations: list[RawObservation] = []
    for file_info in file_infos:
        included = included_by_repository_path[file_info.path]
        routed = [file_info.to_observation()]
        routed.extend(
            observations_for_file_info(
                repo_root,
                file_info,
                module_index=module_index,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
            )
        )
        observations.extend(
            annotate_observation(
                observation,
                config=config,
                manifest=manifest,
                included=included,
            )
            for observation in routed
        )
    observations.extend(extract_css_selector_match_observations(observations))
    return tuple(observations)


def import_bulk_source(
    config_path: Path | str,
    *,
    repository_name: str,
    root_path: Path | str,
    psql_args: Sequence[str],
    git_commit: str | None = None,
    psql_command: str = "psql",
    loader: Callable[..., LoadSummary] = load_file_observations,
) -> BulkImportSummary:
    config = load_bulk_source_config(config_path)
    repo_root = Path(root_path).resolve()
    manifest = build_bulk_plan(config, repository_root=repo_root)
    observations = bulk_observations_from_plan(
        config,
        manifest,
        repository_root=repo_root,
    )
    output_path = write_bulk_run_files(
        manifest,
        observations=observations,
        repository_root=repo_root,
    )
    load_summary = loader(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=str(repo_root),
        git_commit=git_commit,
        psql_command=psql_command,
    )
    return BulkImportSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        corpus_kind=config.corpus_kind,
        policy_status=config.policy_status,
        bulk_run_id=manifest.bulk_run_id,
        bulk_manifest_id=manifest.bulk_manifest_id,
        observations=len(observations),
        included_files=manifest.file_count_included,
        skipped_files=manifest.file_count_skipped,
        output_path=output_path,
        output_path_summary=output_path.relative_to(repo_root).as_posix(),
        manifest=manifest,
        load_summary=load_summary,
    )


def observations_for_file_info(
    repo_root: Path,
    file_info: FileInfo,
    *,
    module_index: PythonModuleIndex,
    repository_paths: frozenset[str],
    markdown_anchors: Mapping[str, frozenset[str]],
) -> tuple[RawObservation, ...]:
    if file_info.language == "markdown":
        return extract_markdown_file_observations_from_file(
            repo_root,
            file_info,
            repository_paths=repository_paths,
            markdown_anchors=dict(markdown_anchors),
        )
    if file_info.language == "shell":
        return extract_shell_file_observations(repo_root, file_info.path)
    if file_info.language == "python":
        return extract_python_file_observations_from_file(
            repo_root,
            file_info.path,
            module_index=module_index,
        )
    if file_info.language == "ruby":
        return extract_ruby_file_observations_from_file(
            repo_root,
            file_info.path,
            repository_paths=repository_paths,
        )
    if file_info.language == "javascript":
        return extract_javascript_file_observations_from_file(
            repo_root,
            file_info.path,
            repository_paths=repository_paths,
        )
    if file_info.language == "eml":
        return extract_eml_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "mbox":
        return extract_mbox_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "nix":
        return extract_nix_file_observations_from_file(repo_root, file_info.path)
    if file_info.language in ("json", "xml"):
        feed_observations = extract_feed_file_observations_from_file(
            repo_root,
            file_info.path,
        )
        if feed_observations:
            return feed_observations
    if file_info.language in (
        "json",
        "jsonc",
        "jsonl",
        "toml",
        "plist",
        "xml",
        "yaml",
    ):
        return extract_config_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "html":
        return extract_html_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "css":
        return extract_css_file_observations_from_file(repo_root, file_info.path)
    if file_info.language in ("text", "csv", "tsv", "latex", "odf"):
        return extract_document_file_observations_from_file(
            repo_root,
            file_info.path,
            repository_paths=repository_paths,
        )
    return ()


def annotate_observation(
    observation: RawObservation,
    *,
    config: BulkSourceConfig,
    manifest: BulkManifest,
    included: BulkIncludedFile,
) -> RawObservation:
    metadata = dict(observation.metadata)
    metadata.update(
        {
            "source_id": config.source_id,
            "source_type": config.source_type,
            "corpus_kind": config.corpus_kind,
            "bulk_run_id": manifest.bulk_run_id,
            "bulk_manifest_id": manifest.bulk_manifest_id,
            "bulk_relative_path": included.relative_path,
            "bulk_file_sha256": included.sha256,
            "bulk_file_byte_count": included.byte_count,
            "bulk_extractor_route": included.route,
            "bulk_policy_status": config.policy_status,
            "bulk_retention_policy": config.retention_policy,
            "bulk_sensitivity": config.sensitivity,
        }
    )
    return replace(observation, metadata=metadata)


def write_bulk_run_files(
    manifest: BulkManifest,
    *,
    observations: Sequence[RawObservation],
    repository_root: Path,
) -> Path:
    output_path = (
        repository_root
        / ".repomap"
        / "bulk-runs"
        / manifest.source_id
        / manifest.bulk_run_id
    ).resolve()
    ensure_contained(output_path, repository_root, "bulk output path")
    output_path.mkdir(parents=True, exist_ok=True)
    write_json(output_path / "plan.json", manifest.to_jsonable())
    write_json(output_path / "manifest.json", manifest.to_jsonable())
    write_jsonl(
        output_path / "included-files.jsonl",
        [item.to_jsonable() for item in manifest.included_files],
    )
    write_jsonl(
        output_path / "skipped-files.jsonl",
        [item.to_jsonable() for item in manifest.skipped_files],
    )
    write_jsonl(
        output_path / "diagnostics.jsonl",
        [
            {"reason": reason, "count": count}
            for reason, count in sorted(manifest.diagnostic_counts.items())
        ],
    )
    write_jsonl(
        output_path / "observations.jsonl",
        [observation.to_dict() for observation in observations],
    )
    return output_path


def classify_bulk_route(path: Path) -> str | None:
    name = path.name
    if name in SPECIAL_FILENAME_ROUTES:
        return SPECIAL_FILENAME_ROUTES[name]
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if len(suffixes) >= 2 and "".join(suffixes[-2:]) in WARC_EXTENSIONS:
        return "warc"
    if suffixes and suffixes[-1] in WARC_EXTENSIONS:
        return "warc"
    if suffixes and suffixes[-1] in ARCHIVE_EXTENSIONS:
        return "archive"
    return EXTENSION_ROUTES.get(path.suffix.lower())


def route_included(config: BulkSourceConfig, path: Path, route: str) -> bool:
    if not config.include_extensions:
        return True
    allowed = frozenset(item.lower() for item in config.include_extensions)
    if path.name in SPECIAL_FILENAME_ROUTES:
        return path.name in config.include_extensions or route in allowed or ".rb" in allowed
    suffix = path.suffix.lower()
    if len(path.suffixes) >= 2 and "".join(path.suffixes[-2:]).lower() in allowed:
        return True
    return suffix in allowed


def deterministic_run_id(
    config: BulkSourceConfig,
    included: Sequence[BulkIncludedFile],
) -> str:
    inventory = [
        {
            "relative_path": item.relative_path,
            "route": item.route,
            "byte_count": item.byte_count,
            "sha256": item.sha256,
        }
        for item in included
    ]
    payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "corpus_kind": config.corpus_kind,
        "policy_status": config.policy_status,
        "root_path_summary": root_path_summary(config),
        "limits": {
            "max_files": config.max_files,
            "max_total_bytes": config.max_total_bytes,
            "max_file_bytes": config.max_file_bytes,
            "max_depth": config.max_depth,
            "follow_symlinks": config.follow_symlinks,
            "include_hidden": config.include_hidden,
        },
        "include_extensions": config.include_extensions,
        "excluded_directories": config.excluded_directories,
        "excluded_paths": config.excluded_paths,
        "inventory": inventory,
    }
    return "bulk-" + sha256_json(payload)[:24]


def manifest_digest(manifest: BulkManifest) -> str:
    payload = manifest.to_jsonable()
    payload["manifest_sha256"] = ""
    return sha256_json(payload)


def root_path_summary(config: BulkSourceConfig) -> str:
    configured = config.root_path_configured
    if Path(configured).is_absolute():
        return "absolute-path-sha256:" + sha256_text(configured)[:16]
    return Path(configured).as_posix()


def resolve_config_root(config_path: Path, configured: str) -> Path:
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def required_table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise BulkPolicyError(f"{key} table is required")
    return value


def table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, Mapping):
        raise BulkPolicyError(f"{key} table must be an object")
    return value


def required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BulkPolicyError(f"{key} is required")
    return value.strip()


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BulkPolicyError("optional string field must be a string")
    return value


def required_positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BulkPolicyError(f"{key} must be a positive integer")
    return value


def required_bool(payload: Mapping[str, Any], key: str) -> bool:
    if key not in payload:
        raise BulkPolicyError(f"{key} is required")
    return bool_value(payload[key], key)


def bool_value(value: object, key: str) -> bool:
    if not isinstance(value, bool):
        raise BulkPolicyError(f"{key} must be a boolean")
    return value


def string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BulkPolicyError("list field must be an array")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BulkPolicyError("list field values must be non-empty strings")
        result.append(item.strip())
    return tuple(result)


def normalized_path_tuple(value: object) -> tuple[str, ...]:
    return tuple(Path(item).as_posix().strip("/") for item in string_tuple(value))


def relative_to_root(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def depth(relative_path: str) -> int:
    return len(Path(relative_path).parts)


def is_excluded_path(relative_path: str, excluded_paths: Sequence[str]) -> bool:
    return any(
        relative_path == excluded or relative_path.startswith(f"{excluded}/")
        for excluded in excluded_paths
    )


def safe_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def ensure_contained(path: Path, root: Path, name: str) -> None:
    if not is_contained(path, root):
        raise BulkPolicyError(f"{name} escapes repository root")


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
