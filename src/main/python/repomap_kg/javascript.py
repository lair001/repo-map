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
ROUTE_METHODS = frozenset(("get", "post", "put", "patch", "delete", "options", "head"))
JEST_TEST_CALLS = frozenset(("it", "test"))
JEST_HOOK_CALLS = frozenset(("beforeEach", "afterEach", "beforeAll", "afterAll"))
REACT_HOOKS = frozenset(
    ("useState", "useEffect", "useMemo", "useCallback", "useReducer")
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
    pending_angular_component = False
    suite_count = 0
    current_suite_key: str | None = None
    case_count_by_owner: dict[str, int] = {}
    route_count = 0

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
            observations.append(
                _diagnostic_observation(
                    relative_path,
                    js_format,
                    profile,
                    line_number,
                    "env-reference",
                    env_name,
                    redacted=_is_secret_prone(env_name),
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
        else:
            side_effect_match = SIDE_EFFECT_IMPORT_RE.match(stripped)
            if side_effect_match and not stripped.startswith("import("):
                observations.extend(
                    _import_observations(
                        relative_path,
                        js_format,
                        profile,
                        line_number,
                        "side_effect_import",
                        side_effect_match.group("specifier"),
                        module_canonical_key,
                        repository_paths,
                    )
                )

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
            class_stack.append((class_name, class_key, _brace_delta(stripped)))
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
        if "expect(" in stripped and _is_jest_profile(profile, relative_path, content):
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
    if (
        "__tests__" in path.parts
        or ".test." in path.name
        or ".spec." in path.name
        or "@jest/globals" in content
        or re.search(r"\bdescribe\s*\(", content)
    ):
        return "jest"
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
