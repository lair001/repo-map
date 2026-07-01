"""Conservative static JavaScript-family extraction."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from repomap_kg import __version__
from repomap_kg.graph_keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    js_class_key,
    js_component_key,
    js_file_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_test_case_key,
    js_test_suite_key,
    js_variable_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR = "repo-js"
PARSER = "stdlib-js-lexical"
MAX_FILE_BYTES = 512 * 1024
JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
LOCAL_RESOLUTION_EXTENSIONS = (
    "",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".mts",
    ".cts",
    ".tsx",
    ".json",
    ".css",
    ".html",
)
REFERENCE_SCHEMES = frozenset(("http", "https", "mailto"))
ROUTE_METHODS = frozenset(
    ("get", "post", "put", "patch", "delete", "options", "head", "all")
)
JEST_TEST_CALLS = frozenset(("it", "test"))
JEST_HOOK_CALLS = frozenset(("beforeEach", "afterEach", "beforeAll", "afterAll"))
REACT_HOOKS = frozenset(
    ("useState", "useEffect", "useMemo", "useCallback", "useReducer")
)
FRAMEWORK_SPECIFIER_PREFIXES = (
    "express",
    "@nestjs/",
    "next",
    "next/",
    "@jest/",
    "jest",
    "jquery",
)
MAX_FRAMEWORK_OBSERVATIONS_PER_KIND = 100
MAX_SELECTOR_LENGTH = 120
MAX_URL_SUMMARY_LENGTH = 120

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
    "client_secret",
    "secret_key",
    "access_token",
    "id_token",
    "session",
    "cookie",
    "connection_string",
    "jdbc_url",
    "datasource_password",
    "apitoken",
    "authtoken",
    "bearertoken",
    "sessiontoken",
    "csrftoken",
    "xsrftoken",
    "firebaseapikey",
    "sentrydsn",
    "stripesecret",
    "npmtoken",
    "githubtoken",
    "jesttoken",
    "angulartoken",
    "vuetoken",
)

IMPORT_FROM_RE = re.compile(
    r"""^\s*import\s+(?P<body>(?:type\s+)?[\s\S]+?)\s+from\s+(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
SIDE_EFFECT_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
EXPORT_FROM_RE = re.compile(
    r"""^\s*export\s+(?P<body>\*|\{[^}]*\})\s+from\s+(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
EXPORT_DECL_RE = re.compile(
    r"""^\s*export\s+(?:(?P<default>default)\s+)?(?P<kind>function|class|const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)"""
)
DYNAMIC_IMPORT_LITERAL_RE = re.compile(
    r"""\bimport\s*\(\s*(?P<quote>["'])(?P<specifier>.+?)(?P=quote)\s*\)"""
)
REQUIRE_LITERAL_RE = re.compile(
    r"""\brequire\s*\(\s*(?P<quote>["'])(?P<specifier>.+?)(?P=quote)\s*\)"""
)
FETCH_LITERAL_RE = re.compile(
    r"""\b(?P<call>fetch|axios\.get)\s*\(\s*(?P<quote>["'])(?P<url>.+?)(?P=quote)"""
)
IMPORT_SCRIPTS_RE = re.compile(
    r"""\bimportScripts\s*\(\s*(?P<quote>["'])(?P<specifier>.+?)(?P=quote)"""
)
SOURCE_MAP_RE = re.compile(r"""sourceMappingURL=(?P<specifier>\S+)""")
FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\b"""
)
FUNCTION_EXPR_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\b"""
)
ARROW_FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"""
)
CLASS_RE = re.compile(
    r"""^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)(?:\s+extends\s+(?P<superclass>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?))?"""
)
METHOD_RE = re.compile(
    r"""^\s*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{?"""
)
VARIABLE_RE = re.compile(
    r"""^\s*(?:export\s+)?(?P<kind>const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?:=\s*(?P<value>.+?))?;?\s*$"""
)
INTERFACE_RE = re.compile(r"""^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)\b""")
TYPE_RE = re.compile(r"""^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\b""")
ENUM_RE = re.compile(r"""^\s*(?:export\s+)?enum\s+(?P<name>[A-Za-z_$][\w$]*)\b""")
JEST_SUITE_RE = re.compile(
    r"""\bdescribe\s*\(\s*(?P<quote>["'])(?P<name>.+?)(?P=quote)"""
)
JEST_CASE_RE = re.compile(
    r"""\b(?P<call>it|test)\s*\(\s*(?P<quote>["'])(?P<name>.+?)(?P=quote)"""
)
JSX_ROUTE_RE = re.compile(r"""<Route\b[^>]*\bpath=(?P<quote>["'])(?P<path>.+?)(?P=quote)""")
OBJECT_ROUTE_RE = re.compile(r"""\bpath\s*:\s*(?P<quote>["'])(?P<path>.+?)(?P=quote)""")
ANGULAR_TEMPLATE_RE = re.compile(
    r"""\b(?P<kind>templateUrl|styleUrls?)\s*:\s*(?:\[\s*)?(?P<quote>["'])(?P<path>.+?)(?P=quote)"""
)
ENV_RE = re.compile(
    r"""\b(?:process\.env|import\.meta\.env)\.([A-Za-z_$][\w$]*)"""
)
MODULE_EXPORTS_RE = re.compile(r"""\bmodule\.exports\s*=""")
NAMED_EXPORTS_RE = re.compile(r"""\bexports\.(?P<name>[A-Za-z_$][\w$]*)\s*=""")
EXPRESS_APP_RE = re.compile(
    r"""\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*express\s*\("""
)
EXPRESS_ROUTER_RE = re.compile(
    r"""\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*express\.Router\s*\("""
)
EXPRESS_ROUTE_RE = re.compile(
    r"""\b(?P<receiver>[A-Za-z_$][\w$]*)\.(?P<method>get|post|put|patch|delete|options|head|all|use)\s*\((?P<args>.*)"""
)
NEST_DECORATOR_RE = re.compile(
    r"""@(?P<name>Module|Controller|Injectable|Get|Post|Put|Patch|Delete|All|Param|Body|Query|UseGuards|UseInterceptors|UsePipes)\s*(?:\((?P<args>.*)\))?"""
)
NEST_DECORATOR_LINE_RE = re.compile(
    r"""^\s*@(?P<name>Module|Controller|Injectable|Get|Post|Put|Patch|Delete|All|Param|Body|Query|UseGuards|UseInterceptors|UsePipes)\s*(?:\((?P<args>.*)\))?"""
)
NEST_HTTP_DECORATORS = frozenset(("Get", "Post", "Put", "Patch", "Delete", "All"))
NEXT_HTTP_EXPORT_RE = re.compile(
    r"""^\s*export\s+(?:async\s+)?function\s+(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s*\("""
)
JEST_MOCK_RE = re.compile(r"""\bjest\.(?P<kind>mock|fn|spyOn)\s*\(""")
JEST_MATCHER_RE = re.compile(r"""\bexpect\s*\([^)]*\)\s*\.\s*(?P<matcher>[A-Za-z_$][\w$]*)\b""")
JQUERY_SELECTOR_RE = re.compile(
    r"""(?:\$|jQuery)\s*\(\s*(?P<quote>["'])(?P<selector>.*?)(?P=quote)\s*\)"""
)
JQUERY_EVENT_RE = re.compile(
    r"""(?:\$\([^)]*\)|jQuery\([^)]*\))\.(?P<event>on|click|submit|change|ready)\s*\((?P<args>.*)"""
)
JQUERY_AJAX_OBJECT_RE = re.compile(
    r"""\$\.ajax\s*\(\s*\{(?P<body>.*?)\}\s*\)"""
)
JQUERY_AJAX_CALL_RE = re.compile(
    r"""\$\.(?P<method>get|post)\s*\(\s*(?P<quote>["'])(?P<url>.*?)(?P=quote)"""
)
JQUERY_LOAD_RE = re.compile(
    r"""\.load\s*\(\s*(?P<quote>["'])(?P<url>.*?)(?P=quote)"""
)
JQUERY_PLUGIN_RE = re.compile(r"""\$\.fn\.(?P<name>[A-Za-z_$][\w$]*)\s*=""")
STRING_LITERAL_RE = re.compile(r"""(?P<quote>["'])(?P<value>.*?)(?P=quote)""")


def extract_javascript_file_observations(
    relative_path: str,
    content: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    """Extract safe, static JavaScript-family facts from local text."""

    file_bytes = len(content.encode("utf-8", errors="replace"))
    js_format = _detect_format(relative_path)
    profile = _detect_profile(relative_path, content, js_format)
    observations: list[RawObservation] = []
    file_canonical_key = js_file_key(relative_path)
    module_canonical_key = js_module_key(relative_path)
    module_system = _detect_module_system(content)
    next_route = _next_route_metadata(relative_path, js_format)
    framework_counts: dict[str, int] = {}
    framework_overflow_kinds: set[str] = set()

    def add_framework_observation(observation: RawObservation) -> None:
        count = framework_counts.get(observation.kind, 0)
        if count >= MAX_FRAMEWORK_OBSERVATIONS_PER_KIND:
            if observation.kind not in framework_overflow_kinds:
                framework_overflow_kinds.add(observation.kind)
                observations.append(
                    _parse_error(
                        relative_path,
                        js_format,
                        profile,
                        "framework-observation-limit",
                        "framework observation kind exceeded static scanner limit",
                        observation.start_line or 1,
                    )
                )
            return
        framework_counts[observation.kind] = count + 1
        observations.append(observation)

    observations.append(
        _observation(
            kind="js.file",
            relative_path=relative_path,
            source_id=f"{relative_path}#js-file",
            name=relative_path,
            target=file_canonical_key,
            metadata={
                "format": js_format,
                "profile": profile,
                "profiles": [profile],
                "parser": PARSER,
                "file_bytes": file_bytes,
            },
        )
    )
    observations.append(
        _definition_observation(
            "js.module",
            relative_path,
            js_format,
            profile,
            1,
            relative_path,
            module_canonical_key,
            source_key=file_canonical_key,
            metadata={"module_system": module_system},
        )
    )

    if file_bytes > MAX_FILE_BYTES:
        observations.append(
            _parse_error(
                relative_path,
                js_format,
                profile,
                "file-size-limit",
                "JavaScript-family file exceeds static scanner limit",
                1,
            )
        )
        return tuple(observations)

    class_stack: list[tuple[str, str, int]] = []
    nest_controller_prefixes: dict[str, str | None] = {}
    pending_nest_decorators: list[dict[str, Any]] = []
    pending_angular_component = False
    suite_count = 0
    current_suite_key: str | None = None
    case_count_by_owner: dict[str, int] = {}
    route_count = 0

    if _is_node_entrypoint(relative_path, content):
        add_framework_observation(
            _framework_observation(
                "node.entrypoint",
                relative_path,
                js_format,
                profile,
                1,
                PurePosixPath(relative_path).name,
                module_canonical_key,
                metadata={
                    "entrypoint_reason": "entrypoint-path",
                    "module_system": module_system,
                },
            )
        )

    if next_route is not None:
        add_framework_observation(
            _framework_observation(
                next_route["kind"],
                relative_path,
                js_format,
                "next",
                1,
                next_route["route_pattern"],
                module_canonical_key,
                metadata=next_route,
            )
        )

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = _strip_line_comment(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        for dynamic_reason in _dynamic_reasons(stripped):
            observations.append(
                _parse_error(
                    relative_path,
                    js_format,
                    profile,
                    f"dynamic-{dynamic_reason}",
                    "dynamic JavaScript construct kept as diagnostic",
                    line_number,
                    dynamic_reason=dynamic_reason,
                )
            )

        for env_name in ENV_RE.findall(stripped):
            redacted = _is_secret_prone(env_name)
            observations.append(
                _diagnostic_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "env-reference",
                    env_name,
                    redacted=redacted,
                )
            )
            add_framework_observation(
                _framework_observation(
                    "js.framework_reference",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "environment",
                    module_canonical_key,
                    metadata={
                        "reference_kind": "environment",
                        "env_name": None if redacted else env_name,
                        "redacted": redacted,
                        "redaction_reason": "secret-prone-env-name" if redacted else None,
                    },
                )
            )

        if "@Component" in stripped:
            pending_angular_component = True

        import_match = IMPORT_FROM_RE.match(stripped)
        if import_match:
            specifier = import_match.group("specifier")
            import_kind = "type_import" if import_match.group("body").strip().startswith("type ") else "import"
            observations.extend(
                _import_observations(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    import_kind,
                    specifier,
                    module_canonical_key,
                    repository_paths,
                )
            )
            framework_reference = _framework_specifier_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                specifier,
                module_canonical_key,
            )
            if framework_reference is not None:
                add_framework_observation(framework_reference)
        else:
            side_effect_match = SIDE_EFFECT_IMPORT_RE.match(stripped)
            if side_effect_match and not stripped.startswith("import("):
                specifier = side_effect_match.group("specifier")
                observations.extend(
                    _import_observations(
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        "side_effect_import",
                        specifier,
                        module_canonical_key,
                        repository_paths,
                    )
                )
                framework_reference = _framework_specifier_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    specifier,
                    module_canonical_key,
                )
                if framework_reference is not None:
                    add_framework_observation(framework_reference)

        export_from_match = EXPORT_FROM_RE.match(stripped)
        if export_from_match:
            specifier = export_from_match.group("specifier")
            observations.extend(
                _export_observations(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "re_export",
                    specifier,
                    module_canonical_key,
                    repository_paths,
                )
            )
            framework_reference = _framework_specifier_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                specifier,
                module_canonical_key,
            )
            if framework_reference is not None:
                add_framework_observation(framework_reference)
        else:
            export_decl_match = EXPORT_DECL_RE.match(stripped)
            if export_decl_match:
                observations.append(
                    _observation(
                        kind="js.export",
                        relative_path=relative_path,
                        source_id=f"{relative_path}#js-export:{line_number}",
                        start_line=line_number,
                        name=export_decl_match.group("name"),
                        metadata={
                            "format": js_format,
                            "profile": profile,
                            "parser": PARSER,
                            "export_kind": export_decl_match.group("kind"),
                            "exported_name": export_decl_match.group("name"),
                            "source_key": module_canonical_key,
                        },
                    )
                )

        for match in REQUIRE_LITERAL_RE.finditer(stripped):
            specifier = match.group("specifier")
            observations.extend(
                _import_observations(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "require",
                    specifier,
                    module_canonical_key,
                    repository_paths,
                )
            )
            target, reason = _specifier_target(relative_path, specifier, repository_paths)
            add_framework_observation(
                _framework_observation(
                    "node.require",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    specifier,
                    module_canonical_key,
                    target=target,
                    metadata={
                        "specifier": _safe_summary(_sanitize_url(specifier)),
                        "target_key": target,
                        "resolution_reason": reason,
                        "module_system": "commonjs",
                        "not_loaded": True,
                    },
                )
            )
            framework_reference = _framework_specifier_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                specifier,
                module_canonical_key,
            )
            if framework_reference is not None:
                add_framework_observation(framework_reference)

        if MODULE_EXPORTS_RE.search(stripped):
            add_framework_observation(
                _framework_observation(
                    "node.export",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "module.exports",
                    module_canonical_key,
                    metadata={
                        "export_kind": "module.exports",
                        "module_system": "commonjs",
                    },
                )
            )
        for match in NAMED_EXPORTS_RE.finditer(stripped):
            add_framework_observation(
                _framework_observation(
                    "node.export",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    match.group("name"),
                    module_canonical_key,
                    metadata={
                        "export_kind": "exports.name",
                        "exported_name": match.group("name"),
                        "module_system": "commonjs",
                    },
                )
            )

        for match in DYNAMIC_IMPORT_LITERAL_RE.finditer(stripped):
            specifier = match.group("specifier")
            observations.extend(
                _import_observations(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "dynamic_import",
                    specifier,
                    module_canonical_key,
                    repository_paths,
                    dynamic=True,
                )
            )

        observations.extend(
            _literal_reference_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                stripped,
                module_canonical_key,
                repository_paths,
            )
        )

        for framework_observation in _jquery_observations(
            relative_path,
            js_format,
            profile,
            line_number,
            stripped,
            module_canonical_key,
            repository_paths,
        ):
            if framework_observation.kind == "js.parse_error":
                observations.append(framework_observation)
            else:
                add_framework_observation(framework_observation)

        express_app_match = EXPRESS_APP_RE.search(stripped)
        if express_app_match:
            add_framework_observation(
                _framework_observation(
                    "express.app",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    express_app_match.group("name"),
                    module_canonical_key,
                    metadata={"app_name": express_app_match.group("name")},
                )
            )
        express_router_match = EXPRESS_ROUTER_RE.search(stripped)
        if express_router_match:
            add_framework_observation(
                _framework_observation(
                    "express.router",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    express_router_match.group("name"),
                    module_canonical_key,
                    metadata={"router_name": express_router_match.group("name")},
                )
            )

        express_route = _express_route_metadata(stripped)
        if express_route is not None:
            add_framework_observation(
                _framework_observation(
                    "express.route",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    express_route["route_name"],
                    module_canonical_key,
                    metadata=express_route,
                )
            )
            if express_route["route_method"] == "USE":
                add_framework_observation(
                    _framework_observation(
                        "express.middleware",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        express_route["route_name"],
                        module_canonical_key,
                        metadata=express_route,
                    )
                )
            if express_route.get("error_handler"):
                add_framework_observation(
                    _framework_observation(
                        "express.error_handler",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        express_route["route_name"],
                        module_canonical_key,
                        metadata=express_route,
                    )
                )
            if not express_route["dynamic"] and express_route.get("route_pattern"):
                route_count += 1
                pointer = (
                    f"/routes/{express_route['route_method'].lower()}:"
                    f"{express_route['route_pattern']}"
                )
                observations.append(
                    _definition_observation(
                        "js.route",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        f"{express_route['route_method']} {express_route['route_pattern']}",
                        js_route_key(relative_path, pointer),
                        source_key=module_canonical_key,
                        metadata={
                            "route_method": express_route["route_method"],
                            "route_pattern": express_route["route_pattern"],
                            "route_pointer": pointer,
                            "identity_strength": "structural",
                            "route_ordinal": route_count,
                        },
                    )
                )

        for decorator_match in NEST_DECORATOR_RE.finditer(stripped):
            add_framework_observation(
                _framework_observation(
                    "nest.decorator",
                    relative_path,
                    js_format,
                    "nestjs",
                    line_number,
                    decorator_match.group("name"),
                    module_canonical_key,
                    metadata={
                        "decorator_name": decorator_match.group("name"),
                        "decorator_args_summary": _safe_summary(
                            decorator_match.group("args")
                        ),
                    },
                )
            )
        nest_line_decorator = NEST_DECORATOR_LINE_RE.match(stripped)
        if nest_line_decorator:
            pending_nest_decorators.append(
                {
                    "name": nest_line_decorator.group("name"),
                    "args": nest_line_decorator.group("args") or "",
                    "line_number": line_number,
                }
            )

        if next_route is not None and next_route["route_file_kind"] == "route":
            next_export_match = NEXT_HTTP_EXPORT_RE.match(stripped)
            if next_export_match:
                http_method = next_export_match.group("method")
                add_framework_observation(
                    _framework_observation(
                        "next.route",
                        relative_path,
                        js_format,
                        "next",
                        line_number,
                        f"{http_method} {next_route['route_pattern']}",
                        module_canonical_key,
                        metadata={
                            **next_route,
                            "http_method": http_method,
                            "route_method": http_method,
                        },
                    )
                )
                route_count += 1
                pointer = f"/routes/{http_method.lower()}:{next_route['route_pattern']}"
                observations.append(
                    _definition_observation(
                        "js.route",
                        relative_path,
                        js_format,
                        "next",
                        line_number,
                        f"{http_method} {next_route['route_pattern']}",
                        js_route_key(relative_path, pointer),
                        source_key=module_canonical_key,
                        metadata={
                            "route_method": http_method,
                            "route_pattern": next_route["route_pattern"],
                            "route_pointer": pointer,
                            "identity_strength": "structural",
                            "route_ordinal": route_count,
                        },
                    )
                )

        class_match = CLASS_RE.match(stripped)
        if class_match:
            class_name = class_match.group("name")
            class_key = js_class_key(relative_path, class_name)
            superclass = class_match.group("superclass")
            observations.append(
                _definition_observation(
                    "js.class",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    class_name,
                    class_key,
                    source_key=module_canonical_key,
                    metadata={
                        "class_name": class_name,
                        "qualified_name": class_name,
                        "superclass": superclass,
                    },
                )
            )
            if pending_angular_component or _is_react_class(superclass):
                observations.append(
                    _component_observation(
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        class_name,
                        module_canonical_key,
                    )
                )
            nest_metadata = _nest_class_metadata(class_name, pending_nest_decorators)
            if nest_metadata is not None:
                nest_kind = nest_metadata.pop("kind")
                add_framework_observation(
                    _framework_observation(
                        nest_kind,
                        relative_path,
                        js_format,
                        "nestjs",
                        line_number,
                        class_name,
                        module_canonical_key,
                        metadata=nest_metadata,
                    )
                )
                if nest_kind == "nest.controller":
                    nest_controller_prefixes[class_name] = nest_metadata.get(
                        "controller_prefix"
                    )
            pending_nest_decorators.clear()
            class_depth = _brace_delta(stripped)
            if class_depth > 0:
                class_stack.append((class_name, class_key, class_depth))
            pending_angular_component = False
            continue

        current_class = class_stack[-1] if class_stack else None
        if current_class:
            method_match = METHOD_RE.match(stripped)
            if method_match and not _looks_like_non_method(stripped):
                method_name = method_match.group("name")
                method_key = js_method_key(current_class[1], method_name)
                observations.append(
                    _definition_observation(
                        "js.method",
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        method_name,
                        method_key,
                        source_key=current_class[1],
                        metadata={
                            "class_name": current_class[0],
                            "method_name": method_name,
                            "qualified_name": f"{current_class[0]}.{method_name}",
                        },
                    )
                )
                nest_route = _nest_route_metadata(
                    current_class[0],
                    method_name,
                    nest_controller_prefixes.get(current_class[0]),
                    pending_nest_decorators,
                )
                if nest_route is not None:
                    add_framework_observation(
                        _framework_observation(
                            "nest.route",
                            relative_path,
                            js_format,
                            "nestjs",
                            line_number,
                            f"{nest_route['route_method']} {nest_route['route_pattern']}",
                            module_canonical_key,
                            metadata=nest_route,
                        )
                    )
                    if not nest_route["dynamic"] and nest_route.get("route_pattern"):
                        route_count += 1
                        pointer = (
                            f"/routes/{nest_route['route_method'].lower()}:"
                            f"{nest_route['controller_prefix']}/"
                            f"{nest_route['route_pattern']}"
                        )
                        observations.append(
                            _definition_observation(
                                "js.route",
                                relative_path,
                                js_format,
                                "nestjs",
                                line_number,
                                f"{nest_route['route_method']} {nest_route['route_pattern']}",
                                js_route_key(relative_path, pointer),
                                source_key=module_canonical_key,
                                metadata={
                                    "route_method": nest_route["route_method"],
                                    "route_pattern": nest_route["route_pattern"],
                                    "route_pointer": pointer,
                                    "identity_strength": "structural",
                                    "route_ordinal": route_count,
                                },
                            )
                        )
                pending_nest_decorators.clear()

        observations.extend(
            _function_and_variable_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                stripped,
                module_canonical_key,
            )
        )
        observations.extend(
            _typescript_observations(
                relative_path,
                js_format,
                profile,
                line_number,
                stripped,
                module_canonical_key,
            )
        )

        suite_match = JEST_SUITE_RE.search(stripped)
        if suite_match and _is_jest_profile(profile, relative_path, content):
            suite_count += 1
            pointer = f"/tests/describe[{suite_count}]"
            suite_key = js_test_suite_key(relative_path, pointer)
            current_suite_key = suite_key
            observations.append(
                _definition_observation(
                    "js.test_suite",
                    relative_path,
                    js_format,
                    "jest",
                    line_number,
                    f"describe[{suite_count}]",
                    suite_key,
                    source_key=module_canonical_key,
                    metadata={
                        "test_framework": "jest",
                        "test_name_summary": _safe_summary(suite_match.group("name")),
                        "identity_strength": "structural",
                    },
                )
            )
            add_framework_observation(
                _framework_observation(
                    "jest.suite",
                    relative_path,
                    js_format,
                    "jest",
                    line_number,
                    f"describe[{suite_count}]",
                    module_canonical_key,
                    metadata={
                        "test_framework": "jest",
                        "test_name_summary": _safe_summary(suite_match.group("name")),
                        "suite_key": suite_key,
                    },
                )
            )

        case_match = JEST_CASE_RE.search(stripped)
        if case_match and _is_jest_profile(profile, relative_path, content):
            owner_key = current_suite_key or file_canonical_key
            count = case_count_by_owner.get(owner_key, 0) + 1
            case_count_by_owner[owner_key] = count
            pointer = f"/tests/{case_match.group('call')}[{count}]"
            test_key = js_test_case_key(owner_key, pointer)
            observations.append(
                _definition_observation(
                    "js.test_case",
                    relative_path,
                    js_format,
                    "jest",
                    line_number,
                    f"{case_match.group('call')}[{count}]",
                    test_key,
                    source_key=owner_key,
                    metadata={
                        "test_framework": "jest",
                        "test_name_summary": _safe_summary(case_match.group("name")),
                        "identity_strength": "structural",
                    },
                )
            )
            add_framework_observation(
                _framework_observation(
                    "jest.test",
                    relative_path,
                    js_format,
                    "jest",
                    line_number,
                    f"{case_match.group('call')}[{count}]",
                    module_canonical_key,
                    metadata={
                        "test_framework": "jest",
                        "test_call": case_match.group("call"),
                        "test_name_summary": _safe_summary(case_match.group("name")),
                        "suite_key": owner_key,
                        "test_key": test_key,
                    },
                )
            )
        if "expect(" in stripped and _is_jest_profile(profile, relative_path, content):
            matchers = tuple(
                dict.fromkeys(match.group("matcher") for match in JEST_MATCHER_RE.finditer(stripped))
            )
            observations.append(
                _observation(
                    kind="js.test_expectation",
                    relative_path=relative_path,
                    source_id=f"{relative_path}#js-expectation:{line_number}",
                    start_line=line_number,
                    name="expect",
                    metadata={
                        "format": js_format,
                        "profile": "jest",
                        "parser": PARSER,
                        "test_framework": "jest",
                        "expectation_count": stripped.count("expect("),
                        "source_key": current_suite_key or module_canonical_key,
                    },
                )
            )
            add_framework_observation(
                _framework_observation(
                    "jest.expectation",
                    relative_path,
                    js_format,
                    "jest",
                    line_number,
                    "expect",
                    module_canonical_key,
                    metadata={
                        "test_framework": "jest",
                        "expectation_count": stripped.count("expect("),
                        "matchers": list(matchers),
                        "source_key": current_suite_key or module_canonical_key,
                    },
                )
            )
        if _is_jest_profile(profile, relative_path, content):
            for mock_match in JEST_MOCK_RE.finditer(stripped):
                add_framework_observation(
                    _framework_observation(
                        "jest.mock",
                        relative_path,
                        js_format,
                        "jest",
                        line_number,
                        mock_match.group("kind"),
                        module_canonical_key,
                        metadata={
                            "test_framework": "jest",
                            "mock_kind": mock_match.group("kind"),
                        },
                    )
                )

        for hook in REACT_HOOKS:
            if re.search(rf"\b{hook}\s*\(", stripped):
                observations.append(
                    _hook_observation(
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        hook,
                        module_canonical_key,
                    )
                )
        custom_hook = re.search(r"\b(use[A-Z]\w*)\s*\(", stripped)
        if custom_hook and custom_hook.group(1) not in REACT_HOOKS:
            observations.append(
                _hook_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    custom_hook.group(1),
                    module_canonical_key,
                )
            )

        for route_pattern in _route_patterns(stripped, profile):
            route_count += 1
            pointer = f"/routes/path:{route_pattern}"
            route_key = js_route_key(relative_path, pointer)
            observations.append(
                _definition_observation(
                    "js.route",
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    f"path {route_pattern}",
                    route_key,
                    source_key=module_canonical_key,
                    metadata={
                        "route_method": "path",
                        "route_pattern": route_pattern,
                        "route_pointer": pointer,
                        "identity_strength": "structural",
                        "route_ordinal": route_count,
                    },
                )
            )

        _update_class_stack(class_stack, stripped)

    return tuple(observations)


