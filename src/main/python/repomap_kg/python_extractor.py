"""Stdlib AST-backed Python raw observation extraction."""

from __future__ import annotations

import ast
import hashlib
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
PYTHON_WEB_MAX_OBSERVATIONS = 512
PYTHON_WEB_MAX_ROUTES_PER_FILE = 64
PYTHON_WEB_MAX_METADATA_STRING = 160
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
WEB_HTTP_METHODS = frozenset(
    ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
)
FLASK_METHOD_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
}
FASTAPI_METHOD_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "options": "OPTIONS",
    "head": "HEAD",
}
PYTHON_WEB_SECRET_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "key",
    "private_key",
    "access_key",
    "secret_key",
    "client_secret",
    "credential",
    "connection_string",
    "auth",
    "bearer",
    "session",
    "cookie",
    "database_url",
    "django_secret_key",
    "flask_secret_key",
    "sqlalchemy_database_uri",
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
    observations.extend(
        python_web_framework_observations(relative_path, module, tree)
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


def python_web_framework_observations(
    relative_path: str,
    module: str,
    tree: ast.Module,
) -> tuple[RawObservation, ...]:
    aliases = _python_web_import_aliases(tree)
    flask_apps: set[str] = set()
    flask_blueprints: dict[str, str] = {}
    fastapi_apps: set[str] = set()
    fastapi_routers: set[str] = set()
    observations: list[RawObservation] = []
    route_count = 0
    route_limit_reported = False

    def add(observation: RawObservation) -> None:
        nonlocal route_count, route_limit_reported
        if observation.kind in (
            "python.flask_route",
            "python.fastapi_route",
            "python.django_urlpattern",
        ):
            if route_count >= PYTHON_WEB_MAX_ROUTES_PER_FILE:
                if not route_limit_reported:
                    observations.append(
                        python_web_parse_error_observation(
                            relative_path,
                            module,
                            observation,
                            error_kind="python-web-profile-limit",
                            framework=observation.metadata.get(
                                "framework", "python-web"
                            ),
                            message_summary="route observation limit reached",
                            recovered=True,
                        )
                    )
                    route_limit_reported = True
                return
            route_count += 1
        observations.append(observation)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = _assignment_value(node)
            if isinstance(value, ast.Call):
                call_name = _qualified_ast_name(value.func, aliases)
                for target_name in _assignment_names(node):
                    if call_name == "flask.Flask":
                        flask_apps.add(target_name)
                        add(
                            python_web_profile_observation(
                                "python.flask_app",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "flask",
                                    "app_name": target_name,
                                },
                            )
                        )
                    elif call_name == "flask.Blueprint":
                        blueprint_name = (
                            _literal_string(value.args[0])
                            if value.args
                            else None
                        ) or target_name
                        flask_blueprints[target_name] = _bounded_metadata_string(
                            blueprint_name
                        )
                        add(
                            python_web_profile_observation(
                                "python.flask_blueprint",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "flask",
                                    "blueprint_name": flask_blueprints[target_name],
                                    "blueprint_variable": target_name,
                                },
                            )
                        )
                    elif call_name == "fastapi.FastAPI":
                        fastapi_apps.add(target_name)
                        add(
                            python_web_profile_observation(
                                "python.fastapi_app",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "fastapi",
                                    "app_name": target_name,
                                },
                            )
                        )
                    elif call_name == "fastapi.APIRouter":
                        fastapi_routers.add(target_name)
                        add(
                            python_web_profile_observation(
                                "python.fastapi_router",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "fastapi",
                                    "router_name": target_name,
                                },
                            )
                        )
            for target in _assignment_target_nodes(node):
                add_config_redaction_if_needed(
                    add,
                    relative_path,
                    module,
                    node,
                    target,
                    value,
                    flask_apps=flask_apps,
                    aliases=aliases,
                    relative_path_for_settings=relative_path,
                )

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    flask_route = _flask_route_from_decorator(
                        relative_path,
                        module,
                        decorator,
                        node,
                        flask_apps=flask_apps,
                        flask_blueprints=flask_blueprints,
                    )
                    if flask_route is not None:
                        add(flask_route)
                        add(
                            python_web_reference_observation(
                                relative_path,
                                module,
                                decorator,
                                name=node.name,
                                target=python_function_key(module, node.name),
                                framework="flask",
                                reference_kind="flask_route_handler",
                                metadata={"handler_name": node.name},
                            )
                        )
                        if flask_route.metadata.get("dynamic"):
                            add(
                                python_web_parse_error_observation(
                                    relative_path,
                                    module,
                                    decorator,
                                    error_kind="dynamic-python-web-route",
                                    framework="flask",
                                    message_summary="dynamic Flask route expression",
                                    recovered=True,
                                    dynamic=True,
                                )
                            )
                    fastapi_route = _fastapi_route_from_decorator(
                        relative_path,
                        module,
                        decorator,
                        node,
                        fastapi_apps=fastapi_apps,
                        fastapi_routers=fastapi_routers,
                        aliases=aliases,
                    )
                    if fastapi_route is not None:
                        add(fastapi_route)
                        add(
                            python_web_reference_observation(
                                relative_path,
                                module,
                                decorator,
                                name=node.name,
                                target=python_function_key(module, node.name),
                                framework="fastapi",
                                reference_kind="fastapi_route_handler",
                                metadata={"handler_name": node.name},
                            )
                        )
                        if fastapi_route.metadata.get("dynamic"):
                            add(
                                python_web_parse_error_observation(
                                    relative_path,
                                    module,
                                    decorator,
                                    error_kind="dynamic-python-web-route",
                                    framework="fastapi",
                                    message_summary="dynamic FastAPI route expression",
                                    recovered=True,
                                    dynamic=True,
                                )
                            )
            for dependency in _fastapi_dependencies(node, aliases):
                add(
                    python_web_profile_observation(
                        "python.fastapi_dependency",
                        relative_path,
                        module,
                        dependency["node"],
                        name=dependency["name"],
                        metadata={
                            "framework": "fastapi",
                            "handler_name": node.name,
                            "dependency_name": dependency["name"],
                            "dependency_kind": dependency["kind"],
                        },
                    )
                )
                if dependency["target"]:
                    add(
                        python_web_reference_observation(
                            relative_path,
                            module,
                            dependency["node"],
                            name=dependency["name"],
                            target=external_key(
                                "python.dependency", dependency["target"]
                            ),
                            framework="fastapi",
                            reference_kind="fastapi_dependency",
                            metadata={"handler_name": node.name},
                        )
                    )
            for redaction in _function_default_redactions(
                relative_path,
                module,
                node,
            ):
                add(redaction)
        elif isinstance(node, ast.ClassDef):
            django_model = _django_model_observation(relative_path, module, node)
            if django_model is not None:
                add(django_model)
            django_app = _django_app_observation(relative_path, module, node)
            if django_app is not None:
                add(django_app)

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if _looks_like_django_settings_path(relative_path):
                for setting in _django_setting_observations(relative_path, module, node):
                    add(setting)
            if _assigns_name(node, "urlpatterns"):
                for item in _django_urlpattern_observations(
                    relative_path, module, node
                ):
                    add(item)
                    if item.metadata.get("dynamic"):
                        add(
                            python_web_parse_error_observation(
                                relative_path,
                                module,
                                item,
                                error_kind="dynamic-python-web-route",
                                framework="django",
                                message_summary="dynamic Django URL pattern",
                                recovered=True,
                                dynamic=True,
                            )
                        )
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            flask_add_rule = _flask_add_url_rule_observation(
                relative_path,
                module,
                node.value,
                flask_apps=flask_apps,
                flask_blueprints=flask_blueprints,
            )
            if flask_add_rule is not None:
                add(flask_add_rule)
                handler_name = flask_add_rule.metadata.get("handler_name")
                if isinstance(handler_name, str):
                    add(
                        python_web_reference_observation(
                            relative_path,
                            module,
                            node.value,
                            name=handler_name,
                            target=python_function_key(module, handler_name),
                            framework="flask",
                            reference_kind="flask_route_handler",
                            metadata={"handler_name": handler_name},
                        )
                    )
            fastapi_include = _fastapi_include_router_reference(
                relative_path,
                module,
                node.value,
                fastapi_apps=fastapi_apps,
                fastapi_routers=fastapi_routers,
            )
            if fastapi_include is not None:
                add(fastapi_include)

    if len(observations) > PYTHON_WEB_MAX_OBSERVATIONS:
        observations = observations[:PYTHON_WEB_MAX_OBSERVATIONS]
        observations.append(
            python_web_parse_error_observation(
                relative_path,
                module,
                tree,
                error_kind="python-web-profile-limit",
                framework="python-web",
                message_summary="framework observation limit reached",
                recovered=True,
            )
        )
    return tuple(observations)


