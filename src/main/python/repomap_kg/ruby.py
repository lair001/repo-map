"""Conservative static Ruby and Ruby-DSL extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from repomap_kg import __version__
from repomap_kg.graph_keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR = "repo-ruby"
PARSER = "stdlib-ruby-lexical"
MAX_FILE_BYTES = 512 * 1024
ROUTE_METHODS = frozenset(("get", "post", "put", "patch", "delete", "options", "head"))
REFERENCE_SCHEMES = frozenset(("http", "https", "mailto"))

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
    "rack_secret",
    "session_secret",
    "sinatra_secret",
    "hanami_secret",
    "vagrant_cloud_token",
    "vagrant_token",
    "gem_credentials",
    "rubygems_api_key",
)

MODULE_RE = re.compile(r"^\s*module\s+([A-Z]\w*(?:::[A-Z]\w*)*)\b")
CLASS_RE = re.compile(
    r"^\s*class\s+([A-Z]\w*(?:::[A-Z]\w*)*)"
    r"(?:\s*<\s*([A-Z]\w*(?:::[A-Z]\w*)*))?\b"
)
DEF_RE = re.compile(
    r"^\s*def\s+(self\.[A-Za-z_]\w*[!?=]?|"
    r"[A-Z]\w*(?:::[A-Z]\w*)*\.[A-Za-z_]\w*[!?=]?|"
    r"[A-Za-z_]\w*[!?=]?)\b"
)
CONSTANT_RE = re.compile(r"^\s*([A-Z]\w*)\s*=\s*(.+)$")
REQUIRE_RE = re.compile(r'^\s*(require|require_relative|load)\s*\(?\s*(["\'])(.*?)\2')
INCLUDE_RE = re.compile(r"^\s*(include|extend)\s+([A-Z]\w*(?:::[A-Z]\w*)*)\b")
ROUTE_RE = re.compile(
    r"""^\s*(get|post|put|patch|delete|options|head)\s*\(?\s*(["'])(.*?)\2"""
)
ERB_RE = re.compile(r"^\s*(erb|haml|slim)\s+(?::([A-Za-z_]\w*)|([\"'])(.*?)\3)")
VAGRANT_BOX_RE = re.compile(r'config\.vm\.box\s*=\s*(["\'])(.*?)\1')
VAGRANT_PROVIDER_RE = re.compile(r'config\.vm\.provider\s*(["\'])(.*?)\1')
VAGRANT_NETWORK_RE = re.compile(r'config\.vm\.network\s+(["\'])(.*?)\1')
VAGRANT_SYNCED_RE = re.compile(
    r'config\.vm\.synced_folder\s+(["\'])(.*?)\1\s*,\s*(["\'])(.*?)\3'
)
VAGRANT_PROVISION_RE = re.compile(r"config\.vm\.provision\b")
RAKE_DESC_RE = re.compile(r'^\s*desc\s+(["\'])(.*?)\1')
RAKE_NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?::([A-Za-z_]\w*)|([\"'])(.*?)\2)")
RAKE_TASK_RE = re.compile(r"^\s*task\s+(?::([A-Za-z_]\w*)|([\"'])(.*?)\2)")
GEM_RE = re.compile(r'^\s*gem\s+(["\'])(.*?)\1(?P<tail>.*)$')
GEM_SOURCE_RE = re.compile(r'^\s*source\s+(["\'])(.*?)\1')
GEMSPEC_DEP_RE = re.compile(
    r"\badd_(?:runtime_|development_)?dependency\s*\(?\s*([\"'])(.*?)\1(?P<tail>.*)$"
)
ENV_RE = re.compile(r'ENV(?:\.fetch)?\s*\[\s*(["\'])(.*?)\1\s*\]|ENV\.fetch\(\s*(["\'])(.*?)\3')
MINITEST_DESCRIBE_RE = re.compile(
    r'^\s*describe\s+(?:(["\'])(.*?)\1|([A-Z]\w*(?:::[A-Z]\w*)*))\s+do\b'
)
MINITEST_IT_RE = re.compile(r'^\s*it\s+(["\'])(.*?)\1\s+do\b')
SINATRA_DSL_RE = re.compile(r"^\s*(set|configure|before|after|helpers)\b")


@dataclass
class _Scope:
    kind: str
    name: str
    canonical_key: str | None = None
    test_case_key: str | None = None
    route_key: str | None = None


def extract_ruby_file_observations(
    relative_path: str,
    content: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    """Extract safe, static Ruby facts from local text."""

    profile = _detect_profile(relative_path, content)
    observations: list[RawObservation] = []
    file_canonical_key = ruby_file_key(relative_path)
    observations.append(
        _observation(
            kind="ruby.file",
            relative_path=relative_path,
            source_id=f"{relative_path}#ruby-file",
            name=relative_path,
            target=file_canonical_key,
            metadata={
                "format": "ruby",
                "profile": profile,
                "profiles": [profile],
                "parser": PARSER,
                "file_bytes": len(content.encode("utf-8", errors="replace")),
            },
        )
    )

    if len(content.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
        observations.append(
            _parse_error(
                relative_path,
                "file-size-limit",
                "ruby file exceeds static scanner limit",
                profile,
                1,
            )
        )
        return tuple(observations)

    stack: list[_Scope] = []
    last_rake_desc: str | None = None
    spec_case_count = 0
    spec_method_counts: dict[str, int] = {}
    lines = content.splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = _strip_comment(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        for dynamic_reason in _dynamic_reasons(stripped):
            observations.append(
                _parse_error(
                    relative_path,
                    f"dynamic-{dynamic_reason}",
                    "dynamic Ruby construct kept as diagnostic",
                    profile,
                    line_number,
                    dynamic_reason=dynamic_reason,
                )
            )

        env_match = ENV_RE.search(stripped)
        if env_match:
            env_name = env_match.group(2) or env_match.group(4) or ""
            observations.append(
                _diagnostic_observation(
                    relative_path,
                    profile,
                    line_number,
                    "env-reference",
                    env_name,
                    redacted=_is_secret_prone(env_name),
                )
            )

        if stripped == "end" or stripped.startswith("end "):
            _pop_scope(stack)
            continue

        module_match = MODULE_RE.match(stripped)
        if module_match:
            name = _qualify_name(module_match.group(1), stack)
            target = ruby_module_key(name)
            observations.append(
                _definition_observation(
                    "ruby.module",
                    relative_path,
                    profile,
                    line_number,
                    name,
                    target,
                    source_key=file_canonical_key,
                    metadata={"qualified_name": name},
                )
            )
            stack.append(_Scope("module", name, canonical_key=target))
            continue

        class_match = CLASS_RE.match(stripped)
        if class_match:
            name = _qualify_name(class_match.group(1), stack)
            superclass = class_match.group(2)
            target = ruby_class_key(name)
            metadata: dict[str, Any] = {"qualified_name": name}
            if superclass:
                metadata["superclass"] = superclass
            observations.append(
                _definition_observation(
                    "ruby.class",
                    relative_path,
                    profile,
                    line_number,
                    name,
                    target,
                    source_key=file_canonical_key,
                    metadata=metadata,
                )
            )
            test_case_key = None
            if _is_minitest_class(superclass, profile):
                test_case_key = ruby_test_case_key(relative_path, name)
                observations.append(
                    _definition_observation(
                        "ruby.test_case",
                        relative_path,
                        "minitest",
                        line_number,
                        name,
                        test_case_key,
                        source_key=file_canonical_key,
                        metadata={
                            "qualified_name": name,
                            "test_framework": "minitest",
                        },
                    )
                )
            stack.append(
                _Scope(
                    "class",
                    name,
                    canonical_key=target,
                    test_case_key=test_case_key,
                )
            )
            continue

        if profile == "minitest":
            describe_match = MINITEST_DESCRIBE_RE.match(stripped)
            if describe_match:
                spec_case_count += 1
                describe_text = describe_match.group(2) or describe_match.group(3) or ""
                test_case_name = f"describe[{spec_case_count}]"
                test_case_key = ruby_test_case_key(relative_path, test_case_name)
                observations.append(
                    _definition_observation(
                        "ruby.test_case",
                        relative_path,
                        "minitest",
                        line_number,
                        test_case_name,
                        test_case_key,
                        source_key=file_canonical_key,
                        metadata={
                            "qualified_name": test_case_name,
                            "test_framework": "minitest",
                            "test_name_summary": _safe_summary(describe_text),
                            "identity_strength": "structural",
                        },
                    )
                )
                stack.append(
                    _Scope(
                        "test_case",
                        test_case_name,
                        canonical_key=test_case_key,
                        test_case_key=test_case_key,
                    )
                )
                continue

            it_match = MINITEST_IT_RE.match(stripped)
            test_case_key = _current_test_case_key(stack)
            if it_match and test_case_key:
                method_count = spec_method_counts.get(test_case_key, 0) + 1
                spec_method_counts[test_case_key] = method_count
                method_name = f"it[{method_count}]"
                target_test = ruby_test_method_key(test_case_key, method_name)
                observations.append(
                    _definition_observation(
                        "ruby.test_method",
                        relative_path,
                        "minitest",
                        line_number,
                        method_name,
                        target_test,
                        source_key=test_case_key,
                        metadata={
                            "test_case_key": test_case_key,
                            "method_name": method_name,
                            "test_framework": "minitest",
                            "test_name_summary": _safe_summary(it_match.group(2)),
                            "identity_strength": "structural",
                        },
                    )
                )
                stack.append(_Scope("test_method", method_name, canonical_key=target_test))
                continue

        def_match = DEF_RE.match(stripped)
        if def_match:
            method_token = def_match.group(1)
            owner, method_name, singleton = _method_owner(method_token, stack)
            if owner and method_name:
                target = (
                    ruby_singleton_method_key(owner, method_name)
                    if singleton
                    else ruby_method_key(owner, method_name)
                )
                owner_key = _owner_key_for_scope(owner, stack) or file_canonical_key
                kind = "ruby.singleton_method" if singleton else "ruby.method"
                observations.append(
                    _definition_observation(
                        kind,
                        relative_path,
                        profile,
                        line_number,
                        method_name,
                        target,
                        source_key=owner_key,
                        metadata={
                            "qualified_name": f"{owner}.{method_name}",
                            "owner": owner,
                            "method_name": method_name,
                        },
                    )
                )
                test_case_key = _current_test_case_key(stack)
                if test_case_key and method_name.startswith("test_"):
                    target_test = ruby_test_method_key(test_case_key, method_name)
                    observations.append(
                        _definition_observation(
                            "ruby.test_method",
                            relative_path,
                            "minitest",
                            line_number,
                            method_name,
                            target_test,
                            source_key=test_case_key,
                            metadata={
                                "test_case_key": test_case_key,
                                "method_name": method_name,
                                "test_framework": "minitest",
                            },
                        )
                    )
                stack.append(_Scope("method", method_name, canonical_key=target))
                continue

        const_match = CONSTANT_RE.match(stripped)
        if const_match:
            constant_name = const_match.group(1)
            owner = _current_owner(stack) or "Object"
            target = ruby_constant_key(owner, constant_name)
            redacted = _is_secret_prone(constant_name)
            metadata = {
                "owner": owner,
                "constant_name": constant_name,
                "value_type": _literal_type(const_match.group(2)),
                "redacted": redacted,
            }
            if redacted:
                metadata["redaction_reason"] = "secret-prone-constant-name"
            observations.append(
                _definition_observation(
                    "ruby.constant",
                    relative_path,
                    profile,
                    line_number,
                    constant_name,
                    target,
                    source_key=_owner_key_for_scope(owner, stack) or file_canonical_key,
                    metadata=metadata,
                )
            )

        req_match = REQUIRE_RE.match(stripped)
        if req_match:
            require_form = req_match.group(1)
            raw_value = req_match.group(3)
            observations.extend(
                _require_observations(
                    relative_path,
                    profile,
                    line_number,
                    require_form,
                    raw_value,
                    file_canonical_key,
                    repository_paths,
                )
            )

        include_match = INCLUDE_RE.match(stripped)
        if include_match:
            kind_name = include_match.group(1)
            target_module = include_match.group(2)
            observations.append(
                _observation(
                    kind=f"ruby.{kind_name}",
                    relative_path=relative_path,
                    source_id=f"{relative_path}#ruby-{kind_name}:{line_number}",
                    start_line=line_number,
                    name=target_module,
                    target=target_module,
                    metadata={
                        "format": "ruby",
                        "profile": profile,
                        "parser": PARSER,
                        "module_name": target_module,
                        "source_key": _current_source_key(stack) or file_canonical_key,
                    },
                )
            )

        route_match = ROUTE_RE.match(stripped)
        if route_match and _looks_like_route_profile(profile, content, relative_path):
            route_method = route_match.group(1)
            route_pattern = route_match.group(3)
            if _is_dynamic_literal(route_pattern):
                observations.append(
                    _parse_error(
                        relative_path,
                        "dynamic-route",
                        "dynamic Ruby route was not canonicalized",
                        profile,
                        line_number,
                        dynamic_reason="route",
                    )
                )
            else:
                pointer = f"/routes/{route_method}:{route_pattern}"
                target = ruby_route_key(relative_path, pointer)
                route_profile = "sinatra" if profile == "sinatra" else "hanami"
                observations.append(
                    _definition_observation(
                        "ruby.route",
                        relative_path,
                        route_profile,
                        line_number,
                        f"{route_method} {route_pattern}",
                        target,
                        source_key=file_canonical_key,
                        metadata={
                            "route_method": route_method,
                            "route_pattern": route_pattern,
                            "route_pointer": pointer,
                        },
                    )
                )
                stack.append(_Scope("route", pointer, canonical_key=target, route_key=target))
                continue

        erb_match = ERB_RE.match(stripped)
        if erb_match and profile == "sinatra":
            template_name = erb_match.group(2) or erb_match.group(4)
            if template_name:
                template_path = f"views/{template_name}.{erb_match.group(1)}"
                observations.append(
                    _reference_observation(
                        relative_path,
                        profile,
                        line_number,
                        "template",
                        template_name,
                        _path_target(template_path, repository_paths),
                        _current_route_key(stack) or file_canonical_key,
                        resolution_reason="repo-local",
                    )
                )

        if profile == "vagrantfile":
            observations.extend(
                _vagrant_observations(
                    relative_path,
                    profile,
                    line_number,
                    stripped,
                    file_canonical_key,
                    repository_paths,
                )
            )

        if profile == "rake":
            desc_match = RAKE_DESC_RE.match(stripped)
            if desc_match:
                last_rake_desc = desc_match.group(2)
            task_match = RAKE_TASK_RE.match(stripped)
            if task_match:
                task_name = task_match.group(1) or task_match.group(3) or "unknown"
                observations.append(
                    _observation(
                        kind="ruby.dsl",
                        relative_path=relative_path,
                        source_id=f"{relative_path}#ruby-task:{task_name}:{line_number}",
                        start_line=line_number,
                        name=task_name,
                        metadata={
                            "format": "ruby",
                            "profile": "rake",
                            "parser": PARSER,
                            "dsl_name": "task",
                            "task_name": task_name,
                            "description_summary": last_rake_desc,
                            "source_key": file_canonical_key,
                        },
                    )
                )
                last_rake_desc = None
            namespace_match = RAKE_NAMESPACE_RE.match(stripped)
            if namespace_match:
                namespace_name = namespace_match.group(1) or namespace_match.group(3) or "unknown"
                observations.append(
                    _observation(
                        kind="ruby.dsl",
                        relative_path=relative_path,
                        source_id=(
                            f"{relative_path}#ruby-namespace:"
                            f"{namespace_name}:{line_number}"
                        ),
                        start_line=line_number,
                        name=namespace_name,
                        metadata={
                            "format": "ruby",
                            "profile": "rake",
                            "parser": PARSER,
                            "dsl_name": "namespace",
                            "namespace_name": namespace_name,
                            "source_key": file_canonical_key,
                        },
                    )
                )

        if profile == "gemfile":
            observations.extend(
                _gemfile_observations(
                    relative_path,
                    profile,
                    line_number,
                    stripped,
                    file_canonical_key,
                )
            )

        if profile == "gemspec":
            observations.extend(
                _gemspec_observations(
                    relative_path,
                    profile,
                    line_number,
                    stripped,
                    file_canonical_key,
                )
            )

        if profile == "sinatra" and SINATRA_DSL_RE.match(stripped):
            dsl_name = SINATRA_DSL_RE.match(stripped).group(1)
            observations.append(
                _observation(
                    kind="ruby.dsl",
                    relative_path=relative_path,
                    source_id=f"{relative_path}#ruby-sinatra-dsl:{dsl_name}:{line_number}",
                    start_line=line_number,
                    name=dsl_name,
                    metadata={
                        "format": "ruby",
                        "profile": "sinatra",
                        "parser": PARSER,
                        "dsl_name": dsl_name,
                        "source_key": _current_source_key(stack) or file_canonical_key,
                    },
                )
            )

        if _opens_block(stripped):
            stack.append(_Scope("block", f"block:{line_number}"))

    return tuple(observations)


def _detect_profile(relative_path: str, content: str) -> str:
    path = PurePosixPath(relative_path)
    filename = path.name
    lower_path = relative_path.lower()
    if filename == "Vagrantfile":
        return "vagrantfile"
    if filename == "Gemfile":
        return "gemfile"
    if filename.endswith(".gemspec"):
        return "gemspec"
    if filename == "Rakefile" or filename.endswith(".rake"):
        return "rake"
    if lower_path == "config/routes.rb" or "hanami::app" in content.lower():
        return "hanami"
    if "sinatra" in content.lower():
        return "sinatra"
    if "minitest" in content.lower() or lower_path.startswith("test/"):
        return "minitest"
    return "generic_ruby"


def _observation(*, kind: str, relative_path: str, source_id: str, metadata: dict[str, Any], confidence: str = "extracted", start_line: int | None = None, name: str | None = None, target: str | None = None) -> RawObservation:
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


def _definition_observation(kind: str, relative_path: str, profile: str, line_number: int, name: str, target: str, *, source_key: str, metadata: dict[str, Any]) -> RawObservation:
    payload = {
        "format": "ruby",
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


def _reference_observation(relative_path: str, profile: str, line_number: int, reference_kind: str, raw_value: str, target: str, source_key: str, *, resolution_reason: str, extra_metadata: dict[str, Any] | None = None) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "ruby",
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "reference_kind": reference_kind,
        "raw_value_summary": _safe_summary(raw_value),
        "source_key": source_key,
        "target_key": target,
        "resolution_reason": resolution_reason,
        "not_fetched": True,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _observation(
        kind="ruby.reference",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-reference:{reference_kind}:{line_number}:{len(raw_value)}",
        start_line=line_number,
        name=reference_kind,
        target=target,
        metadata=metadata,
    )


def _require_observations(relative_path: str, profile: str, line_number: int, require_form: str, raw_value: str, source_key: str, repository_paths: frozenset[str] | None) -> tuple[RawObservation, ...]:
    target, reason = _require_target(relative_path, require_form, raw_value, repository_paths)
    metadata = {
        "format": "ruby",
        "profile": profile,
        "parser": PARSER,
        "require_form": require_form,
        "require_path": _safe_summary(raw_value),
        "source_key": source_key,
        "target_key": target,
        "not_loaded": True,
    }
    return (
        _observation(
            kind="ruby.require",
            relative_path=relative_path,
            source_id=f"{relative_path}#ruby-require:{line_number}",
            start_line=line_number,
            name=raw_value,
            target=target,
            metadata=metadata,
        ),
        _reference_observation(
            relative_path,
            profile,
            line_number,
            require_form,
            raw_value,
            target,
            source_key,
            resolution_reason=reason,
        ),
    )


def _vagrant_observations(relative_path: str, profile: str, line_number: int, line: str, source_key: str, repository_paths: frozenset[str] | None) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    if match := VAGRANT_BOX_RE.search(line):
        box_name = match.group(2)
        target = external_key("vagrant-box", box_name)
        observations.append(
            _vagrant_config(relative_path, line_number, "box", profile, source_key)
        )
        observations.append(
            _reference_observation(
                relative_path,
                profile,
                line_number,
                "vagrant_box",
                box_name,
                target,
                source_key,
                resolution_reason="external-vagrant-box",
                extra_metadata={"vagrant_key": "box"},
            )
        )
    if match := VAGRANT_PROVIDER_RE.search(line):
        provider = match.group(2)
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "provider",
                profile,
                source_key,
                value_summary=provider,
            )
        )
    if match := VAGRANT_NETWORK_RE.search(line):
        network_name = match.group(2)
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "network",
                profile,
                source_key,
                value_summary=network_name,
            )
        )
    if match := VAGRANT_SYNCED_RE.search(line):
        local_path = match.group(2)
        target = _path_target(local_path, repository_paths)
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "synced_folder",
                profile,
                source_key,
            )
        )
        observations.append(
            _reference_observation(
                relative_path,
                profile,
                line_number,
                "vagrant_synced_folder",
                local_path,
                target,
                source_key,
                resolution_reason="repo-local" if target.startswith("file:") else "path",
                extra_metadata={"vagrant_key": "synced_folder"},
            )
        )
    if VAGRANT_PROVISION_RE.search(line):
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "provision",
                profile,
                source_key,
                redacted=True,
                dynamic=True,
                redaction_reason="provisioner-command-body-omitted",
            )
        )
    return tuple(observations)