def _detect_format(relative_path: str) -> str:
    suffix = PurePosixPath(relative_path).suffix.lower()
    if suffix in (".ts", ".mts", ".cts"):
        return "typescript"
    if suffix == ".jsx":
        return "jsx"
    if suffix == ".tsx":
        return "tsx"
    return "javascript"


def _detect_profile(relative_path: str, content: str, js_format: str) -> str:
    path = PurePosixPath(relative_path)
    lower_path = relative_path.lower()
    lower_content = content.lower()
    if _next_route_metadata(relative_path, js_format) is not None or re.search(
        r"""from\s+["']next(?:/[^"']*)?["']""", content
    ):
        return "next"
    if (
        "__tests__" in path.parts
        or ".test." in path.name
        or ".spec." in path.name
        or "@jest/globals" in content
        or re.search(r"\bdescribe\s*\(", content)
    ):
        return "jest"
    if "@nestjs/" in content or NEST_DECORATOR_RE.search(content):
        return "nestjs"
    if _has_jquery_marker(content):
        return "jquery"
    if _is_node_entrypoint(relative_path, content):
        return "node"
    if _has_express_marker(content):
        return "express"
    if "report" in lower_path or "coverage" in path.parts:
        return "test_report_asset"
    if ".repomap/source-artifacts/" in lower_path or "_files/" in lower_path:
        return "saved_page_asset"
    if "@angular/" in content or "@Component" in content or "Routes" in content:
        return "angular"
    if "from 'react'" in content or 'from "react"' in content or js_format in ("jsx", "tsx"):
        return "react"
    if "from 'vue'" in content or 'from "vue"' in content or "defineComponent" in content:
        return "vue"
    if path.name.endswith((".config.js", ".config.ts", ".config.cjs", ".config.mjs")):
        return "node_config"
    if lower_path.startswith("public/") or "/public/" in lower_path:
        return "frontend_asset"
    if js_format == "typescript":
        return "generic_typescript"
    return "generic_javascript"


