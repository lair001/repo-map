"""Stdlib AST-backed Python raw observation extraction."""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath
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
PYTHON_TEST_MAX_OBSERVATIONS = 512
PYTHON_TEST_MAX_METADATA_STRING = 160
UNITTEST_ASSERTION_METHODS = frozenset(
    (
        "assertEqual",
        "assertTrue",
        "assertFalse",
        "assertIsNone",
        "assertIsNotNone",
        "assertIn",
        "assertNotIn",
        "assertRaises",
        "assertGreater",
        "assertLess",
        "assertRegex",
    )
)


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
    except SyntaxError as error:
        return (python_parse_error_observation(relative_path, module, error),)

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
    observations.extend(
        python_test_profile_observations(relative_path, module, tree)
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


def python_parse_error_observation(
    relative_path: str,
    module: str,
    error: SyntaxError,
) -> RawObservation:
    line_number = error.lineno if isinstance(error.lineno, int) else None
    return RawObservation(
        kind="python.parse_error",
        source_id=f"{relative_path}#python-parse-error:{line_number or 'module'}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=module,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python",
            "parser": "stdlib-ast",
            "error_kind": "malformed-python",
            "message_summary": (error.msg or "syntax error")[:120],
            "recovered": False,
            "raw_profile_only": True,
        },
    )


def python_test_profile_observations(
    relative_path: str,
    module: str,
    tree: ast.Module,
) -> tuple[RawObservation, ...]:
    if not _looks_like_test_path(relative_path):
        return ()
    observations: list[RawObservation] = []
    frameworks: set[str] = set()
    unittest_case_count = 0
    pytest_test_count = 0
    fixture_count = 0
    assertion_total = 0
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            is_unittest = _is_unittest_case(node)
            is_pytest_class = node.name.startswith("Test")
            if is_unittest:
                frameworks.add("unittest")
                test_methods = _test_methods(node)
                unittest_case_count += 1
                observations.append(
                    python_test_profile_observation(
                        "python.unittest_case",
                        relative_path,
                        module,
                        node,
                        name=node.name,
                        metadata={
                            "test_framework": "unittest",
                            "class_name": node.name,
                            "test_method_count": len(test_methods),
                            "setup_teardown_methods": _setup_teardown_methods(node),
                        },
                    )
                )
                for method in test_methods:
                    observations.append(
                        python_test_profile_observation(
                            "python.test_method",
                            relative_path,
                            module,
                            method,
                            name=method.name,
                            metadata={
                                "test_framework": "unittest",
                                "class_name": node.name,
                                "test_name": method.name,
                                "decorator_count": len(method.decorator_list),
                                "skipped": _has_skip_decorator(method),
                            },
                        )
                    )
                    assertion_count = _assertion_count(method)
                    assertion_total += assertion_count
                    if assertion_count:
                        observations.append(
                            python_test_assertion_observation(
                                relative_path,
                                module,
                                method,
                                assertion_count=assertion_count,
                                test_framework="unittest",
                                class_name=node.name,
                            )
                        )
            if is_pytest_class and not is_unittest:
                frameworks.add("pytest")
                for method in _test_methods(node):
                    pytest_test_count += 1
                    observations.append(
                        python_test_profile_observation(
                            "python.test_method",
                            relative_path,
                            module,
                            method,
                            name=method.name,
                            metadata={
                                "test_framework": "pytest",
                                "class_name": node.name,
                                "test_name": method.name,
                                "decorator_count": len(method.decorator_list),
                            },
                        )
                    )
                    observations.append(
                        python_test_profile_observation(
                            "python.pytest_test",
                            relative_path,
                            module,
                            method,
                            name=method.name,
                            metadata={
                                "test_framework": "pytest",
                                "class_name": node.name,
                                "test_name": method.name,
                                "mark_names": _pytest_mark_names(method),
                            },
                        )
                    )
                    assertion_count = _assertion_count(method)
                    assertion_total += assertion_count
                    if assertion_count:
                        observations.append(
                            python_test_assertion_observation(
                                relative_path,
                                module,
                                method,
                                assertion_count=assertion_count,
                                test_framework="pytest",
                                class_name=node.name,
                            )
                        )
                    if _has_pytest_parametrize(method):
                        observations.append(
                            python_test_parametrize_observation(
                                relative_path,
                                module,
                                method,
                                class_name=node.name,
                            )
                        )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_pytest_fixture(node):
                frameworks.add("pytest")
                fixture_count += 1
                for kind in ("python.test_fixture", "python.pytest_fixture"):
                    observations.append(
                        python_test_profile_observation(
                            kind,
                            relative_path,
                            module,
                            node,
                            name=node.name,
                            metadata={
                                "test_framework": "pytest",
                                "fixture_name": node.name,
                                "decorator_count": len(node.decorator_list),
                            },
                        )
                    )
            if node.name.startswith("test_"):
                frameworks.add("pytest")
                pytest_test_count += 1
                observations.append(
                    python_test_profile_observation(
                        "python.test_function",
                        relative_path,
                        module,
                        node,
                        name=node.name,
                        metadata={
                            "test_framework": "pytest",
                            "test_name": node.name,
                            "decorator_count": len(node.decorator_list),
                            "mark_names": _pytest_mark_names(node),
                        },
                    )
                )
                observations.append(
                    python_test_profile_observation(
                        "python.pytest_test",
                        relative_path,
                        module,
                        node,
                        name=node.name,
                        metadata={
                            "test_framework": "pytest",
                            "test_name": node.name,
                            "mark_names": _pytest_mark_names(node),
                        },
                    )
                )
                assertion_count = _assertion_count(node)
                assertion_total += assertion_count
                if assertion_count:
                    observations.append(
                        python_test_assertion_observation(
                            relative_path,
                            module,
                            node,
                            assertion_count=assertion_count,
                            test_framework="pytest",
                        )
                    )
                if _has_pytest_parametrize(node):
                    observations.append(
                        python_test_parametrize_observation(
                            relative_path,
                            module,
                            node,
                            class_name=None,
                        )
                    )
    if observations:
        observations.insert(
            0,
            python_test_file_observation(
                relative_path,
                module,
                tree,
                test_frameworks=frameworks or {"unknown"},
                unittest_case_count=unittest_case_count,
                pytest_test_count=pytest_test_count,
                fixture_count=fixture_count,
                assertion_count=assertion_total,
            ),
        )
    return tuple(observations[:PYTHON_TEST_MAX_OBSERVATIONS])