def _vagrant_config(relative_path: str, line_number: int, vagrant_key: str, profile: str, source_key: str, *, value_summary: str | None = None, redacted: bool = False, dynamic: bool = False, redaction_reason: str | None = None) -> RawObservation:
    return _observation(
        kind="ruby.vagrant_config",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-vagrant:{vagrant_key}:{line_number}",
        start_line=line_number,
        name=vagrant_key,
        metadata={
            "format": "ruby",
            "profile": profile,
            "parser": PARSER,
            "dsl_name": "vagrant",
            "vagrant_key": vagrant_key,
            "value_summary": _safe_summary(value_summary) if value_summary else None,
            "source_key": source_key,
            "redacted": redacted,
            "dynamic": dynamic,
            "redaction_reason": redaction_reason,
        },
    )


def _gemfile_observations(relative_path: str, profile: str, line_number: int, line: str, source_key: str) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    if source_match := GEM_SOURCE_RE.match(line):
        source_url = _sanitize_url(source_match.group(2))
        target = external_url_key(source_url)
        observations.append(
            _reference_observation(
                relative_path,
                profile,
                line_number,
                "gem_source",
                source_url,
                target,
                source_key,
                resolution_reason="external-url",
            )
        )
    if gem_match := GEM_RE.match(line):
        gem_name = gem_match.group(2)
        observations.extend(
            _gem_dependency_observations(
                relative_path,
                profile,
                line_number,
                gem_name,
                gem_match.group("tail"),
                source_key,
                "gemfile",
            )
        )
    return tuple(observations)