def _detect_module_system(content: str) -> str:
    has_esm = bool(re.search(r"^\s*(?:import|export)\b", content, re.MULTILINE))
    has_commonjs = "require(" in content or "module.exports" in content or "exports." in content
    if has_esm and has_commonjs:
        return "mixed"
    if has_esm:
        return "esm"
    if has_commonjs:
        return "commonjs"
    return "script"


def _framework_observation(
    kind: str,
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    name: str,
    source_key: str,
    *,
    metadata: dict[str, Any],
    target: str | None = None,
) -> RawObservation:
    payload = {
        "format": js_format,
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "source_key": source_key,
        "raw_profile_observation": True,
    }
    payload.update(metadata)
    return _observation(
        kind=kind,
        relative_path=relative_path,
        source_id=(
            f"{relative_path}#{kind}:{line_number}:"
            f"{_source_id_fragment(name)}"
        ),
        start_line=line_number,
        name=_safe_summary(name),
        target=target,
        metadata=payload,
    )


def _framework_specifier_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    specifier: str,
    source_key: str,
) -> RawObservation | None:
    if not _is_framework_specifier(specifier):
        return None
    return _framework_observation(
        "js.framework_reference",
        relative_path,
        js_format,
        profile,
        line_number,
        specifier,
        source_key,
        metadata={
            "reference_kind": "framework-package",
            "specifier": _safe_summary(_sanitize_url(specifier)),
            "package_name": _package_name(specifier),
            "not_loaded": True,
            "not_fetched": True,
        },
    )