def python_web_profile_observation(
    kind: str,
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    name: str,
    metadata: dict[str, Any],
    target: str | None = None,
    confidence: str = "extracted",
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind.replace('.', '-')}:{_line_slug(node)}:{slug(name)}",
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=end_line(node) if hasattr(node, "lineno") else None,
        name=name,
        target=target,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python-ast",
            "module": module,
            "raw_profile_only": True,
            "not_executed": True,
            "not_fetched": True,
            **metadata,
        },
    )


def python_web_reference_observation(
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    name: str,
    target: str,
    framework: str,
    reference_kind: str,
    metadata: dict[str, Any] | None = None,
) -> RawObservation:
    payload = {
        "profile": "python",
        "source_format": "python-ast",
        "module": module,
        "framework": framework,
        "reference_kind": reference_kind,
        "not_executed": True,
        "not_fetched": True,
        "raw_profile_only": True,
    }
    if metadata:
        payload.update(metadata)
    return RawObservation(
        kind="python.reference",
        source_id=(
            f"{relative_path}#python-reference:{_line_slug(node)}:"
            f"{slug(reference_kind)}:{slug(name)}"
        ),
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=end_line(node) if hasattr(node, "lineno") else None,
        name=name,
        target=target,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=payload,
    )


def python_web_parse_error_observation(
    relative_path: str,
    module: str,
    node: ast.AST | RawObservation,
    *,
    error_kind: str,
    framework: str,
    message_summary: str,
    recovered: bool,
    dynamic: bool = False,
) -> RawObservation:
    line_number = getattr(node, "lineno", None)
    if isinstance(node, RawObservation):
        line_number = node.start_line
    return RawObservation(
        kind="python.parse_error",
        source_id=(
            f"{relative_path}#python-web-diagnostic:{line_number or 'module'}:"
            f"{slug(error_kind)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=module,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python-ast",
            "framework": framework,
            "error_kind": error_kind,
            "message_summary": _bounded_metadata_string(message_summary),
            "dynamic": dynamic,
            "recovered": recovered,
            "raw_profile_only": True,
            "not_executed": True,
            "not_fetched": True,
        },
    )


