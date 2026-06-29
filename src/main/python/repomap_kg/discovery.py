"""Repository file discovery and classification."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_kg import __version__
from repomap_kg.observations import RawObservation
from repomap_kg.profiles import ProjectProfile
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
    ".json": "json",
    ".md": "markdown",
    ".nix": "nix",
    ".py": "python",
    ".rb": "ruby",
    ".sh": "shell",
    ".sql": "sql",
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
    observations = []
    for file_info in discover_repository(repository_root, profile=profile):
        observations.append(file_info.to_observation())
        if file_info.language == "shell":
            observations.extend(
                extract_shell_file_observations(repository_root, file_info.path)
            )
    return observations


def extract_shell_file_observations(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    return extract_shell_observations(relative_path, content)


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
    if filename in CONFIG_FILENAMES or relative_path.startswith(".github/"):
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