def _is_framework_specifier(specifier: str) -> bool:
    return specifier == "express" or specifier == "jquery" or any(
        specifier.startswith(prefix) for prefix in FRAMEWORK_SPECIFIER_PREFIXES
    )


def _has_express_marker(content: str) -> bool:
    return bool(
        re.search(r"""require\s*\(\s*["']express["']\s*\)""", content)
        or re.search(r"""from\s+["']express["']""", content)
        or "express()" in content
        or "express.Router" in content
    )


def _has_jquery_marker(content: str) -> bool:
    return bool(
        "jQuery(" in content
        or "$.ajax" in content
        or "$.get" in content
        or "$.post" in content
        or "$.fn." in content
        or re.search(r"""\$\([^)]*["'][^"']+["'][^)]*\)\.(?:on|click|submit|change|ready)""", content)
    )


def _is_node_entrypoint(relative_path: str, content: str) -> bool:
    path = PurePosixPath(relative_path)
    stem = path.stem.lower()
    if stem not in ("server", "app", "index", "main"):
        return False
    if path.suffix.lower() not in JS_EXTENSIONS:
        return False
    return bool(
        re.search(r"""require\s*\(\s*["']node:""", content)
        or re.search(r"""from\s+["']node:""", content)
        or "process.env." in content
        or "import.meta.env." in content
        or "module.exports" in content
        or "exports." in content
    )