def python_web_redaction_observation(
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    framework: str,
    name: str,
    redaction_reason: str,
    field_name: str | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "profile": "python",
        "source_format": "python-ast",
        "module": module,
        "framework": framework,
        "redacted": True,
        "redaction_reason": redaction_reason,
        "raw_profile_only": True,
        "not_executed": True,
        "not_fetched": True,
    }
    if field_name is not None:
        metadata["field_name"] = _bounded_metadata_string(field_name)
    return RawObservation(
        kind="python.redaction",
        source_id=(
            f"{relative_path}#python-redaction:{_line_slug(node)}:"
            f"{slug(framework)}:{slug(name)}"
        ),
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=end_line(node) if hasattr(node, "lineno") else None,
        name=_bounded_metadata_string(name),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _python_web_import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                if alias.name in ("flask", "fastapi", "django"):
                    aliases[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local_name = alias.asname or alias.name
                aliases[local_name] = f"{node.module}.{alias.name}"
    return aliases


def _qualified_ast_name(node: ast.AST, aliases: Mapping[str, str]) -> str:
    raw_name = _ast_name(node)
    if not raw_name:
        return ""
    first, *rest = raw_name.split(".")
    mapped = aliases.get(first)
    if mapped is None:
        return raw_name
    return ".".join((mapped, *rest))


def _flask_route_from_decorator(
    relative_path: str,
    module: str,
    call: ast.Call,
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    flask_apps: set[str],
    flask_blueprints: Mapping[str, str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if receiver not in flask_apps and receiver not in flask_blueprints:
        return None
    if attr == "route":
        methods = _methods_from_keyword(call, default=("GET",))
    elif attr in FLASK_METHOD_DECORATORS:
        methods = (FLASK_METHOD_DECORATORS[attr],)
    else:
        return None
    route_metadata = _route_path_metadata(_call_arg(call, 0))
    metadata = {
        "framework": "flask",
        "handler_name": function_node.name,
        "decorator_name": f"{receiver}.{attr}",
        "receiver_name": receiver,
        "http_methods": list(methods),
        "dynamic": route_metadata["dynamic"],
        **route_metadata,
    }
    if receiver in flask_blueprints:
        metadata["blueprint_name"] = flask_blueprints[receiver]
        metadata["blueprint_variable"] = receiver
    return python_web_profile_observation(
        "python.flask_route",
        relative_path,
        module,
        function_node,
        name=function_node.name,
        metadata=metadata,
        target=python_function_key(module, function_node.name),
        confidence="heuristic" if route_metadata["dynamic"] else "extracted",
    )


def _fastapi_route_from_decorator(
    relative_path: str,
    module: str,
    call: ast.Call,
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    fastapi_apps: set[str],
    fastapi_routers: set[str],
    aliases: Mapping[str, str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if receiver not in fastapi_apps and receiver not in fastapi_routers:
        return None
    if attr == "api_route":
        methods = _methods_from_keyword(call, default=("GET",))
    elif attr in FASTAPI_METHOD_DECORATORS:
        methods = (FASTAPI_METHOD_DECORATORS[attr],)
    else:
        return None
    route_metadata = _route_path_metadata(_call_arg(call, 0))
    metadata = {
        "framework": "fastapi",
        "handler_name": function_node.name,
        "decorator_name": f"{receiver}.{attr}",
        "receiver_name": receiver,
        "http_methods": list(methods),
        "dependency_count": len(_fastapi_dependencies(function_node, aliases)),
        "dynamic": route_metadata["dynamic"],
        **route_metadata,
    }
    response_model = _keyword(call, "response_model")
    if response_model is not None:
        metadata["response_model"] = _bounded_metadata_string(
            _safe_reference_name(response_model)
        )
    tags = _keyword(call, "tags")
    tag_values = _literal_string_list(tags)
    if tag_values is not None:
        metadata["tag_count"] = len(tag_values)
    for text_key in ("summary", "description"):
        text_node = _keyword(call, text_key)
        text_value = _literal_string(text_node)
        if text_value is not None:
            metadata[f"{text_key}_present"] = True
            metadata[f"{text_key}_length"] = len(text_value)
            metadata[f"{text_key}_sha256"] = _sha256_text(text_value)
    status_code = _keyword(call, "status_code")
    if isinstance(status_code, ast.Constant) and isinstance(status_code.value, int):
        metadata["status_code"] = status_code.value
    return python_web_profile_observation(
        "python.fastapi_route",
        relative_path,
        module,
        function_node,
        name=function_node.name,
        metadata=metadata,
        target=python_function_key(module, function_node.name),
        confidence="heuristic" if route_metadata["dynamic"] else "extracted",
    )


def _flask_add_url_rule_observation(
    relative_path: str,
    module: str,
    call: ast.Call,
    *,
    flask_apps: set[str],
    flask_blueprints: Mapping[str, str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if attr != "add_url_rule":
        return None
    if receiver not in flask_apps and receiver not in flask_blueprints:
        return None
    handler_node = _call_arg(call, 2) or _keyword(call, "view_func")
    handler_name = _safe_reference_name(handler_node) if handler_node else "unknown"
    route_metadata = _route_path_metadata(_call_arg(call, 0))
    methods = _methods_from_keyword(call, default=("GET",))
    metadata = {
        "framework": "flask",
        "handler_name": handler_name,
        "decorator_name": f"{receiver}.add_url_rule",
        "receiver_name": receiver,
        "http_methods": list(methods),
        "dynamic": route_metadata["dynamic"],
        **route_metadata,
    }
    if receiver in flask_blueprints:
        metadata["blueprint_name"] = flask_blueprints[receiver]
        metadata["blueprint_variable"] = receiver
    return python_web_profile_observation(
        "python.flask_route",
        relative_path,
        module,
        call,
        name=handler_name,
        metadata=metadata,
        target=python_function_key(module, handler_name),
        confidence="heuristic" if route_metadata["dynamic"] else "extracted",
    )


def _fastapi_include_router_reference(
    relative_path: str,
    module: str,
    call: ast.Call,
    *,
    fastapi_apps: set[str],
    fastapi_routers: set[str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if attr != "include_router":
        return None
    if receiver not in fastapi_apps and receiver not in fastapi_routers:
        return None
    target_node = _call_arg(call, 0)
    target_name = _safe_reference_name(target_node) if target_node else "unknown"
    return python_web_reference_observation(
        relative_path,
        module,
        call,
        name=target_name,
        target=external_key("python.fastapi_router", target_name),
        framework="fastapi",
        reference_kind="fastapi_include_router",
        metadata={"receiver_name": receiver, "router_name": target_name},
    )


def _django_urlpattern_observations(
    relative_path: str,
    module: str,
    node: ast.Assign | ast.AnnAssign,
) -> tuple[RawObservation, ...]:
    value = _assignment_value(node)
    if not isinstance(value, (ast.List, ast.Tuple)):
        return ()
    observations: list[RawObservation] = []
    for item in value.elts:
        if not isinstance(item, ast.Call):
            continue
        call_name = _ast_name(item.func).split(".")[-1]
        if call_name not in ("path", "re_path"):
            continue
        view_node = _call_arg(item, 1)
        include_target = None
        urlpattern_kind = call_name
        if isinstance(view_node, ast.Call) and _ast_name(view_node.func).split(".")[-1] == "include":
            urlpattern_kind = "include"
            include_target = _literal_string(_call_arg(view_node, 0))
        route_metadata = _route_path_metadata(
            _call_arg(item, 0),
            regex=call_name == "re_path",
        )
        view_name = _safe_reference_name(view_node) if view_node is not None else "unknown"
        metadata = {
            "framework": "django",
            "urlpattern_kind": urlpattern_kind,
            "view_name": _bounded_metadata_string(view_name),
            "dynamic": route_metadata["dynamic"],
            **route_metadata,
        }
        if include_target is not None:
            metadata["include_target"] = _bounded_metadata_string(include_target)
        observations.append(
            python_web_profile_observation(
                "python.django_urlpattern",
                relative_path,
                module,
                item,
                name=view_name,
                metadata=metadata,
                confidence="heuristic" if route_metadata["dynamic"] else "extracted",
            )
        )
        if view_node is not None and urlpattern_kind != "include":
            observations.append(
                python_web_profile_observation(
                    "python.django_view",
                    relative_path,
                    module,
                    view_node,
                    name=view_name,
                    metadata={
                        "framework": "django",
                        "view_name": _bounded_metadata_string(view_name),
                        "urlpattern_kind": urlpattern_kind,
                    },
                    target=external_key("python.view", view_name),
                )
            )
            observations.append(
                python_web_reference_observation(
                    relative_path,
                    module,
                    view_node,
                    name=view_name,
                    target=external_key("python.view", view_name),
                    framework="django",
                    reference_kind="django_urlpattern_view",
                    metadata={"urlpattern_kind": urlpattern_kind},
                )
            )
        if include_target is not None:
            observations.append(
                python_web_reference_observation(
                    relative_path,
                    module,
                    item,
                    name=include_target,
                    target=external_key("python.module", include_target),
                    framework="django",
                    reference_kind="django_include",
                    metadata={"include_target": include_target},
                )
            )
    return tuple(observations)


def _django_model_observation(
    relative_path: str,
    module: str,
    node: ast.ClassDef,
) -> RawObservation | None:
    if not any(_ast_name(base) in ("models.Model", "django.db.models.Model", "Model") for base in node.bases):
        return None
    field_count = 0
    for child in node.body:
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            value = _assignment_value(child)
            if isinstance(value, ast.Call):
                call_name = _ast_name(value.func)
                if call_name.startswith("models.") or call_name.endswith("Field"):
                    field_count += len(_assignment_names(child)) or 1
    return python_web_profile_observation(
        "python.django_model",
        relative_path,
        module,
        node,
        name=node.name,
        target=python_class_key(module, node.name),
        metadata={
            "framework": "django",
            "model_name": node.name,
            "class_name": node.name,
            "model_field_count": field_count,
        },
    )


def _django_app_observation(
    relative_path: str,
    module: str,
    node: ast.ClassDef,
) -> RawObservation | None:
    if not any(_ast_name(base).endswith("AppConfig") for base in node.bases):
        return None
    return python_web_profile_observation(
        "python.django_app",
        relative_path,
        module,
        node,
        name=node.name,
        target=python_class_key(module, node.name),
        metadata={
            "framework": "django",
            "class_name": node.name,
        },
    )


def _django_setting_observations(
    relative_path: str,
    module: str,
    node: ast.Assign | ast.AnnAssign,
) -> tuple[RawObservation, ...]:
    value = _assignment_value(node)
    observations: list[RawObservation] = []
    for name in _assignment_names(node):
        if not name.isupper():
            continue
        sensitive = _is_secret_like_name(name) or _value_looks_credentialed(value)
        observations.append(
            python_web_profile_observation(
                "python.django_setting_reference",
                relative_path,
                module,
                node,
                name=name,
                metadata={
                    "framework": "django",
                    "setting_name": name,
                    "value_kind": _expression_kind(value),
                    "redacted": sensitive,
                },
            )
        )
        if sensitive:
            observations.append(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="django",
                    name=name,
                    redaction_reason="secret-like-django-setting",
                    field_name=name,
                )
            )
    return tuple(observations)


def add_config_redaction_if_needed(
    add: Any,
    relative_path: str,
    module: str,
    node: ast.Assign | ast.AnnAssign,
    target: ast.expr,
    value: ast.expr | None,
    *,
    flask_apps: set[str],
    aliases: Mapping[str, str],
    relative_path_for_settings: str,
) -> None:
    if isinstance(target, ast.Subscript):
        key = _literal_string(target.slice)
        container_name = _ast_name(target.value)
        if (
            key is not None
            and container_name.endswith(".config")
            and container_name.split(".", 1)[0] in flask_apps
            and (_is_secret_like_name(key) or _value_looks_credentialed(value))
        ):
            add(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="flask",
                    name=key,
                    redaction_reason="secret-like-flask-config",
                    field_name=key,
                )
            )
    if _looks_like_django_settings_path(relative_path_for_settings):
        return
    for name in _assignment_names(node):
        if _is_secret_like_name(name) and value is not None:
            add(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="python-web",
                    name=name,
                    redaction_reason="secret-like-assignment",
                    field_name=name,
                )
            )


def _function_default_redactions(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[RawObservation, ...]:
    observations = []
    args = [*node.args.args, *node.args.kwonlyargs]
    defaults = [*node.args.defaults, *node.args.kw_defaults]
    padded_defaults: list[ast.expr | None] = [None] * (len(args) - len(defaults))
    padded_defaults.extend(defaults)
    for argument, default in zip(args, padded_defaults, strict=False):
        if default is None:
            continue
        if _is_secret_like_name(argument.arg) or _value_looks_credentialed(default):
            observations.append(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="python-web",
                    name=argument.arg,
                    redaction_reason="secret-like-default",
                    field_name=argument.arg,
                )
            )
    return tuple(observations)


def _fastapi_dependencies(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: Mapping[str, str],
) -> tuple[dict[str, Any], ...]:
    dependencies: list[dict[str, Any]] = []
    defaults = [*node.args.defaults, *[item for item in node.args.kw_defaults if item]]
    for default in defaults:
        if isinstance(default, ast.Call) and _qualified_ast_name(default.func, aliases) == "fastapi.Depends":
            target_node = _call_arg(default, 0)
            target_name = _safe_reference_name(target_node) if target_node else "unknown"
            dependencies.append(
                {
                    "node": default,
                    "name": target_name,
                    "target": target_name if target_name != "unknown" else None,
                    "kind": "depends_default",
                }
            )
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _qualified_ast_name(child.func, aliases) == "fastapi.Depends":
            if any(item["node"] is child for item in dependencies):
                continue
            target_node = _call_arg(child, 0)
            target_name = _safe_reference_name(target_node) if target_node else "unknown"
            dependencies.append(
                {
                    "node": child,
                    "name": target_name,
                    "target": target_name if target_name != "unknown" else None,
                    "kind": "depends_call",
                }
            )
    return tuple(dependencies)


def _assignment_value(node: ast.Assign | ast.AnnAssign) -> ast.expr | None:
    if isinstance(node, ast.Assign):
        return node.value
    return node.value


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    names = []
    for target in _assignment_target_nodes(node):
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names


def _assignment_target_nodes(node: ast.Assign | ast.AnnAssign) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    return (node.target,)


def _assigns_name(node: ast.Assign | ast.AnnAssign, name: str) -> bool:
    return name in _assignment_names(node)


def _call_receiver_attr(call: ast.Call) -> tuple[str, str]:
    if isinstance(call.func, ast.Attribute):
        return _ast_name(call.func.value), call.func.attr
    return "", ""


def _call_arg(call: ast.Call, index: int) -> ast.expr | None:
    return call.args[index] if len(call.args) > index else None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _methods_from_keyword(call: ast.Call, *, default: tuple[str, ...]) -> tuple[str, ...]:
    methods = _literal_string_list(_keyword(call, "methods"))
    if not methods:
        return default
    normalized = tuple(
        method.upper()
        for method in methods
        if method.upper() in WEB_HTTP_METHODS
    )
    return normalized or default


def _route_path_metadata(
    node: ast.expr | None,
    *,
    regex: bool = False,
) -> dict[str, Any]:
    value = _literal_string(node)
    if value is None:
        return {"route_path_kind": "dynamic", "dynamic": True}
    if _looks_credentialed_url(value):
        return {"route_path_kind": "redacted", "dynamic": False, "redacted": True}
    return {
        "route_path": _bounded_metadata_string(value),
        "route_path_kind": "regex_literal" if regex else "literal",
        "dynamic": False,
    }


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_string_list(node: ast.AST | None) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    values = []
    for item in node.elts:
        value = _literal_string(item)
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _safe_reference_name(node: ast.AST | None) -> str:
    if node is None:
        return "unknown"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _bounded_metadata_string(node.value)
    name = _ast_name(node)
    return _bounded_metadata_string(name or "unknown")


def _expression_kind(node: ast.AST | None) -> str:
    if node is None:
        return "unknown"
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return "literal_string"
        if isinstance(node.value, bool):
            return "literal_bool"
        if isinstance(node.value, (int, float)):
            return "literal_number"
        if node.value is None:
            return "literal_null"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return "collection_shape"
    if isinstance(node, ast.Call):
        return "function_call"
    if isinstance(node, (ast.Name, ast.Attribute)):
        return "traversal_reference"
    if isinstance(node, ast.BinOp):
        return "dynamic_expression"
    return "unknown"


def _is_secret_like_name(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in PYTHON_WEB_SECRET_MARKERS)


def _value_looks_credentialed(node: ast.AST | None) -> bool:
    value = _literal_string(node)
    return bool(value and _looks_credentialed_url(value))


def _looks_credentialed_url(value: str) -> bool:
    return bool(re.search(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]+:[^/@\s]+@", value))


def _looks_like_django_settings_path(relative_path: str) -> bool:
    return PurePath(relative_path.replace("\\", "/")).name == "settings.py"


def _bounded_metadata_string(value: str) -> str:
    if len(value) <= PYTHON_WEB_MAX_METADATA_STRING:
        return value
    return f"{value[:PYTHON_WEB_MAX_METADATA_STRING]}..."


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _line_slug(node: ast.AST) -> str:
    line = getattr(node, "lineno", None)
    return str(line) if isinstance(line, int) else "module"


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
            "decorators": [
                safe_decorator_summary(item) for item in node.decorator_list
            ],
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
            "decorators": [
                safe_decorator_summary(item) for item in node.decorator_list
            ],
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
                            safe_decorator_summary(item)
                            for item in node.decorator_list
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


def safe_decorator_summary(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        call_name = _ast_name(node.func)
        return f"{call_name}(...)" if call_name else "call(...)"
    return safe_unparse(node)


def end_line(node: ast.AST) -> int:
    lineno = getattr(node, "end_lineno", None)
    if isinstance(lineno, int) and lineno > 0:
        return lineno
    return node.lineno


def slug(value: str) -> str:
    return SLUG_PATTERN.sub("-", value).strip("-") or "unknown"