def _gemspec_observations(relative_path: str, profile: str, line_number: int, line: str, source_key: str) -> tuple[RawObservation, ...]:
    if dep_match := GEMSPEC_DEP_RE.search(line):
        return _gem_dependency_observations(
            relative_path,
            profile,
            line_number,
            dep_match.group(2),
            dep_match.group("tail"),
            source_key,
            "gemspec",
        )
    return ()


def _gem_dependency_observations(relative_path: str, profile: str, line_number: int, gem_name: str, requirement_tail: str, source_key: str, dependency_source: str) -> tuple[RawObservation, ...]:
    target = external_key("ruby-gem", gem_name)
    requirement_summary = _first_literal(requirement_tail)
    dependency = _observation(
        kind="ruby.gem_dependency",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-gem:{gem_name}:{line_number}",
        start_line=line_number,
        name=gem_name,
        target=target,
        metadata={
            "format": "ruby",
            "profile": profile,
            "parser": PARSER,
            "gem_name": gem_name,
            "gem_requirement_summary": _safe_summary(requirement_summary),
            "dependency_source": dependency_source,
            "source_key": source_key,
        },
    )
    reference = _reference_observation(
        relative_path,
        profile,
        line_number,
        "gem_dependency",
        gem_name,
        target,
        source_key,
        resolution_reason="external-ruby-gem",
    )
    return (dependency, reference)