def _next_route_metadata(relative_path: str, js_format: str) -> dict[str, Any] | None:
    path = PurePosixPath(relative_path)
    suffix = path.suffix.lower()
    if suffix not in JS_EXTENSIONS:
        return None
    parts = path.parts
    if not parts:
        return None
    if parts[0] == "pages" and len(parts) >= 2:
        route_parts = list(parts[1:])
        route_parts[-1] = _strip_js_suffix(route_parts[-1])
        route_pattern = _route_pattern_from_segments(route_parts)
        if len(route_parts) >= 2 and route_parts[0] == "api":
            return {
                "kind": "next.api_route",
                "framework": "next",
                "route_file_kind": "api",
                "route_pattern": route_pattern,
                "router": "pages",
            }
        if route_parts[-1].startswith("_"):
            return None
        return {
            "kind": "next.page",
            "framework": "next",
            "route_file_kind": "page",
            "route_pattern": route_pattern,
            "router": "pages",
        }
    if parts[0] == "app" and len(parts) >= 2:
        filename = _strip_js_suffix(parts[-1])
        if filename not in ("page", "layout", "route", "loading", "error"):
            return None
        route_parts = list(parts[1:-1])
        route_pattern = _route_pattern_from_segments(route_parts)
        if filename == "route":
            kind = "next.app_route"
        elif filename == "page":
            kind = "next.page"
        else:
            kind = "next.component"
        return {
            "kind": kind,
            "framework": "next",
            "route_file_kind": filename,
            "route_pattern": route_pattern,
            "router": "app",
        }
    return None


def _strip_js_suffix(name: str) -> str:
    for suffix in sorted(JS_EXTENSIONS, key=len, reverse=True):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _route_pattern_from_segments(segments: list[str]) -> str:
    clean_segments = [segment for segment in segments if segment and segment != "index"]
    if not clean_segments:
        return "/"
    return "/" + "/".join(clean_segments)


def _express_route_metadata(line: str) -> dict[str, Any] | None:
    match = EXPRESS_ROUTE_RE.search(line)
    if not match:
        return None
    receiver = match.group("receiver")
    method = match.group("method").upper()
    args = _split_js_args(match.group("args"))
    route_pattern: str | None = None
    handler_args = args
    if args:
        first_literal = _whole_string_literal(args[0])
        if first_literal is not None:
            route_pattern = first_literal
            handler_args = args[1:]
    dynamic = route_pattern is None
    identifiers = [_simple_identifier(arg) for arg in handler_args]
    identifiers = [identifier for identifier in identifiers if identifier is not None]
    handler_name = identifiers[-1] if identifiers else None
    middleware_count = max(0, len(identifiers) - (1 if handler_name else 0))
    error_handler = method == "USE" and any(
        _looks_like_express_error_handler(arg) for arg in handler_args
    )
    route_name = f"{method} {route_pattern or '<dynamic>'}"
    return {
        "receiver_name": receiver,
        "route_method": method,
        "route_pattern": route_pattern,
        "route_name": route_name,
        "handler_name": handler_name,
        "middleware_count": middleware_count,
        "dynamic": dynamic,
        "dynamic_reason": "dynamic-route-path" if dynamic else None,
        "error_handler": error_handler,
        "framework": "express",
    }


