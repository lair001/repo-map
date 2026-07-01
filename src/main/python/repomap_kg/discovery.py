"""Repository file discovery and classification."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_kg import __version__
from repomap_kg.config_extractor import extract_config_file_observations
from repomap_kg.css import extract_css_file_observations
from repomap_kg.css_html_matching import extract_css_selector_match_observations
from repomap_kg.documents import (
    extract_document_file_observations,
    extract_odf_file_observations,
)
from repomap_kg.feed import extract_feed_file_observations
from repomap_kg.html import extract_html_file_observations
from repomap_kg.markdown import (
    extract_markdown_file_observations,
    markdown_anchors_for_content,
)
from repomap_kg.nix import extract_nix_file_observations
from repomap_kg.observations import RawObservation
from repomap_kg.profiles import ProjectProfile
from repomap_kg.python_extractor import (
    PythonModuleIndex,
    extract_python_file_observations,
)
from repomap_kg.shell import extract_shell_observations


IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
    }
)
GENERATED_DIR_NAMES = frozenset({"coverage", "generated", "reports"})
LANGUAGE_BY_EXTENSION = {
    ".applescript": "applescript",
    ".awk": "awk",
    ".bash": "shell",
    ".css": "css",
    ".csv": "csv",
    ".htm": "html",
    ".html": "html",
    ".json": "json",
    ".jsonc": "jsonc",
    ".jsonl": "jsonl",
    ".md": "markdown",
    ".nix": "nix",
    ".ods": "odf",
    ".odt": "odf",
    ".ots": "odf",
    ".ott": "odf",
    ".plist": "plist",
    ".py": "python",
    ".rb": "ruby",
    ".sh": "shell",
    ".sql": "sql",
    ".latex": "latex",
    ".tex": "latex",
    ".tsv": "tsv",
    ".txt": "text",
    ".toml": "toml",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zsh": "shell",
}
CONFIG_FILENAMES = frozenset(
    {
        ".gitignore",
        "flake.lock",
        "flake.nix",
        "pyproject.toml",
        "requirements.txt",
    }
)


@dataclass(frozen=True)
class FileInfo:
    path: str
    language: str
    role: str
    content_hash: str
    executable: bool
    generated: bool
    confidence: str = "extracted"

    def to_observation(self) -> RawObservation:
        return RawObservation(
            kind="file",
            source_id=self.path,
            path=self.path,
            name=self.path,
            confidence=self.confidence,
            extractor="repo-discovery",
            extractor_version=__version__,
            metadata=self.to_metadata(),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "role": self.role,
            "content_hash": self.content_hash,
            "executable": self.executable,
            "generated": self.generated,
        }


def discover_repository(
    root: Path | str, *, profile: ProjectProfile | None = None
) -> list[FileInfo]:
    repository_root = Path(root).resolve()
    files = []
    for directory, dirnames, filenames in os.walk(repository_root):
        dirnames[:] = sorted(
            dirname for dirname in dirnames if dirname not in IGNORED_DIR_NAMES
        )
        directory_path = Path(directory)
        for filename in sorted(filenames):
            file_path = directory_path / filename
            files.append(classify_path(repository_root, file_path, profile=profile))
    return sorted(files, key=lambda file_info: file_info.path)


def discover_observations(
    root: Path | str, *, profile: ProjectProfile | None = None
) -> list[RawObservation]:
    repository_root = Path(root).resolve()
    file_infos = discover_repository(repository_root, profile=profile)
    module_index = PythonModuleIndex.from_python_paths(
        (file_info.path for file_info in file_infos if file_info.language == "python"),
        repository_root=repository_root,
    )
    repository_paths = frozenset(file_info.path for file_info in file_infos)
    markdown_anchors = markdown_anchor_index(repository_root, file_infos)
    observations = []
    for file_info in file_infos:
        observations.append(file_info.to_observation())
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
            observations.extend(
                extract_shell_file_observations(repository_root, file_info.path)
            )
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
                continue
        if file_info.language in ("json", "jsonc", "jsonl", "toml", "plist", "xml"):
            observations.extend(
                extract_config_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "html":
            observations.extend(
                extract_html_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "css":
            observations.extend(
                extract_css_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language in ("text", "csv", "tsv", "latex", "odf"):
            observations.extend(
                extract_document_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    repository_paths=repository_paths,
                )
            )
    observations.extend(extract_css_selector_match_observations(observations))
    return observations


def extract_shell_file_observations(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_shell_observations(relative_path, content)


def extract_python_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
    *,
    module_index: PythonModuleIndex,
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_python_file_observations(
        relative_path,
        content,
        module_index=module_index,
        repository_root=repository_root,
    )


def extract_nix_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_nix_file_observations(
        relative_path,
        content,
        flake_ref=repository_root.name,
    )


def extract_config_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_config_file_observations(relative_path, content)


def extract_feed_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_feed_file_observations(relative_path, content)


def extract_html_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_html_file_observations(relative_path, content)


def extract_css_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_css_file_observations(relative_path, content)


def extract_document_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    suffix = Path(relative_path).suffix.lower()
    if suffix in (".odt", ".ods", ".ott", ".ots"):
        try:
            content = (repository_root / relative_path).read_bytes()
        except OSError as error:
            return (
                RawObservation(
                    kind="document.parse_error",
                    source_id=f"{relative_path}#document-parse-error:read",
                    path=relative_path,
                    confidence="unknown",
                    extractor="repo-documents",
                    extractor_version=__version__,
                    metadata={
                        "format": suffix.lstrip(".") or "unknown",
                        "parser": "stdlib-document-conservative",
                        "error_kind": "read-error",
                        "message_summary": str(error)[:120],
                        "recovered": False,
                    },
                ),
            )
        return extract_odf_file_observations(
            relative_path,
            content,
            repository_paths=repository_paths,
        )
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return (
            RawObservation(
                kind="document.parse_error",
                source_id=f"{relative_path}#document-parse-error:decode",
                path=relative_path,
                confidence="unknown",
                extractor="repo-documents",
                extractor_version=__version__,
                metadata={
                    "format": Path(relative_path).suffix.lower().lstrip(".") or "unknown",
                    "parser": "stdlib-document-conservative",
                    "error_kind": "decode-error",
                    "message_summary": "file is not valid UTF-8",
                    "recovered": False,
                },
            ),
        )
    return extract_document_file_observations(
        relative_path,
        content,
        repository_paths=repository_paths,
    )


def extract_markdown_file_observations_from_file(
    repository_root: Path,
    file_info: FileInfo,
    *,
    repository_paths: frozenset[str],
    markdown_anchors: dict[str, frozenset[str]],
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / file_info.path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_markdown_file_observations(
        file_info.path,
        content,
        repository_paths=repository_paths,
        markdown_anchors=markdown_anchors,
        content_hash=file_info.content_hash,
        generated=file_info.generated,
    )


def markdown_anchor_index(
    repository_root: Path,
    file_infos: list[FileInfo],
) -> dict[str, frozenset[str]]:
    anchors: dict[str, frozenset[str]] = {}
    for file_info in file_infos:
        if file_info.language != "markdown":
            continue
        try:
            content = (repository_root / file_info.path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        anchors[file_info.path] = frozenset(markdown_anchors_for_content(content))
    return anchors


def classify_path(
    root: Path | str, path: Path | str, *, profile: ProjectProfile | None = None
) -> FileInfo:
    repository_root = Path(root).resolve()
    file_path = Path(path).resolve()
    relative_path = file_path.relative_to(repository_root).as_posix()
    executable = os.access(file_path, os.X_OK)
    generated = is_generated(relative_path)
    language = detect_language(file_path)
    role = detect_role(relative_path, executable=executable, generated=generated)
    confidence = "extracted"
    if profile is not None:
        generated = profile.generated_for_path(relative_path, generated)
        role = profile.role_for_path(relative_path, role)
        confidence = profile.confidence_for_path(relative_path, confidence)

    return FileInfo(
        path=relative_path,
        language=language,
        role=role,
        content_hash=content_hash(file_path),
        executable=executable,
        generated=generated,
        confidence=confidence,
    )


def detect_language(path: Path) -> str:
    language = LANGUAGE_BY_EXTENSION.get(path.suffix)
    if language is not None:
        return language
    shebang = first_line(path)
    if shebang.startswith("#!"):
        if "python" in shebang:
            return "python"
        if "bash" in shebang or "sh" in shebang or "zsh" in shebang:
            return "shell"
        if "ruby" in shebang:
            return "ruby"
    return "unknown"


def detect_role(relative_path: str, *, executable: bool, generated: bool) -> str:
    parts = relative_path.split("/")
    filename = parts[-1]
    if generated:
        return "generated"
    if "test" in parts or "tests" in parts or ".test." in filename:
        return "test"
    if relative_path.startswith("docs/") or filename.endswith(".md"):
        return "documentation"
    if (
        filename in CONFIG_FILENAMES
        or filename.endswith(".plist")
        or relative_path.startswith(".github/")
    ):
        return "config"
    if executable or relative_path.startswith("bin/"):
        return "entrypoint"
    if relative_path.startswith("src/"):
        return "source"
    return "unknown"


def is_generated(relative_path: str) -> bool:
    parts = relative_path.split("/")
    return any(part in GENERATED_DIR_NAMES for part in parts)


def first_line(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().strip()
    except UnicodeDecodeError:
        return ""


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
