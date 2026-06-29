"""Stdlib AST-backed Python raw observation extraction."""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from repomap_kg import __version__
from repomap_kg.graph_keys import (
    external_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR_NAME = "repo-python"
SLUG_PATTERN = re.compile(r"[^0-9A-Za-z_.]+")


@dataclass(frozen=True)
class PythonModuleIndex:
    module_to_path: Mapping[str, str]
    path_to_module: Mapping[str, str]

    @classmethod
    def empty(cls) -> PythonModuleIndex:
        return cls(module_to_path={}, path_to_module={})

    @classmethod
    def from_modules(cls, modules: Mapping[str, str]) -> PythonModuleIndex:
        module_to_path = dict(modules)
        path_to_module = {path: module for module, path in module_to_path.items()}
        return cls(module_to_path=module_to_path, path_to_module=path_to_module)

    @classmethod
    def from_python_paths(
        cls,
        paths: Iterable[str],
        *,
        repository_root: Path | str | None = None,
    ) -> PythonModuleIndex:
        modules = {}
        for path in sorted(paths):
            module = importable_module_name(path, repository_root=repository_root)
            if module is not None:
                modules[module] = path
        return cls.from_modules(modules)

    def has_module(self, module: str) -> bool:
        return module in self.module_to_path


def importable_module_name(
    relative_path: str,
    *,
    repository_root: Path | str | None = None,
) -> str | None:
    if not relative_path.endswith(".py"):
        return None
    normalized_path = relative_path.replace("\\", "/")
    roots = package_roots(repository_root)
    for root in roots:
        prefix = f"{root}/" if root != "." else ""
        if root == "." or normalized_path.startswith(prefix):
            suffix = normalized_path.removeprefix(prefix)
            return module_name_from_suffix(suffix)
    return module_name_from_suffix(normalized_path)


def package_roots(repository_root: Path | str | None = None) -> tuple[str, ...]:
    roots = ["src/main/python"]
    roots.extend(pyproject_package_roots(repository_root))
    roots.extend(test_python_roots)
    return tuple(dict.fromkeys(roots))


def pyproject_package_roots(repository_root: Path | str | None) -> tuple[str, ...]:
    if repository_root is None:
        return ()
    pyproject_path = Path(repository_root) / "pyproject.toml"
    if not pyproject_path.exists():
        return ()
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return ()
    package_dir = (
        payload.get("tool", {})
        .get("setuptools", {})
        .get("package-dir", {})
    )
    if not isinstance(package_dir, Mapping):
        return ()
    roots = []
    for key in ("", "."):
        value = package_dir.get(key)
        if isinstance(value, str) and value.strip():
            roots.append(normalize_root(value))
    return tuple(roots)


test_python_roots = (
    "src/test/unit/python",
    "src/test/int/python",
)


def normalize_root(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")


def module_name_from_suffix(suffix: str) -> str | None:
    if not suffix.endswith(".py"):
        return None
    without_extension = suffix[:-3]
    if without_extension.endswith("/__init__"):
        without_extension = without_extension[: -len("/__init__")]
    elif without_extension == "__init__":
        return None
    parts = [part for part in without_extension.split("/") if part]
    if not parts:
        return None
    return ".".join(parts)


def extract_python_file_observations(
    relative_path: str,
    content: str,
    *,
    module_index: PythonModuleIndex,
    repository_root: Path | str | None = None,
) -> tuple[RawObservation, ...]:
    module = importable_module_name(relative_path, repository_root=repository_root)
    if module is None:
        return ()
    try:
        tree = ast.parse(content, filename=relative_path)
    except SyntaxError:
        return ()

    observations: list[RawObservation] = [
        python_module_observation(relative_path, module, tree, content)
    ]
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            observations.extend(
                python_import_observations(
                    relative_path,
                    module,
                    node,
                    module_index=module_index,
                )
            )
        elif isinstance(node, ast.ClassDef):
            observations.append(python_class_observation(relative_path, module, node))
            observations.extend(
                python_method_observations(relative_path, module, node)
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            observations.append(
                python_function_observation(relative_path, module, node)
            )
    return tuple(observations)


def python_module_observation(
    relative_path: str, module: str, tree: ast.Module, content: str
) -> RawObservation:
    line_count = max(1, len(content.splitlines()))
    return RawObservation(
        kind="python.module",
        source_id=f"{relative_path}#module:{module}",
        path=relative_path,
        start_line=1,
        end_line=line_count,
        name=module,
        target=python_module_key(module),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "module": module,
            "package_root": package_root_for_path(relative_path),
            "parser": "ast",
        },
    )


def python_import_observations(
    relative_path: str,
    source_module: str,
    node: ast.Import | ast.ImportFrom,
    *,
    module_index: PythonModuleIndex,
) -> tuple[RawObservation, ...]:
    observations = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            imported_module = alias.name
            target_key, resolution = import_target_for_absolute(
                imported_module,
                module_index=module_index,
            )
            observations.append(
                python_import_observation(
                    relative_path,
                    source_module,
                    node,
                    imported_module=imported_module,
                    imported_names=[alias.name],
                    alias=alias.asname,
                    level=0,
                    resolution=resolution,
                    target_key=target_key,
                )
            )
        return tuple(observations)

    base_module = node.module or ""
    for alias in node.names:
        imported_module, target_key, resolution = import_target_for_from(
            source_module,
            base_module,
            alias.name,
            node.level,
            module_index=module_index,
        )
        observations.append(
            python_import_observation(
                relative_path,
                source_module,
                node,
                imported_module=imported_module,
                imported_names=[alias.name],
                alias=alias.asname,
                level=node.level,
                resolution=resolution,
                target_key=target_key,
            )
        )
    return tuple(observations)


def python_import_observation(
    relative_path: str,
    source_module: str,
    node: ast.Import | ast.ImportFrom,
    *,
    imported_module: str,
    imported_names: list[str],
    alias: str | None,
    level: int,
    resolution: str,
    target_key: str,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "module": source_module,
        "imported_names": imported_names,
        "level": level,
        "resolution": resolution,
    }
    if imported_module:
        metadata["imported_module"] = imported_module
    if alias is not None:
        metadata["alias"] = alias
    return RawObservation(
        kind="python.import",
        source_id=(
            f"{relative_path}#import:{node.lineno}:"
            f"{slug(imported_module or '.'.join(imported_names))}"
        ),
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=imported_module or ".".join(imported_names),
        target=target_key,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def import_target_for_absolute(
    imported_module: str,
    *,
    module_index: PythonModuleIndex,
) -> tuple[str, str]:
    if module_index.has_module(imported_module):
        return python_module_key(imported_module), "local"
    return external_key("python.module", imported_module), "external"


def import_target_for_from(
    source_module: str,
    base_module: str,
    imported_name: str,
    level: int,
    *,
    module_index: PythonModuleIndex,
) -> tuple[str, str, str]:
    if level:
        resolved_base = resolve_relative_base(source_module, base_module, level)
        if resolved_base is None:
            return (
                "",
                unknown_key("python.module", "missing-package-context"),
                "unknown",
            )
        candidates = relative_module_candidates(
            resolved_base,
            base_module,
            imported_name,
        )
        for candidate in candidates:
            if module_index.has_module(candidate):
                return candidate, python_module_key(candidate), "local"
        return (
            candidates[0],
            unknown_key("python.module", "missing-module"),
            "unknown",
        )

    candidates = module_candidates(base_module, imported_name)
    for candidate in candidates:
        if module_index.has_module(candidate):
            return candidate, python_module_key(candidate), "local"
    if base_module and module_index.has_module(base_module):
        return base_module, python_module_key(base_module), "local"
    return base_module, external_key("python.module", base_module), "external"


def resolve_relative_base(
    source_module: str, base_module: str, level: int
) -> str | None:
    source_parts = source_module.split(".")
    if len(source_parts) < 2:
        return None
    package_parts = source_parts[:-1]
    if level > len(package_parts):
        return None
    prefix = package_parts[: len(package_parts) - level + 1]
    if base_module:
        prefix.extend(base_module.split("."))
    if not prefix:
        return None
    return ".".join(prefix)


def module_candidates(base_module: str, imported_name: str) -> tuple[str, ...]:
    if imported_name == "*":
        return (base_module,)
    if not base_module:
        return (imported_name,)
    return (f"{base_module}.{imported_name}", base_module)


def relative_module_candidates(
    resolved_base: str, base_module: str, imported_name: str
) -> tuple[str, ...]:
    if imported_name == "*":
        return (resolved_base,)
    if not base_module:
        return (f"{resolved_base}.{imported_name}",)
    return module_candidates(resolved_base, imported_name)


def python_class_observation(
    relative_path: str, module: str, node: ast.ClassDef
) -> RawObservation:
    return RawObservation(
        kind="python.class",
        source_id=f"{relative_path}#class:{node.lineno}:{slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=node.name,
        target=python_class_key(module, node.name),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "module": module,
            "bases": [safe_unparse(base) for base in node.bases],
            "decorators": [safe_unparse(item) for item in node.decorator_list],
        },
    )


def python_function_observation(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> RawObservation:
    return RawObservation(
        kind="python.function",
        source_id=f"{relative_path}#function:{node.lineno}:{slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=node.name,
        target=python_function_key(module, node.name),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "module": module,
            "async": isinstance(node, ast.AsyncFunctionDef),
            "decorators": [safe_unparse(item) for item in node.decorator_list],
        },
    )


def python_method_observations(
    relative_path: str, module: str, class_node: ast.ClassDef
) -> tuple[RawObservation, ...]:
    observations = []
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            observations.append(
                RawObservation(
                    kind="python.method",
                    source_id=(
                        f"{relative_path}#method:{node.lineno}:"
                        f"{slug(class_node.name + '.' + node.name)}"
                    ),
                    path=relative_path,
                    start_line=node.lineno,
                    end_line=end_line(node),
                    name=node.name,
                    target=python_method_key(module, class_node.name, node.name),
                    confidence="extracted",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata={
                        "module": module,
                        "class": class_node.name,
                        "async": isinstance(node, ast.AsyncFunctionDef),
                        "decorators": [
                            safe_unparse(item) for item in node.decorator_list
                        ],
                    },
                )
            )
    return tuple(observations)


def package_root_for_path(relative_path: str) -> str:
    normalized_path = relative_path.replace("\\", "/")
    for root in ("src/main/python", *test_python_roots):
        if normalized_path.startswith(f"{root}/"):
            return root
    return "."


def safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except ValueError:
        return node.__class__.__name__


def end_line(node: ast.AST) -> int:
    lineno = getattr(node, "end_lineno", None)
    if isinstance(lineno, int) and lineno > 0:
        return lineno
    return node.lineno


def slug(value: str) -> str:
    return SLUG_PATTERN.sub("-", value).strip("-") or "unknown"