def _split_js_args(raw_args: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for char in raw_args:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
            current.append(char)
            continue
        if char in "([{":
            depth += 1
            current.append(char)
            continue
        if char in ")]}":
            if depth <= 0:
                break
            depth -= 1
            current.append(char)
            continue
        if char == "," and depth == 0:
            value = "".join(current).strip()
            if value:
                args.append(value)
            current = []
            continue
        current.append(char)
    value = "".join(current).strip().rstrip(";")
    if value:
        args.append(value)
    return args


def _whole_string_literal(value: str) -> str | None:
    stripped = value.strip()
    if len(stripped) < 2 or stripped[0] not in ("'", '"') or stripped[-1] != stripped[0]:
        return None
    return stripped[1:-1]


def _first_string_literal(value: str | None) -> str | None:
    if not value:
        return None
    match = STRING_LITERAL_RE.search(value)
    if not match:
        return None
    return match.group("value")


def _simple_identifier(value: str) -> str | None:
    stripped = value.strip()
    if re.fullmatch(r"[A-Za-z_$][\w$]*", stripped):
        return stripped
    return None


def _looks_like_express_error_handler(value: str) -> bool:
    compact = re.sub(r"\s+", " ", value.strip())
    return bool(
        re.search(r"\(\s*err\s*,\s*req\s*,\s*res\s*,\s*next\s*\)", compact)
        or re.search(r"function\s*\(\s*err\s*,\s*req\s*,\s*res\s*,\s*next\s*\)", compact)
    )


def _nest_class_metadata(
    class_name: str, decorators: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for decorator in decorators:
        name = decorator["name"]
        args = decorator.get("args", "")
        if name == "Module":
            return {
                "kind": "nest.module",
                "module_name": class_name,
                "imports": _extract_nest_array_names(args, "imports"),
                "controllers": _extract_nest_array_names(args, "controllers"),
                "providers": _extract_nest_array_names(args, "providers"),
            }
        if name == "Controller":
            return {
                "kind": "nest.controller",
                "controller_name": class_name,
                "controller_prefix": _first_string_literal(args),
                "dynamic": _first_string_literal(args) is None and bool(args.strip()),
            }
        if name == "Injectable":
            return {"kind": "nest.provider", "provider_name": class_name}
    return None


def _extract_nest_array_names(args: str, key: str) -> list[str]:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*\[(?P<body>[^\]]*)\]", args)
    if not match:
        return []
    names: list[str] = []
    for part in match.group("body").split(","):
        name = part.strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
            names.append(name)
    return names


def _nest_route_metadata(
    controller_name: str,
    method_name: str,
    controller_prefix: str | None,
    decorators: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for decorator in decorators:
        name = decorator["name"]
        if name not in NEST_HTTP_DECORATORS:
            continue
        route_pattern = _first_string_literal(decorator.get("args", "")) or ""
        return {
            "controller_name": controller_name,
            "method_name": method_name,
            "controller_prefix": controller_prefix,
            "route_method": name.upper() if name != "All" else "ALL",
            "route_pattern": route_pattern,
            "dynamic": route_pattern == "" and bool(decorator.get("args", "").strip()),
            "framework": "nestjs",
        }
    return None


def _jquery_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for match in JQUERY_SELECTOR_RE.finditer(line):
        selector = match.group("selector")
        if len(selector) > MAX_SELECTOR_LENGTH or _is_secret_prone(selector):
            observations.append(
                _parse_error(
                    relative_path,
                    js_format,
                    profile,
                    "framework-selector-limit",
                    "jQuery selector exceeded static scanner limit or redaction policy",
                    line_number,
                )
            )
            continue
        metadata = {"selector": selector, "selector_length": len(selector)}
        observations.append(
            _framework_observation(
                "jquery.selector",
                relative_path,
                js_format,
                "jquery",
                line_number,
                selector,
                source_key,
                metadata=metadata,
            )
        )
        observations.append(
            _framework_observation(
                "js.dom_selector",
                relative_path,
                js_format,
                "jquery",
                line_number,
                selector,
                source_key,
                metadata={**metadata, "framework": "jquery"},
            )
        )
    for match in JQUERY_EVENT_RE.finditer(line):
        event_method = match.group("event")
        event_name = _first_string_literal(match.group("args")) if event_method == "on" else event_method
        if not event_name:
            event_name = event_method
        metadata = {"event_name": event_name, "event_method": event_method}
        observations.append(
            _framework_observation(
                "jquery.event",
                relative_path,
                js_format,
                "jquery",
                line_number,
                event_name,
                source_key,
                metadata=metadata,
            )
        )
        observations.append(
            _framework_observation(
                "js.dom_event",
                relative_path,
                js_format,
                "jquery",
                line_number,
                event_name,
                source_key,
                metadata={**metadata, "framework": "jquery"},
            )
        )
    for ajax_method, raw_url in _jquery_ajax_calls(line):
        target, reason = _specifier_target(relative_path, raw_url, repository_paths)
        sanitized_url = _sanitize_url(raw_url)
        url_summary = _safe_summary(sanitized_url, max_length=MAX_URL_SUMMARY_LENGTH)
        metadata = {
            "ajax_method": ajax_method,
            "url_summary": url_summary,
            "target_key": target,
            "resolution_reason": reason,
            "not_fetched": True,
        }
        observations.append(
            _framework_observation(
                "jquery.ajax",
                relative_path,
                js_format,
                "jquery",
                line_number,
                ajax_method,
                source_key,
                target=target,
                metadata=metadata,
            )
        )
        observations.append(
            _framework_observation(
                "js.ajax_reference",
                relative_path,
                js_format,
                "jquery",
                line_number,
                ajax_method,
                source_key,
                target=target,
                metadata={**metadata, "framework": "jquery"},
            )
        )
    for match in JQUERY_PLUGIN_RE.finditer(line):
        plugin_name = match.group("name")
        observations.append(
            _framework_observation(
                "jquery.plugin_reference",
                relative_path,
                js_format,
                "jquery",
                line_number,
                plugin_name,
                source_key,
                metadata={"plugin_name": plugin_name, "not_executed": True},
            )
        )
    return tuple(observations)


def _jquery_ajax_calls(line: str) -> tuple[tuple[str, str], ...]:
    calls: list[tuple[str, str]] = []
    for match in JQUERY_AJAX_OBJECT_RE.finditer(line):
        url = _object_literal_string_value(match.group("body"), "url")
        if url is not None:
            calls.append(("ajax", url))
    for match in JQUERY_AJAX_CALL_RE.finditer(line):
        calls.append((match.group("method"), match.group("url")))
    for match in JQUERY_LOAD_RE.finditer(line):
        calls.append(("load", match.group("url")))
    return tuple(calls)


def _object_literal_string_value(body: str, key: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(key)}\s*:\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
        body,
    )
    if not match:
        return None
    return match.group("value")


def _source_id_fragment(value: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value)
    return fragment[:80] or "item"


def _observation(
    *,
    kind: str,
    relative_path: str,
    source_id: str,
    metadata: dict[str, Any],
    confidence: str = "extracted",
    start_line: int | None = None,
    name: str | None = None,
    target: str | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=relative_path,
        confidence=confidence,
        extractor=EXTRACTOR,
        extractor_version=__version__,
        start_line=start_line,
        end_line=start_line,
        name=name,
        target=target,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _definition_observation(
    kind: str,
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    name: str,
    target: str,
    *,
    source_key: str,
    metadata: dict[str, Any],
) -> RawObservation:
    payload = {
        "format": js_format,
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "source_key": source_key,
        "identity_strength": "symbolic",
    }
    payload.update(metadata)
    return _observation(
        kind=kind,
        relative_path=relative_path,
        source_id=f"{relative_path}#{kind}:{name}:{line_number}",
        start_line=line_number,
        name=name,
        target=target,
        metadata=payload,
    )


def _reference_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    reference_kind: str,
    raw_value: str,
    target: str,
    source_key: str,
    *,
    resolution_reason: str,
    dynamic: bool = False,
    extra_metadata: dict[str, Any] | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": js_format,
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "reference_kind": reference_kind,
        "raw_value_summary": _safe_summary(_sanitize_url(raw_value)),
        "source_key": source_key,
        "target_key": target,
        "resolution_reason": resolution_reason,
        "not_fetched": True,
        "dynamic": dynamic,
        "dynamic_reason": "dynamic-import" if dynamic else None,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _observation(
        kind="js.reference",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-reference:{reference_kind}:{line_number}:{len(raw_value)}",
        start_line=line_number,
        name=reference_kind,
        target=target,
        metadata=metadata,
    )


def _import_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    import_kind: str,
    specifier: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
    *,
    dynamic: bool = False,
) -> tuple[RawObservation, ...]:
    target, reason = _specifier_target(relative_path, specifier, repository_paths)
    import_observation = _observation(
        kind="js.import",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-import:{line_number}:{len(specifier)}",
        start_line=line_number,
        name=_safe_summary(specifier),
        target=target,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "import_kind": import_kind,
            "import_specifier": _safe_summary(_sanitize_url(specifier)),
            "source_key": source_key,
            "target_key": target,
            "not_loaded": True,
            "dynamic": dynamic,
            "dynamic_reason": "dynamic-import" if dynamic else None,
        },
    )
    reference = _reference_observation(
        relative_path,
        js_format,
        profile,
        line_number,
        import_kind,
        specifier,
        target,
        source_key,
        resolution_reason=reason,
        dynamic=dynamic,
        extra_metadata={"import_kind": import_kind},
    )
    return (import_observation, reference)