def python_test_file_observation(
    relative_path: str,
    module: str,
    tree: ast.Module,
    *,
    test_frameworks: set[str],
    unittest_case_count: int,
    pytest_test_count: int,
    fixture_count: int,
    assertion_count: int,
) -> RawObservation:
    end = max(1, getattr(tree, "end_lineno", 1) or 1)
    return RawObservation(
        kind="python.test_file",
        source_id=f"{relative_path}#python-test-file",
        path=relative_path,
        start_line=1,
        end_line=end,
        name=module,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python",
            "module": module,
            "test_frameworks": sorted(test_frameworks),
            "unittest_case_count": unittest_case_count,
            "pytest_test_count": pytest_test_count,
            "fixture_count": fixture_count,
            "assertion_count": assertion_count,
            "raw_profile_only": True,
        },
    )


def python_test_profile_observation(
    kind: str,
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    name: str,
    metadata: dict[str, Any],
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind.replace('.', '-')}:"
        f"{getattr(node, 'lineno', 'module')}:{slug(name)}",
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=end_line(node),
        name=name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python",
            "module": module,
            "raw_profile_only": True,
            **metadata,
        },
    )


def python_test_assertion_observation(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    assertion_count: int,
    test_framework: str,
    class_name: str | None = None,
) -> RawObservation:
    metadata = {
        "profile": "python",
        "source_format": "python",
        "module": module,
        "test_framework": test_framework,
        "test_name": node.name,
        "assertion_count": assertion_count,
        "raw_profile_only": True,
    }
    if class_name is not None:
        metadata["class_name"] = class_name
    return RawObservation(
        kind="python.test_assertion",
        source_id=f"{relative_path}#python-test-assertion:{node.lineno}:{slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=node.name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def python_test_parametrize_observation(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    class_name: str | None,
) -> RawObservation:
    metadata = {
        "profile": "python",
        "source_format": "python",
        "module": module,
        "test_framework": "pytest",
        "test_name": node.name,
        "parametrize": True,
        "raw_profile_only": True,
    }
    if class_name is not None:
        metadata["class_name"] = class_name
    return RawObservation(
        kind="python.test_parametrize",
        source_id=f"{relative_path}#python-test-parametrize:{node.lineno}:{slug(node.name)}",
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=node.name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
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


def _looks_like_test_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    filename = PurePath(normalized).name
    parts = set(normalized.split("/"))
    return (
        "tests" in parts
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or "/test_" in normalized
    )


def _test_methods(
    class_node: ast.ClassDef,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    return tuple(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def _is_unittest_case(class_node: ast.ClassDef) -> bool:
    return any(
        _ast_name(base) in ("unittest.TestCase", "TestCase")
        for base in class_node.bases
    )


def _setup_teardown_methods(class_node: ast.ClassDef) -> list[str]:
    names = []
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            "setUp",
            "tearDown",
            "setUpClass",
            "tearDownClass",
        ):
            names.append(node.name)
    return sorted(names)


def _has_skip_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("skip" in _ast_name(item).lower() for item in node.decorator_list)


def _is_pytest_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _ast_name(decorator) in ("pytest.fixture", "fixture")
        for decorator in node.decorator_list
    )


def _has_pytest_parametrize(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _ast_name(decorator) in ("pytest.mark.parametrize", "mark.parametrize")
        for decorator in node.decorator_list
    )


def _pytest_mark_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names = []
    for decorator in node.decorator_list:
        decorator_name = _ast_name(decorator)
        if decorator_name.startswith("pytest.mark."):
            names.append(decorator_name.removeprefix("pytest.mark."))
        elif decorator_name.startswith("mark."):
            names.append(decorator_name.removeprefix("mark."))
    return sorted(names)


def _assertion_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            count += 1
        elif isinstance(child, ast.Call):
            call_name = _ast_name(child.func)
            if call_name.split(".")[-1] in UNITTEST_ASSERTION_METHODS:
                count += 1
    return count


def _ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _ast_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _ast_name(node.value)
    return ""


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