def _parse_error(relative_path: str, error_kind: str, message: str, profile: str, line_number: int, *, dynamic_reason: str | None = None) -> RawObservation:
    metadata = {
        "format": "ruby",
        "profile": profile,
        "parser": PARSER,
        "error_kind": error_kind,
        "message_summary": message,
        "dynamic": dynamic_reason is not None,
        "dynamic_reason": dynamic_reason,
        "recovered": True,
    }
    return _observation(
        kind="ruby.parse_error",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-parse-error:{line_number}:{error_kind}",
        confidence="unknown",
        start_line=line_number,
        name=error_kind,
        metadata=metadata,
    )


def _diagnostic_observation(relative_path: str, profile: str, line_number: int, diagnostic_kind: str, name: str, *, redacted: bool) -> RawObservation:
    metadata = {
        "format": "ruby",
        "profile": profile,
        "parser": PARSER,
        "diagnostic_kind": diagnostic_kind,
        "redacted": redacted,
        "redaction_reason": "secret-prone-env-name" if redacted else None,
        "dynamic": True,
        "dynamic_reason": "environment",
    }
    return _observation(
        kind="ruby.dsl",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-env:{line_number}",
        start_line=line_number,
        name=name,
        metadata=metadata,
    )


def _strip_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in ("'", '"'):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "#" and quote is None:
            return line[:index]
    return line