def _export_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    export_kind: str,
    specifier: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    target, reason = _specifier_target(relative_path, specifier, repository_paths)
    export_observation = _observation(
        kind="js.export",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-export:{line_number}:{len(specifier)}",
        start_line=line_number,
        name=_safe_summary(specifier),
        target=target,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "export_kind": export_kind,
            "import_specifier": _safe_summary(_sanitize_url(specifier)),
            "source_key": source_key,
            "target_key": target,
            "not_loaded": True,
        },
    )
    reference = _reference_observation(
        relative_path,
        js_format,
        profile,
        line_number,
        export_kind,
        specifier,
        target,
        source_key,
        resolution_reason=reason,
        extra_metadata={"export_kind": export_kind},
    )
    return (export_observation, reference)


def _literal_reference_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for match in FETCH_LITERAL_RE.finditer(line):
        raw_url = match.group("url")
        target, reason = _specifier_target(relative_path, raw_url, repository_paths)
        if target.startswith("external.url:"):
            observations.append(
                _reference_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    match.group("call"),
                    raw_url,
                    target,
                    source_key,
                    resolution_reason=reason,
                )
            )
    for match in IMPORT_SCRIPTS_RE.finditer(line):
        specifier = match.group("specifier")
        target, reason = _specifier_target(relative_path, specifier, repository_paths)
        observations.append(
            _reference_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                "importScripts",
                specifier,
                target,
                source_key,
                resolution_reason=reason,
            )
        )
    source_map_match = SOURCE_MAP_RE.search(line)
    if source_map_match:
        specifier = source_map_match.group("specifier")
        target, reason = _specifier_target(relative_path, specifier, repository_paths)
        observations.append(
            _reference_observation(
                relative_path,
                js_format,
                profile,
                line_number,
                "source_map",
                specifier,
                target,
                source_key,
                resolution_reason=reason,
                extra_metadata={"not_fetched": True},
            )
        )
    if profile == "angular":
        for match in ANGULAR_TEMPLATE_RE.finditer(line):
            raw_path = match.group("path")
            target, reason = _specifier_target(relative_path, raw_path, repository_paths)
            observations.append(
                _reference_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    match.group("kind"),
                    raw_path,
                    target,
                    source_key,
                    resolution_reason=reason,
                )
            )
    return tuple(observations)


def _function_and_variable_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    function_name = None
    for regex in (FUNCTION_RE, FUNCTION_EXPR_RE, ARROW_FUNCTION_RE):
        match = regex.match(line)
        if match:
            function_name = match.group("name")
            break
    if function_name:
        function_key = js_function_key(relative_path, function_name)
        observations.append(
            _definition_observation(
                "js.function",
                relative_path,
                js_format,
                profile,
                line_number,
                function_name,
                function_key,
                source_key=source_key,
                metadata={"function_name": function_name, "qualified_name": function_name},
            )
        )
        if _looks_like_component(function_name, profile, js_format, line):
            observations.append(
                _component_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    function_name,
                    source_key,
                )
            )

    variable_match = VARIABLE_RE.match(line)
    if variable_match:
        variable_name = variable_match.group("name")
        value = variable_match.group("value") or ""
        redacted = _is_secret_prone(variable_name) or _looks_like_secret_literal(value)
        metadata = {
            "variable_kind": variable_match.group("kind"),
            "local_name": variable_name,
            "literal_type": _literal_type(value),
            "redacted": redacted,
            "redaction_reason": "secret-prone-variable" if redacted else None,
        }
        observations.append(
            _definition_observation(
                "js.variable",
                relative_path,
                js_format,
                profile,
                line_number,
                variable_name,
                js_variable_key(relative_path, variable_name),
                source_key=source_key,
                metadata=metadata,
            )
        )
        if (
            function_name is None
            and (
                "defineComponent" in value
                or _looks_like_component(variable_name, profile, js_format, line)
            )
        ):
            observations.append(
                _component_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    variable_name,
                    source_key,
                )
            )
    return tuple(observations)


def _typescript_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for kind, regex in (
        ("js.interface", INTERFACE_RE),
        ("js.type_alias", TYPE_RE),
        ("js.enum", ENUM_RE),
    ):
        match = regex.match(line)
        if not match:
            continue
        name = match.group("name")
        observations.append(
            _observation(
                kind=kind,
                relative_path=relative_path,
                source_id=f"{relative_path}#{kind}:{name}:{line_number}",
                start_line=line_number,
                name=name,
                metadata={
                    "format": js_format,
                    "profile": profile,
                    "parser": PARSER,
                    "local_name": name,
                    "source_key": source_key,
                    "identity_strength": "symbolic",
                },
            )
        )
    return tuple(observations)


def _component_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    component_name: str,
    source_key: str,
) -> RawObservation:
    return _definition_observation(
        "js.component",
        relative_path,
        js_format,
        profile,
        line_number,
        component_name,
        js_component_key(relative_path, component_name),
        source_key=source_key,
        metadata={"component_name": component_name, "qualified_name": component_name},
    )


def _hook_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    hook_name: str,
    source_key: str,
) -> RawObservation:
    return _observation(
        kind="js.hook",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-hook:{hook_name}:{line_number}",
        start_line=line_number,
        name=hook_name,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "hook_name": hook_name,
            "source_key": source_key,
        },
    )


def _diagnostic_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    diagnostic_kind: str,
    name: str,
    *,
    redacted: bool,
) -> RawObservation:
    return _observation(
        kind="js.parse_error",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-diagnostic:{diagnostic_kind}:{line_number}",
        confidence="unknown",
        start_line=line_number,
        name=diagnostic_kind,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "error_kind": diagnostic_kind,
            "dynamic": True,
            "dynamic_reason": "environment",
            "redacted": redacted,
            "redaction_reason": "secret-prone-env-name" if redacted else None,
            "recovered": True,
        },
    )