def _dynamic_reasons(line: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if "#{" in line:
        reasons.append("interpolation")
    for token in ("define_method", "send", "class_eval", "instance_eval", "eval", "method_missing"):
        if re.search(rf"\b{re.escape(token)}\b", line):
            reasons.append(token)
    return tuple(dict.fromkeys(reasons))


def _qualify_name(name: str, stack: list[_Scope]) -> str:
    if "::" in name:
        return name
    owner = _current_owner(stack)
    return f"{owner}::{name}" if owner else name


def _current_owner(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.kind in ("class", "module"):
            return scope.name
    return None


def _current_source_key(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.canonical_key:
            return scope.canonical_key
    return None


def _current_route_key(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.route_key:
            return scope.route_key
    return None


def _current_test_case_key(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.test_case_key:
            return scope.test_case_key
    return None


def _owner_key_for_scope(owner: str, stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.name == owner and scope.canonical_key:
            return scope.canonical_key
    return None


def _method_owner(method_token: str, stack: list[_Scope]) -> tuple[str | None, str | None, bool]:
    if method_token.startswith("self."):
        return _current_owner(stack), method_token.split(".", 1)[1], True
    if "." in method_token:
        owner, method_name = method_token.rsplit(".", 1)
        return owner, method_name, True
    return _current_owner(stack), method_token, False


def _pop_scope(stack: list[_Scope]) -> None:
    if stack:
        stack.pop()


def _opens_block(line: str) -> bool:
    if line.startswith(("module ", "class ", "def ")):
        return False
    return bool(re.search(r"\bdo\b", line)) or line.endswith(" do")


def _is_minitest_class(superclass: str | None, profile: str) -> bool:
    return superclass == "Minitest::Test" or profile == "minitest" and superclass is not None


def _looks_like_route_profile(profile: str, content: str, relative_path: str) -> bool:
    if profile in ("sinatra", "hanami"):
        return True
    if relative_path == "config/routes.rb":
        return True
    lowered = content.lower()
    return "sinatra" in lowered or "hanami" in lowered


def _is_dynamic_literal(value: str) -> bool:
    return "#{" in value


def _require_target(relative_path: str, require_form: str, raw_value: str, repository_paths: frozenset[str] | None) -> tuple[str, str]:
    if _is_dynamic_literal(raw_value):
        return dynamic_key("ruby.reference", "interpolated-require"), "dynamic"
    if require_form == "require_relative":
        candidate = _normalize_relative_path(relative_path, raw_value, default_suffix=".rb")
        if candidate is None:
            return unknown_key("file", "repo-escaping-ruby-reference"), "repo-escaping"
        if repository_paths is None or candidate in repository_paths:
            return file_key(candidate), "repo-local"
        return file_key(candidate), "repo-local-candidate"
    if raw_value.startswith(("./", "../")):
        candidate = _normalize_relative_path(relative_path, raw_value, default_suffix=".rb")
        if candidate is None:
            return unknown_key("file", "repo-escaping-ruby-reference"), "repo-escaping"
        return file_key(candidate), "repo-local"
    return external_key("ruby.require", raw_value), "external-ruby-require"


def _normalize_relative_path(relative_path: str, raw_value: str, *, default_suffix: str | None = None) -> str | None:
    base = PurePosixPath(relative_path).parent
    candidate = PurePosixPath(raw_value)
    if not candidate.suffix and default_suffix:
        candidate = candidate.with_suffix(default_suffix)
    normalized = _normalize_posix(base / candidate)
    if normalized is None or normalized.startswith("../"):
        return None
    return normalized


def _normalize_posix(path: PurePosixPath) -> str | None:
    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _path_target(raw_path: str, repository_paths: frozenset[str] | None) -> str:
    if _is_dynamic_literal(raw_path) or raw_path.startswith(("~", "$")) or "*" in raw_path:
        return dynamic_key("ruby.reference", "dynamic-path")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw_path):
        scheme = raw_path.split(":", 1)[0].lower()
        if scheme in REFERENCE_SCHEMES:
            return external_url_key(_sanitize_url(raw_path))
        return unknown_key("ruby.reference", "unsupported-scheme")
    path = PurePosixPath(raw_path)
    if path.is_absolute():
        return external_key("file", "absolute-ruby-reference")
    normalized = _normalize_posix(path)
    if normalized is None:
        return unknown_key("file", "repo-escaping-ruby-reference")
    if repository_paths is None or normalized in repository_paths:
        return file_key(normalized)
    return file_key(normalized)


def _sanitize_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "about:invalid"
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    query = "&".join(
        f"{key}=REDACTED" if _is_secret_prone(key) else pair
        for pair in parsed.query.split("&")
        if pair
        for key in [pair.split("=", 1)[0]]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def _safe_summary(value: str | None) -> str | None:
    if value is None:
        return None
    if _is_secret_prone(value):
        return "REDACTED"
    value = value.strip()
    if len(value) > 120:
        return value[:117] + "..."
    return value


def _literal_type(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith(("'", '"')):
        return "string"
    if stripped in ("true", "false"):
        return "boolean"
    if re.fullmatch(r"-?\d+", stripped):
        return "integer"
    if stripped.startswith("["):
        return "array"
    if stripped.startswith("{"):
        return "hash"
    return "expression"


def _first_literal(text: str) -> str | None:
    match = re.search(r'(["\'])(.*?)\1', text)
    if not match:
        return None
    return match.group(2)


def _is_secret_prone(value: str | None) -> bool:
    if not value:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return any(marker in normalized for marker in SECRET_MARKERS)