def _parse_error(
    relative_path: str,
    js_format: str,
    profile: str,
    error_kind: str,
    message: str,
    line_number: int,
    *,
    dynamic_reason: str | None = None,
) -> RawObservation:
    return _observation(
        kind="js.parse_error",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-parse-error:{line_number}:{error_kind}",
        confidence="unknown",
        start_line=line_number,
        name=error_kind,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "error_kind": error_kind,
            "message_summary": message,
            "dynamic": dynamic_reason is not None,
            "dynamic_reason": dynamic_reason,
            "recovered": True,
        },
    )


def _specifier_target(
    relative_path: str,
    specifier: str,
    repository_paths: frozenset[str] | None,
) -> tuple[str, str]:
    sanitized = _sanitize_url(specifier)
    if _is_dynamic_literal(specifier):
        return dynamic_key("js.reference", "dynamic-specifier"), "dynamic"
    scheme = urlsplit(sanitized).scheme.lower()
    if scheme in REFERENCE_SCHEMES:
        return external_url_key(sanitized), "external-url"
    if scheme:
        return unknown_key("js.reference", "unsupported-scheme"), "unsupported-scheme"
    if specifier.startswith("~") or "*" in specifier:
        return dynamic_key("js.reference", "dynamic-path"), "dynamic"
    if specifier.startswith("/"):
        return external_key("file", "absolute-js-reference"), "absolute-file"
    if specifier.startswith("."):
        target = _local_path_target(relative_path, specifier, repository_paths)
        reason = "repo-escaping" if target.startswith("unknown:file:") else "repo-local"
        return target, reason
    clean_specifier = specifier.split("#", 1)[0].split("?", 1)[0]
    if PurePosixPath(clean_specifier).suffix and not specifier.startswith("@"):
        return (
            _local_path_target(relative_path, f"./{specifier}", repository_paths),
            "repo-local",
        )
    if "/" in specifier and not specifier.startswith("@"):
        return external_key("js-package", _package_name(specifier)), "external-js-package"
    if specifier:
        return external_key("js-package", _package_name(specifier)), "external-js-package"
    return unknown_key("js.reference", "empty-specifier"), "unknown"


def _local_path_target(
    relative_path: str,
    raw_path: str,
    repository_paths: frozenset[str] | None,
) -> str:
    clean_path = raw_path.split("#", 1)[0].split("?", 1)[0]
    base = PurePosixPath(relative_path).parent
    normalized = base.joinpath(clean_path)
    parts: list[str] = []
    for part in normalized.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return unknown_key("file", "repo-escaping-js-reference")
            parts.pop()
            continue
        parts.append(part)
    candidate = PurePosixPath(*parts).as_posix()
    if repository_paths is None:
        return file_key(candidate)
    for possible in _candidate_paths(candidate):
        if possible in repository_paths:
            return file_key(possible)
    return file_key(candidate)


def _candidate_paths(candidate: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for extension in LOCAL_RESOLUTION_EXTENSIONS:
        candidates.append(candidate + extension)
    for extension in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"):
        candidates.append(f"{candidate}/index{extension}")
    return tuple(dict.fromkeys(candidates))


def _package_name(specifier: str) -> str:
    if specifier.startswith("@"):
        parts = specifier.split("/")
        if len(parts) >= 2:
            return "/".join(parts[:2])
    return specifier.split("/", 1)[0]


def _route_patterns(line: str, profile: str) -> tuple[str, ...]:
    patterns: list[str] = []
    if profile == "react":
        patterns.extend(match.group("path") for match in JSX_ROUTE_RE.finditer(line))
    if profile in ("angular", "vue", "react"):
        patterns.extend(match.group("path") for match in OBJECT_ROUTE_RE.finditer(line))
    return tuple(pattern for pattern in patterns if not _is_dynamic_literal(pattern))


def _strip_line_comment(line: str) -> str:
    if "sourceMappingURL=" in line:
        return line
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in ("'", '"', "`"):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "/" and quote is None and line[index : index + 2] == "//":
            return line[:index]
    return line


def _dynamic_reasons(line: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if "${" in line or "`" in line and ("import(" in line or "require(" in line):
        reasons.append("interpolation")
    if re.search(r"\bimport\s*\(\s*[^\"'`]", line) or re.search(
        r"\bimport\s*\(\s*`", line
    ):
        reasons.append("dynamic-import")
    if re.search(r"\brequire\s*\(\s*[^\"']", line):
        reasons.append("dynamic-require")
    for token in ("eval", "Function"):
        if re.search(rf"\b{re.escape(token)}\b", line):
            reasons.append(token)
    return tuple(dict.fromkeys(reasons))


def _is_jest_profile(profile: str, relative_path: str, content: str) -> bool:
    return profile == "jest" or _detect_profile(relative_path, content, _detect_format(relative_path)) == "jest"


def _is_react_class(superclass: str | None) -> bool:
    return superclass in ("React.Component", "Component")


def _looks_like_component(name: str, profile: str, js_format: str, line: str) -> bool:
    if not name[:1].isupper():
        return False
    if name.isupper():
        return False
    return profile in ("react", "vue", "angular") or js_format in ("jsx", "tsx") or "<" in line


def _looks_like_non_method(line: str) -> bool:
    return line.startswith(("if ", "for ", "while ", "switch ", "catch ", "function "))


def _update_class_stack(class_stack: list[tuple[str, str, int]], line: str) -> None:
    if not class_stack:
        return
    name, key, depth = class_stack[-1]
    depth += _brace_delta(line)
    if depth <= 0 and "}" in line:
        class_stack.pop()
        return
    class_stack[-1] = (name, key, depth)


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _literal_type(value: str) -> str:
    stripped = value.strip().rstrip(";")
    if not stripped:
        return "unknown"
    if stripped[0:1] in ("'", '"', "`"):
        return "string"
    if stripped in ("true", "false"):
        return "boolean"
    if stripped == "null":
        return "null"
    if re.fullmatch(r"-?\d+", stripped):
        return "integer"
    if re.fullmatch(r"-?\d+\.\d+", stripped):
        return "decimal"
    if stripped.startswith("["):
        return "array"
    if stripped.startswith("{"):
        return "object"
    if "=>" in stripped or stripped.startswith("function"):
        return "function"
    return "expression"


def _is_dynamic_literal(value: str) -> bool:
    return "${" in value or "*" in value or value.startswith("`") or value.endswith("`")


def _is_secret_prone(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return any(marker.replace("_", "") in normalized for marker in SECRET_MARKERS)


def _looks_like_secret_literal(value: str) -> bool:
    if "PRIVATE KEY" in value or "BEGIN " in value and " KEY" in value:
        return True
    return bool(re.search(r"[A-Za-z0-9_-]{32,}", value)) and any(
        marker in value.lower() for marker in ("token", "secret", "key")
    )


def _safe_summary(value: str | None, *, max_length: int = 120) -> str | None:
    if value is None:
        return None
    summary = value.strip()
    if _is_secret_prone(summary):
        return "REDACTED"
    if len(summary) > max_length:
        return summary[: max_length - 3] + "..."
    return summary


def _sanitize_url(raw_url: str) -> str:
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return raw_url
    if parsed.scheme.lower() not in REFERENCE_SCHEMES:
        return raw_url
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    query_parts: list[str] = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        key, separator, value = part.partition("=")
        if _is_secret_prone(key) or _is_secret_prone(value):
            query_parts.append(f"{key}=REDACTED" if separator else key)
        else:
            query_parts.append(part)
    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            "&".join(query_parts),
            parsed.fragment,
        )
    )
