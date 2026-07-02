"""Static structured configuration raw observation extraction."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import tomllib
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.graph_keys import (
    config_document_key,
    config_path_key,
    dynamic_key,
    env_key,
    external_key,
    external_url_key,
    file_key,
    tool_key,
    unknown_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR_NAME = "repo-config"
SECRET_PRONE_KEYS = (
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
    "kubeconfig",
    "service_account",
    "dockerconfigjson",
    "registry_password",
    "connection_string",
    "jdbc_url",
    "datasource_password",
    "grafana_api_key",
    "arq_encryption_key",
    "arq_password",
    "arq_destination_password",
    "securejsondata",
)
ENV_CONTAINER_KEYS = frozenset(("env", "environment", "env_vars"))
TOOL_KEYS = frozenset(("command", "cmd", "executable", "program"))
PATH_KEY_MARKERS = ("path", "file", "cwd")
STABLE_ARRAY_MEMBER_KEYS = ("name", "id", "key", "project")
SIMPLE_COMMAND_PATTERN = re.compile(r"^[0-9A-Za-z_.+-]+$")
ENV_REFERENCE_PATTERN = re.compile(r"^\$(?P<brace>\{?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}?$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DYNAMIC_MARKERS = ("${", "$(", "{{", "}}", "*", "?", "~")
PLIST_XML_FORMAT = "plist-xml"
PLIST_XML_SAFETY_MODE = "pre-scan-no-doctype-entity-no-external-resources"
GENERIC_XML_FORMAT = "xml"
GENERIC_XML_SAFETY_MODE = "pre-scan-no-doctype-entity-no-external-resources"
YAML_FORMAT = "yaml"
YAML_PARSER = "stdlib-yaml-conservative"
YAML_MAX_FILE_BYTES = 1_048_576
YAML_MAX_DOCUMENTS = 64
YAML_MAX_NODES = 25_000
YAML_MAX_DEPTH = 64
YAML_MAX_SCALAR_LENGTH = 4_096
YAML_MAX_ALIASES = 512
UNSAFE_XML_DECLARATION_PATTERN = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
UNSAFE_PROCESSING_INSTRUCTION_PATTERN = re.compile(
    r"<\?(?!xml(?:\s|\?>))", re.IGNORECASE
)
PLIST_ROOT_PATTERN = re.compile(r"<\s*plist(?:\s|>)", re.IGNORECASE)
YAML_TAG_PATTERN = re.compile(r"^![A-Za-z0-9_./:-]+$")
YAML_ANCHOR_PATTERN = re.compile(r"^&[A-Za-z0-9_.-]+$")
YAML_ALIAS_PATTERN = re.compile(r"^\*[A-Za-z0-9_.-]+$")
YAML_SIMPLE_IMAGE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?(?:@[A-Za-z0-9:_-]+)?$"
)
TFJSON_PROFILE_FORMATS = frozenset({"json", "jsonc"})
TFJSON_PACKAGE_DEPENDENCY_GROUPS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)
TFJSON_FRAMEWORK_DEPENDENCY_HINTS = {
    "@angular/core": "angular",
    "@nestjs/core": "nestjs",
    "express": "express",
    "jest": "jest",
    "jquery": "jquery",
    "next": "next",
    "react": "react",
    "vue": "vue",
}
TERRAFORM_HCL_FORMAT = "terraform-hcl"
TERRAFORM_HCL_PROFILE = "terraform"
TERRAFORM_HCL_TFVARS_PROFILE = "terraform_tfvars"
TERRAFORM_HCL_PARSER = "repo-terraform-hcl-shallow-scanner"
TERRAFORM_HCL_BLOCK_TYPES = frozenset(
    (
        "terraform",
        "provider",
        "resource",
        "data",
        "module",
        "variable",
        "output",
        "locals",
        "moved",
        "import",
        "check",
        "removed",
    )
)
TERRAFORM_HCL_MAX_FILE_BYTES = 1_048_576
TERRAFORM_HCL_MAX_BLOCKS = 256
TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK = 128
TERRAFORM_HCL_MAX_REFERENCES = 512
TERRAFORM_HCL_MAX_METADATA_STRING = 160
TERRAFORM_HCL_MAX_DIAGNOSTICS = 64
TERRAFORM_HCL_BLOCK_HEADER_PATTERN = re.compile(
    r'^\s*(?P<block_type>[A-Za-z_][A-Za-z0-9_-]*)'
    r'(?P<labels>(?:\s+"(?:[^"\\]|\\.)*")*)\s*\{'
)
TERRAFORM_HCL_ATTRIBUTE_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(?P<value>.*)$"
)
TERRAFORM_HCL_TRAVERSAL_PATTERN = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_*-]+)+\b"
)
OPENAPI_HTTP_METHODS = frozenset(
    ("get", "post", "put", "patch", "delete", "options", "head", "trace")
)
OPENAPI_MAX_PATHS = 128
OPENAPI_MAX_OPERATIONS = 256
OPENAPI_MAX_PARAMETERS_PER_OPERATION = 64
OPENAPI_MAX_RESPONSES_PER_OPERATION = 64
OPENAPI_MAX_SCHEMAS = 256
OPENAPI_MAX_REFERENCES = 512
OPENAPI_MAX_EXAMPLES = 128
OPENAPI_MAX_METADATA_STRING = 160
OPENAPI_TEXT_KEYS = frozenset(("description", "summary"))
OPENAPI_EXAMPLE_KEYS = frozenset(("example", "examples", "default"))
PYTHON_REQUIREMENTS_FORMAT = "python-requirements"
PYTHON_REQUIREMENTS_PROFILE = "python"
PYTHON_REQUIREMENTS_NAME_PATTERN = re.compile(
    r"^(?:requirements(?:-[0-9A-Za-z_.-]+)?|dev-requirements|test-requirements)\.txt$"
)
PYTHON_REQUIREMENT_NAME_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)"
    r"(?P<extras>\[[A-Za-z0-9_, .-]+\])?"
    r"(?P<specifier>.*)$"
)
PYTHON_MAX_REQUIREMENTS = 256
PYTHON_MAX_REQUIREMENT_REFERENCES = 128
PYTHON_MAX_REQUIREMENT_DIAGNOSTICS = 64
PYTHON_MAX_METADATA_STRING = 160


class JsoncNormalizationError(ValueError):
    """Raised when conservative JSONC normalization cannot safely continue."""


class PlistXmlSafetyError(ValueError):
    """Raised when XML content uses constructs XML1 refuses to parse."""


class PlistXmlParseError(ValueError):
    """Raised when XML content is not a supported plist structure."""


class GenericXmlSafetyError(ValueError):
    """Raised when generic XML content uses constructs XML2 refuses to parse."""


class YamlParseError(ValueError):
    """Raised when conservative YAML parsing cannot safely continue."""

    def __init__(
        self,
        message: str,
        *,
        error_kind: str = "malformed-yaml",
        line_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_kind = error_kind
        self.line_number = line_number


@dataclass(frozen=True)
class _YamlLine:
    indent: int
    text: str
    line_number: int


@dataclass(frozen=True)
class _YamlValue:
    value: Any
    yaml_tag: str | None = None
    anchor: str | None = None
    alias: str | None = None
    metadata_only: bool = False


@dataclass
class _YamlParseState:
    node_count: int = 0
    alias_count: int = 0
    metadata_by_pointer: dict[str, dict[str, Any]] | None = None

    def metadata(self) -> dict[str, dict[str, Any]]:
        if self.metadata_by_pointer is None:
            self.metadata_by_pointer = {}
        return self.metadata_by_pointer


@dataclass(frozen=True)
class _TerraformHclBlock:
    block_type: str
    labels: tuple[str, ...]
    body: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class _TerraformHclAttribute:
    name: str
    value: str
    start_line: int


@dataclass(frozen=True)
class _PythonRequirement:
    package_name: str | None
    specifier: str | None
    extras: tuple[str, ...]
    environment_marker: str | None
    source: str | None
    editable: bool
    direct_url: bool
    local_path: bool
    line_number: int
    raw_kind: str


def extract_config_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    suffix = PurePosixPath(relative_path).suffix.lower()
    if _is_python_requirements_file_name(relative_path):
        return _extract_python_requirements_observations(relative_path, content)
    if _is_terraform_hcl_file_name(relative_path):
        return _extract_terraform_hcl_observations(relative_path, content)
    if _is_terraform_tfvars_hcl_file_name(relative_path):
        return _extract_terraform_hcl_tfvars_observations(relative_path, content)
    if suffix == ".jsonl":
        return _extract_jsonl_observations(relative_path, content)
    if suffix == ".jsonc":
        return _extract_jsonc_observations(relative_path, content)
    if suffix == ".toml":
        return _extract_toml_observations(relative_path, content)
    if suffix in (".yaml", ".yml"):
        return _extract_yaml_observations(relative_path, content)
    if suffix == ".plist":
        return _extract_plist_xml_observations(relative_path, content)
    if suffix == ".xml":
        if _looks_like_plist_xml(content):
            return _extract_plist_xml_observations(relative_path, content)
        return _extract_generic_xml_observations(relative_path, content)
    return _extract_json_observations(relative_path, content)


def json_pointer(segments: tuple[str, ...] | list[str]) -> str:
    if not segments:
        return ""
    return "/" + "/".join(_escape_pointer_segment(segment) for segment in segments)


def _extract_json_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        parse_error = _parse_error_observation(
            relative_path,
            format_name="json",
            error_kind="malformed-json",
            error=error,
            recovered=False,
        )
        if _is_openapi_file_name(relative_path):
            return (
                parse_error,
                _openapi_parse_error_observation(
                    relative_path,
                    format_name="json",
                    error_kind="malformed-openapi-json",
                    message=str(error),
                    start_line=error.lineno,
                ),
            )
        return (
            parse_error,
        )
    profile = _tfjson_profile(relative_path, parsed, format_name="json")
    metadata_overrides = _tfjson_metadata_overrides(
        relative_path,
        parsed,
        profile=profile,
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="json",
        confidence="extracted",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    profile_observations = _tfjson_profile_observations(
        relative_path,
        parsed,
        format_name="json",
        confidence="extracted",
        profile=profile,
        content=content,
    )
    document = _document_observation(
        relative_path,
        format_name="json",
        parser="stdlib-json",
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
        extra_metadata=_tfjson_document_metadata(profile),
    )
    return (document, *profile_observations, *path_observations, *reference_observations)


def _extract_jsonc_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        normalized = normalize_jsonc(content)
        parsed = json.loads(normalized)
    except JsoncNormalizationError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name="jsonc",
                error_kind="unsupported-jsonc-construct",
                message=str(error),
                recovered=False,
            ),
        )
    except json.JSONDecodeError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name="jsonc",
                error_kind="malformed-jsonc",
                error=error,
                recovered=False,
            ),
        )
    profile = _tfjson_profile(relative_path, parsed, format_name="jsonc")
    metadata_overrides = _tfjson_metadata_overrides(
        relative_path,
        parsed,
        profile=profile,
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="jsonc",
        confidence="heuristic",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    profile_observations = _tfjson_profile_observations(
        relative_path,
        parsed,
        format_name="jsonc",
        confidence="heuristic",
        profile=profile,
        content=content,
    )
    document = _document_observation(
        relative_path,
        format_name="jsonc",
        parser="jsonc-conservative",
        confidence="heuristic",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
        extra_metadata=_tfjson_document_metadata(profile),
    )
    return (document, *profile_observations, *path_observations, *reference_observations)


def _extract_jsonl_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    path_observations: list[RawObservation] = []
    reference_observations: list[RawObservation] = []
    records: list[RawObservation] = []
    errors: list[RawObservation] = []
    parseable_record_index = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(
                _parse_error_observation(
                    relative_path,
                    format_name="jsonl",
                    error_kind="malformed-jsonl-line",
                    error=error,
                    start_line=line_number,
                    recovered=True,
                )
            )
            continue
        records.append(
            _jsonl_record_observation(
                relative_path,
                parsed,
                line_number=line_number,
                record_index=parseable_record_index,
            )
        )
        if isinstance(parsed, dict):
            paths, references = _structure_observations(
                relative_path,
                parsed,
                format_name="jsonl",
                confidence="extracted",
                content=line,
                source_suffix=f":record-{parseable_record_index}",
                line_offset=line_number - 1,
            )
            path_observations.extend(paths)
            reference_observations.extend(references)
        parseable_record_index += 1
    document = _document_observation(
        relative_path,
        format_name="jsonl",
        parser="stdlib-json",
        confidence="extracted" if not errors else "heuristic",
        top_level_type="mixed-jsonl",
        path_count=len(path_observations),
        record_count=len(records),
        parse_error_count=len(errors),
    )
    return (
        document,
        *records,
        *path_observations,
        *reference_observations,
        *errors,
    )


def _extract_toml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        parse_error = _parse_error_observation(
            relative_path,
            format_name="toml",
            error_kind="malformed-toml",
            message=str(error),
            start_line=getattr(error, "lineno", None),
            recovered=False,
        )
        if _is_pyproject_file_name(relative_path):
            return (
                parse_error,
                _python_parse_error_observation(
                    relative_path,
                    error_kind="malformed-pyproject-toml",
                    message=str(error),
                    start_line=getattr(error, "lineno", None),
                    source_suffix="pyproject",
                ),
            )
        return (parse_error,)
    metadata_overrides = (
        _python_pyproject_metadata_overrides(parsed)
        if _is_pyproject_file_name(relative_path)
        else None
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="toml",
        confidence="extracted",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    profile_observations: tuple[RawObservation, ...] = ()
    if _is_pyproject_file_name(relative_path):
        profile_observations = _python_pyproject_observations(
            relative_path,
            parsed,
            format_name="toml",
            confidence="extracted",
        )
    document = _document_observation(
        relative_path,
        format_name="toml",
        parser="stdlib-tomllib",
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
    )
    return (document, *profile_observations, *path_observations, *reference_observations)


def _extract_yaml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        parsed, metadata_overrides, document_count = _parse_yaml_documents(
            relative_path,
            content,
        )
    except YamlParseError as error:
        observation = _parse_error_observation(
            relative_path,
            format_name=YAML_FORMAT,
            error_kind=error.error_kind,
            message=str(error),
            start_line=error.line_number,
            recovered=False,
        )
        if error.error_kind == "duplicate-yaml-key":
            observation.metadata["duplicate_key_policy"] = "parse-error"
        if _is_openapi_file_name(relative_path):
            return (
                observation,
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=YAML_FORMAT,
                    error_kind="malformed-openapi-yaml",
                    message=str(error),
                    start_line=error.line_number,
                ),
            )
        return (observation,)

    profile = _yaml_profile(relative_path, parsed, document_count=document_count)
    _apply_yaml_profile_metadata(
        parsed,
        metadata_overrides,
        profile=profile,
        document_count=document_count,
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name=YAML_FORMAT,
        confidence="extracted",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    document = _document_observation(
        relative_path,
        format_name=YAML_FORMAT,
        parser=YAML_PARSER,
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
        extra_metadata={
            "profile": profile,
            "document_count": document_count,
            "duplicate_key_policy": "parse-error",
        },
    )
    profile_observations = ()
    if profile == "openapi":
        profile_observations = _openapi_profile_observations(
            relative_path,
            parsed,
            format_name=YAML_FORMAT,
            confidence="extracted",
            profile=profile,
            document_count=document_count,
        )
    return (document, *profile_observations, *path_observations, *reference_observations)


def _parse_yaml_documents(
    relative_path: str,
    content: str,
) -> tuple[Any, dict[str, dict[str, Any]], int]:
    encoded_size = len(content.encode("utf-8"))
    if encoded_size > YAML_MAX_FILE_BYTES:
        raise YamlParseError(
            "YAML file exceeds conservative byte limit",
            error_kind="yaml-file-byte-limit",
        )
    documents = _split_yaml_documents(content)
    if len(documents) > YAML_MAX_DOCUMENTS:
        raise YamlParseError(
            "YAML stream exceeds conservative document limit",
            error_kind="yaml-document-count-limit",
        )

    parsed_documents: list[Any] = []
    all_metadata: dict[str, dict[str, Any]] = {}
    for document_index, document_lines in enumerate(documents):
        state = _YamlParseState()
        lines = _yaml_logical_lines(document_lines)
        if not lines:
            parsed = None
        else:
            parsed, next_index = _parse_yaml_block(
                lines,
                0,
                lines[0].indent,
                state,
                pointer_segments=(),
                depth=0,
            )
            if next_index != len(lines):
                line = lines[next_index]
                raise YamlParseError(
                    "unsupported YAML structure after parsed document",
                    line_number=line.line_number,
                )
        parsed_documents.append(parsed)
        pointer_prefix: tuple[str, ...]
        if len(documents) == 1:
            pointer_prefix = ()
        else:
            pointer_prefix = ("documents", str(document_index))
        for pointer, metadata in state.metadata().items():
            combined_pointer = json_pointer(
                (*pointer_prefix, *_pointer_segments(pointer))
            )
            all_metadata.setdefault(combined_pointer, {}).update(metadata)

    if len(parsed_documents) == 1:
        parsed_value = parsed_documents[0]
    else:
        parsed_value = {
            "documents": {
                str(index): value for index, value in enumerate(parsed_documents)
            }
        }
    return parsed_value, all_metadata, len(parsed_documents)


def _split_yaml_documents(content: str) -> list[tuple[tuple[int, str], ...]]:
    documents: list[list[tuple[int, str]]] = [[]]
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped == "---":
            if documents[-1]:
                documents.append([])
            continue
        if stripped == "...":
            if documents[-1]:
                documents.append([])
            continue
        documents[-1].append((line_number, line))
    return [tuple(document) for document in documents if document] or [()]


def _yaml_logical_lines(lines: tuple[tuple[int, str], ...]) -> tuple[_YamlLine, ...]:
    logical_lines: list[_YamlLine] = []
    for line_number, raw_line in lines:
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip(" \t"))]:
            raise YamlParseError(
                "tabs are not supported for YAML indentation",
                line_number=line_number,
            )
        stripped_comment = _strip_yaml_comment(raw_line).rstrip()
        if not stripped_comment.strip():
            continue
        indent = len(stripped_comment) - len(stripped_comment.lstrip(" "))
        logical_lines.append(
            _YamlLine(
                indent=indent,
                text=stripped_comment.strip(),
                line_number=line_number,
            )
        )
    return tuple(logical_lines)


def _parse_yaml_block(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[Any, int]:
    if depth > YAML_MAX_DEPTH:
        raise YamlParseError(
            "YAML nesting exceeds conservative depth limit",
            error_kind="yaml-depth-limit",
            line_number=lines[index].line_number if index < len(lines) else None,
        )
    if index >= len(lines):
        return None, index
    line = lines[index]
    if line.indent < indent:
        return None, index
    if line.indent > indent:
        raise YamlParseError(
            "unexpected YAML indentation",
            line_number=line.line_number,
        )
    if line.text.startswith("- "):
        return _parse_yaml_sequence(
            lines,
            index,
            indent,
            state,
            pointer_segments=pointer_segments,
            depth=depth,
        )
    return _parse_yaml_mapping(
        lines,
        index,
        indent,
        state,
        pointer_segments=pointer_segments,
        depth=depth,
    )


def _parse_yaml_mapping(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    seen_keys: set[str] = set()
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlParseError(
                "unexpected YAML indentation",
                line_number=line.line_number,
            )
        if line.text.startswith("- "):
            break
        key, value_text = _split_yaml_mapping_pair(line.text, line.line_number)
        if key in seen_keys:
            raise YamlParseError(
                f"duplicate YAML key: {key}",
                error_kind="duplicate-yaml-key",
                line_number=line.line_number,
            )
        seen_keys.add(key)
        child_segments = (*pointer_segments, key)
        value, index = _yaml_value_or_nested_block(
            lines,
            index,
            indent,
            value_text,
            state,
            pointer_segments=child_segments,
            depth=depth,
        )
        mapping[key] = value
        state.node_count += 1
        if state.node_count > YAML_MAX_NODES:
            raise YamlParseError(
                "YAML node count exceeds conservative limit",
                error_kind="yaml-node-count-limit",
                line_number=line.line_number,
            )
    return mapping, index


def _parse_yaml_sequence(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[list[Any], int]:
    sequence: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlParseError(
                "unexpected YAML indentation",
                line_number=line.line_number,
            )
        if not line.text.startswith("- "):
            break
        item_text = line.text[2:].strip()
        item_index = len(sequence)
        child_segments = (*pointer_segments, str(item_index))
        if not item_text:
            next_index = index + 1
            if next_index < len(lines) and lines[next_index].indent > indent:
                value, index = _parse_yaml_block(
                    lines,
                    next_index,
                    lines[next_index].indent,
                    state,
                    pointer_segments=child_segments,
                    depth=depth + 1,
                )
            else:
                value, index = None, next_index
        elif _looks_like_yaml_mapping_pair(item_text):
            key, value_text = _split_yaml_mapping_pair(item_text, line.line_number)
            item_mapping: dict[str, Any] = {}
            value, next_index = _yaml_value_or_nested_block(
                lines,
                index,
                indent,
                value_text,
                state,
                pointer_segments=(*child_segments, key),
                depth=depth,
            )
            item_mapping[key] = value
            if next_index < len(lines) and lines[next_index].indent > indent:
                extra, next_index = _parse_yaml_block(
                    lines,
                    next_index,
                    lines[next_index].indent,
                    state,
                    pointer_segments=child_segments,
                    depth=depth + 1,
                )
                if isinstance(extra, dict):
                    for extra_key, extra_value in extra.items():
                        if extra_key in item_mapping:
                            raise YamlParseError(
                                f"duplicate YAML key: {extra_key}",
                                error_kind="duplicate-yaml-key",
                                line_number=line.line_number,
                            )
                        item_mapping[extra_key] = extra_value
                else:
                    raise YamlParseError(
                        "sequence item cannot combine scalar and nested sequence",
                        line_number=line.line_number,
                    )
            value, index = item_mapping, next_index
        else:
            parsed = _parse_yaml_scalar(item_text, line.line_number, state)
            _record_yaml_value_metadata(
                parsed,
                state,
                pointer_segments=child_segments,
                merge_key=False,
            )
            value = parsed.value
            index += 1
        sequence.append(value)
        state.node_count += 1
        if state.node_count > YAML_MAX_NODES:
            raise YamlParseError(
                "YAML node count exceeds conservative limit",
                error_kind="yaml-node-count-limit",
                line_number=line.line_number,
            )
    return sequence, index


def _yaml_value_or_nested_block(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    value_text: str,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[Any, int]:
    line = lines[index]
    parsed = _parse_yaml_scalar(value_text, line.line_number, state)
    next_index = index + 1
    merge_key = bool(pointer_segments and pointer_segments[-1] == "<<")
    if parsed.metadata_only and next_index < len(lines) and lines[next_index].indent > indent:
        value, next_index = _parse_yaml_block(
            lines,
            next_index,
            lines[next_index].indent,
            state,
            pointer_segments=pointer_segments,
            depth=depth + 1,
        )
    elif parsed.metadata_only:
        value = None
    else:
        value = parsed.value
    _record_yaml_value_metadata(
        parsed,
        state,
        pointer_segments=pointer_segments,
        merge_key=merge_key,
    )
    return value, next_index


def _parse_yaml_scalar(
    text: str,
    line_number: int,
    state: _YamlParseState,
) -> _YamlValue:
    stripped = text.strip()
    yaml_tag: str | None = None
    anchor: str | None = None
    while True:
        token, rest = _yaml_first_token(stripped)
        if token is not None and YAML_TAG_PATTERN.match(token):
            yaml_tag = token
            stripped = rest
            continue
        if token is not None and YAML_ANCHOR_PATTERN.match(token):
            anchor = token[1:]
            stripped = rest
            continue
        break
    if not stripped:
        return _YamlValue(None, yaml_tag=yaml_tag, anchor=anchor, metadata_only=True)
    if YAML_ALIAS_PATTERN.match(stripped):
        state.alias_count += 1
        if state.alias_count > YAML_MAX_ALIASES:
            raise YamlParseError(
                "YAML alias count exceeds conservative limit",
                error_kind="yaml-alias-count-limit",
                line_number=line_number,
            )
        return _YamlValue(
            stripped[1:],
            yaml_tag=yaml_tag,
            anchor=anchor,
            alias=stripped[1:],
        )
    if len(stripped) > YAML_MAX_SCALAR_LENGTH:
        raise YamlParseError(
            "YAML scalar exceeds conservative length limit",
            error_kind="yaml-scalar-length-limit",
            line_number=line_number,
        )
    if stripped.startswith("["):
        if not stripped.endswith("]"):
            raise YamlParseError(
                "unterminated YAML inline sequence",
                line_number=line_number,
            )
        return _YamlValue(
            _parse_yaml_inline_sequence(stripped, line_number, state),
            yaml_tag=yaml_tag,
            anchor=anchor,
        )
    if stripped.startswith("{"):
        if not stripped.endswith("}"):
            raise YamlParseError(
                "unterminated YAML inline mapping",
                line_number=line_number,
            )
        return _YamlValue(
            _parse_yaml_inline_mapping(stripped, line_number, state),
            yaml_tag=yaml_tag,
            anchor=anchor,
        )
    return _YamlValue(_parse_yaml_plain_scalar(stripped), yaml_tag=yaml_tag, anchor=anchor)


def _record_yaml_value_metadata(
    parsed: _YamlValue,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    merge_key: bool,
) -> None:
    if not pointer_segments:
        return
    metadata: dict[str, Any] = {}
    if parsed.yaml_tag is not None:
        metadata["yaml_tag"] = parsed.yaml_tag
        if _is_secret_key(parsed.yaml_tag):
            metadata["redacted"] = True
            metadata["redaction_reason"] = "secret-prone-yaml-tag"
    if parsed.anchor is not None:
        metadata["anchor"] = parsed.anchor
    if parsed.alias is not None:
        metadata["alias"] = parsed.alias
    if merge_key:
        metadata["merge_key"] = True
    if not metadata:
        return
    pointer = json_pointer(pointer_segments)
    state.metadata().setdefault(pointer, {}).update(metadata)


def _strip_yaml_comment(line: str) -> str:
    output: list[str] = []
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote is not None:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            output.append(character)
            continue
        if character == "#" and (index == 0 or line[index - 1].isspace()):
            break
        output.append(character)
    return "".join(output)


def _yaml_first_token(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    if not stripped:
        return None, ""
    parts = stripped.split(None, 1)
    token = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    return token, rest


def _split_yaml_mapping_pair(text: str, line_number: int) -> tuple[str, str]:
    index = _yaml_mapping_colon_index(text)
    if index is None:
        raise YamlParseError("expected YAML mapping pair", line_number=line_number)
    key_text = text[:index].strip()
    if not key_text:
        raise YamlParseError("YAML mapping key is empty", line_number=line_number)
    key = _unquote_yaml_scalar(key_text)
    if not isinstance(key, str):
        key = str(key)
    return key, text[index + 1 :].strip()


def _looks_like_yaml_mapping_pair(text: str) -> bool:
    return _yaml_mapping_colon_index(text) is not None


def _yaml_mapping_colon_index(text: str) -> int | None:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            continue
        if character == ":":
            next_character = text[index + 1] if index + 1 < len(text) else ""
            if not next_character or next_character.isspace():
                return index
    return None


def _parse_yaml_inline_sequence(
    text: str,
    line_number: int,
    state: _YamlParseState,
) -> list[Any]:
    inner = text[1:-1].strip()
    if not inner:
        return []
    return [
        _parse_yaml_scalar(item, line_number, state).value
        for item in _split_yaml_inline_items(inner, line_number)
    ]


def _parse_yaml_inline_mapping(
    text: str,
    line_number: int,
    state: _YamlParseState,
) -> dict[str, Any]:
    inner = text[1:-1].strip()
    if not inner:
        return {}
    result: dict[str, Any] = {}
    for item in _split_yaml_inline_items(inner, line_number):
        key, value_text = _split_yaml_mapping_pair(item, line_number)
        if key in result:
            raise YamlParseError(
                f"duplicate YAML key: {key}",
                error_kind="duplicate-yaml-key",
                line_number=line_number,
            )
        result[key] = _parse_yaml_scalar(value_text, line_number, state).value
    return result


def _split_yaml_inline_items(text: str, line_number: int) -> tuple[str, ...]:
    items: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0
    for index, character in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            continue
        if character in "[{":
            depth += 1
            continue
        if character in "]}":
            depth -= 1
            if depth < 0:
                raise YamlParseError(
                    "malformed YAML inline collection",
                    line_number=line_number,
                )
            continue
        if character == "," and depth == 0:
            item = text[start:index].strip()
            if item:
                items.append(item)
            start = index + 1
    tail = text[start:].strip()
    if tail:
        items.append(tail)
    return tuple(items)


def _parse_yaml_plain_scalar(text: str) -> Any:
    unquoted = _unquote_yaml_scalar(text)
    if unquoted != text:
        return unquoted
    normalized = text.lower()
    if normalized in ("true", "false"):
        return normalized == "true"
    if normalized in ("null", "~"):
        return None
    if re.fullmatch(r"[-+]?[0-9]+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"[-+]?[0-9]+\.[0-9]+", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _unquote_yaml_scalar(text: str) -> Any:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ("'", '"'):
        body = stripped[1:-1]
        if stripped[0] == '"':
            try:
                return bytes(body, "utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                return body
        return body.replace("''", "'")
    return text


def _yaml_profile(
    relative_path: str,
    value: Any,
    *,
    document_count: int,
) -> str:
    path = PurePosixPath(relative_path)
    path_parts = tuple(_normalized_key(part) for part in path.parts)
    name = path.name
    normalized_name = _normalized_key(name)
    if ".github" in path.parts and "workflows" in path.parts:
        return "github_actions"
    if ".circleci" in path.parts and name in ("config.yml", "config.yaml"):
        return "circleci"
    if normalized_name in ("docker_compose.yml", "docker_compose.yaml") or name in (
        "docker-compose.yml",
        "docker-compose.yaml",
    ):
        return "docker_compose"
    if name == "Chart.yaml":
        return "helm_chart"
    if name == "values.yaml":
        return "helm_values"
    if name == "application.yml" or name == "application.yaml" or normalized_name.startswith("application_"):
        return "spring_boot"
    if "grafana" in path_parts:
        return "grafana"
    if "serena" in normalized_name or "serena" in path_parts:
        return "serena"
    if "arq" in normalized_name or "arq" in path_parts:
        return "arq_backup"
    documents = _yaml_documents(value, document_count=document_count)
    if _is_openapi_file_name(relative_path) or any(
        _is_openapi_document(document) for document in documents
    ):
        return "openapi"
    if any(_is_kubernetes_document(document) for document in documents):
        return "kubernetes"
    if any(isinstance(document, dict) and "pipeline" in document for document in documents):
        return "harness"
    if any(_is_docker_compose_document(document) for document in documents):
        return "docker_compose"
    if any(_is_grafana_document(document) for document in documents):
        return "grafana"
    return "generic_yaml"


def _tfjson_profile(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
) -> str | None:
    if format_name not in TFJSON_PROFILE_FORMATS or not isinstance(value, dict):
        return None
    path = PurePosixPath(relative_path)
    name = path.name
    normalized_name = _normalized_key(name)
    lower_path = relative_path.lower()
    if _is_openapi_file_name(relative_path) or _is_openapi_document(value):
        return "openapi_json"
    if lower_path.endswith(".tfvars.json") or normalized_name == "terraform.tfvars.json":
        return "terraform_tfvars_json"
    if lower_path.endswith(".tf.json"):
        return "terraform_json"
    if normalized_name == "package.json":
        return "package_json"
    if normalized_name in ("package_lock.json", "npm_shrinkwrap.json"):
        return "package_lock_json"
    if normalized_name == "tsconfig.json" or (
        normalized_name.startswith("tsconfig.")
        and normalized_name.endswith(".json")
    ):
        return "typescript_config"
    if normalized_name == "jsconfig.json":
        return "javascript_config"
    if normalized_name in ("angular.json", ".angular_cli.json"):
        return "angular_workspace"
    if normalized_name in ("project.json", "workspace.json", "nx.json"):
        return "workspace_config"
    if normalized_name == "nest_cli.json":
        return "nest_config"
    if normalized_name == "jest.config.json":
        return "jest_config"
    if normalized_name in ("babel.config.json", ".babelrc", ".babelrc.json"):
        return "babel_config"
    if normalized_name in (".eslintrc", ".eslintrc.json"):
        return "eslint_config"
    if normalized_name in (".prettierrc", ".prettierrc.json"):
        return "prettier_config"
    if normalized_name == "playwright.config.json":
        return "playwright_config"
    if _is_argocd_json_document(value):
        return "argocd_json"
    if _is_kubernetes_document(value):
        return "kubernetes_json"
    if _is_liquibase_json_document(value):
        return "liquibase_json"
    if _is_docker_compose_document(value):
        return "docker_compose_json"
    return None


def _tfjson_document_metadata(profile: str | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {"profile": profile}


def _tfjson_metadata_overrides(
    relative_path: str,
    value: Any,
    *,
    profile: str | None,
) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    if profile == "terraform_tfvars_json":
        for pointer, _path_value in _json_pointer_values(value):
            overrides.setdefault(pointer, {}).update(
                {
                    "profile": profile,
                    "redacted": True,
                    "redaction_reason": "tfvars-sensitive-by-default",
                }
            )
        return overrides
    if profile is not None:
        for pointer, path_value in _json_pointer_values(value):
            metadata = overrides.setdefault(pointer, {})
            metadata["profile"] = profile
            if _tfjson_pointer_is_redacted(pointer, path_value, value, profile=profile):
                metadata["redacted"] = True
                metadata.setdefault(
                    "redaction_reason",
                    _tfjson_redaction_reason(pointer, profile),
                )
    return overrides


def _tfjson_pointer_is_redacted(
    pointer: str,
    path_value: Any,
    root_value: Any,
    *,
    profile: str,
) -> bool:
    if _is_secret_pointer(pointer):
        return True
    if _looks_like_secret_scalar(path_value):
        return True
    segments = _pointer_segments(pointer)
    normalized_segments = tuple(_normalized_key(segment) for segment in segments)
    if profile == "package_json" and len(segments) >= 2 and segments[0] == "scripts":
        return _script_is_secret_prone(path_value)
    if profile == "kubernetes_json" and _json_pointer_is_kubernetes_secret_data(
        pointer,
        root_value,
    ):
        return True
    if profile == "openapi_json" and _openapi_pointer_is_redacted(pointer, path_value):
        return True
    if "securejsondata" in normalized_segments:
        return True
    return False


def _tfjson_redaction_reason(pointer: str, profile: str) -> str:
    if profile == "package_json" and pointer.startswith("/scripts/"):
        return "secret-prone-script"
    if profile == "kubernetes_json" and (
        "/data/" in pointer or "/stringData/" in pointer
    ):
        return "secret-prone-json-path"
    if _is_secret_pointer(pointer):
        return "secret-prone-key"
    return "secret-prone-config-context"


def _json_pointer_is_kubernetes_secret_data(pointer: str, root_value: Any) -> bool:
    segments = _pointer_segments(pointer)
    if "data" not in segments and "stringData" not in segments:
        return False
    return isinstance(root_value, dict) and root_value.get("kind") == "Secret"


def _json_pointer_values(value: Any) -> tuple[tuple[str, Any], ...]:
    result: list[tuple[str, Any]] = []

    def walk(current: Any, segments: tuple[str, ...]) -> None:
        if segments:
            result.append((json_pointer(segments), current))
        if isinstance(current, dict):
            for key, child in current.items():
                walk(child, (*segments, str(key)))
        elif isinstance(current, list):
            for index, child in enumerate(current):
                walk(child, (*segments, str(index)))

    walk(value, ())
    return tuple(result)


def _tfjson_profile_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str | None,
    content: str,
) -> tuple[RawObservation, ...]:
    if profile is None or not isinstance(value, dict):
        return ()
    observations: list[RawObservation] = [
        _profile_observation(
            "ecosystem.config_profile",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={
                "profile": profile,
                "profile_family": _tfjson_profile_family(profile),
                "source_document_key": config_document_key(relative_path),
            },
        )
    ]
    if profile == "package_json":
        observations.extend(
            _package_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                content=content,
            )
        )
    elif profile == "package_lock_json":
        observations.extend(
            _package_lock_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile in ("typescript_config", "javascript_config"):
        observations.extend(
            _typescript_config_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                content=content,
            )
        )
    elif profile == "angular_workspace":
        observations.extend(
            _angular_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                content=content,
            )
        )
    elif profile == "nest_config":
        observations.append(
            _profile_observation(
                "nest.config",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=_safe_selected_metadata(
                    value,
                    ("sourceRoot", "entryFile", "collection", "compilerOptions"),
                ),
            )
        )
    elif profile == "jest_config":
        observations.append(
            _profile_observation(
                "jest.config",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=_safe_selected_metadata(
                    value,
                    ("testEnvironment", "preset", "rootDir", "testMatch", "setupFilesAfterEnv"),
                ),
            )
        )
    elif profile == "playwright_config":
        observations.append(
            _playwright_observation(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
            )
        )
    elif profile == "openapi_json":
        observations.extend(
            _openapi_profile_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
            )
        )
    elif profile == "terraform_json":
        observations.extend(
            _terraform_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "terraform_tfvars_json":
        observations.extend(
            _terraform_tfvars_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "kubernetes_json":
        observations.extend(
            _kubernetes_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "argocd_json":
        observations.extend(
            _argocd_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "liquibase_json":
        observations.extend(
            _liquibase_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "docker_compose_json":
        observations.extend(
            _docker_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
            )
        )
    return tuple(observations)


def _tfjson_profile_family(profile: str) -> str:
    if profile.startswith("terraform_"):
        return "terraform"
    if profile in ("package_json", "package_lock_json"):
        return "npm"
    if profile in ("typescript_config", "javascript_config"):
        return "typescript"
    if profile == "openapi_json":
        return "openapi"
    if profile.endswith("_json"):
        return profile.removesuffix("_json")
    return profile


def _profile_observation(
    kind: str,
    relative_path: str,
    *,
    profile: str,
    format_name: str,
    confidence: str,
    metadata: dict[str, Any],
    name: str | None = None,
    target: str | None = None,
    source_suffix: str | None = None,
) -> RawObservation:
    full_metadata = {
        "format": format_name,
        "profile": profile,
        **metadata,
    }
    source_segment = source_suffix or kind.replace(".", "-")
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{source_segment}",
        path=relative_path,
        name=name,
        target=target,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=full_metadata,
    )


def _extract_python_requirements_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    requirement_count = 0
    reference_count = 0
    redaction_count = 0
    parse_error_count = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = _python_requirement_line_without_comment(line)
        if not stripped:
            continue
        if stripped.startswith(("-r ", "--requirement ")):
            path_value = stripped.split(maxsplit=1)[1].strip()
            refs, errors = _python_requirement_file_reference_observations(
                relative_path,
                path_value,
                line_number=line_number,
                reference_kind="include_file",
            )
            observations.extend(refs)
            observations.extend(errors)
            reference_count += len(refs)
            parse_error_count += len(errors)
            continue
        if stripped.startswith(("-c ", "--constraint ")):
            path_value = stripped.split(maxsplit=1)[1].strip()
            refs, errors = _python_requirement_file_reference_observations(
                relative_path,
                path_value,
                line_number=line_number,
                reference_kind="constraint_file",
            )
            observations.extend(refs)
            observations.extend(errors)
            reference_count += len(refs)
            parse_error_count += len(errors)
            continue
        if stripped.startswith(("--index-url ", "--extra-index-url ", "--find-links ")):
            option, value = stripped.split(maxsplit=1)
            refs, redactions = _python_requirement_url_reference_observations(
                relative_path,
                value.strip(),
                line_number=line_number,
                reference_kind=option.lstrip("-").replace("-", "_"),
                redact_all=True,
            )
            observations.extend(refs)
            observations.extend(redactions)
            reference_count += len(refs)
            redaction_count += len(redactions)
            continue
        if stripped.startswith("--hash=") or stripped.startswith("--"):
            continue
        requirement = _parse_python_requirement_line(stripped, line_number=line_number)
        if requirement is None:
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="malformed-python-requirement",
                    message="requirement line is not statically supported",
                    start_line=line_number,
                    source_suffix=f"requirement:{line_number}",
                )
            )
            parse_error_count += 1
            continue
        if requirement_count >= PYTHON_MAX_REQUIREMENTS:
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="python-requirements-limit",
                    message="requirements file exceeds dependency limit",
                    start_line=line_number,
                    source_suffix=f"requirement-limit:{line_number}",
                )
            )
            parse_error_count += 1
            break
        observations.append(_python_requirement_observation(relative_path, requirement))
        requirement_count += 1
        refs, redactions = _python_requirement_source_observations(
            relative_path,
            requirement,
        )
        observations.extend(refs)
        observations.extend(redactions)
        reference_count += len(refs)
        redaction_count += len(redactions)
    package_file = _python_package_file_observation(
        relative_path,
        requirement_count=requirement_count,
        reference_count=reference_count,
        redaction_count=redaction_count,
        parse_error_count=parse_error_count,
    )
    return (package_file, *observations)


def _python_package_file_observation(
    relative_path: str,
    *,
    requirement_count: int,
    reference_count: int,
    redaction_count: int,
    parse_error_count: int,
) -> RawObservation:
    return _profile_observation(
        "python.package_file",
        relative_path,
        profile=PYTHON_REQUIREMENTS_PROFILE,
        format_name=PYTHON_REQUIREMENTS_FORMAT,
        confidence="extracted",
        metadata={
            "file_family": _python_requirement_file_family(relative_path),
            "source_format": PYTHON_REQUIREMENTS_FORMAT,
            "requirement_count": requirement_count,
            "reference_count": reference_count,
            "redaction_count": redaction_count,
            "parse_error_count": parse_error_count,
            "raw_profile_only": True,
        },
        name=PurePosixPath(relative_path).name,
        source_suffix="python-package-file",
    )


def _python_requirement_line_without_comment(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    if " #" in stripped:
        return stripped.split(" #", 1)[0].strip()
    return stripped


def _parse_python_requirement_line(
    stripped: str,
    *,
    line_number: int | None,
) -> _PythonRequirement | None:
    editable = False
    value = stripped
    if value.startswith(("-e ", "--editable ")):
        editable = True
        value = value.split(maxsplit=1)[1].strip()
    package_part: str | None = None
    source: str | None = None
    if " @ " in value:
        package_part, source = value.split(" @ ", 1)
    elif _python_requirement_is_direct_source(value) or editable:
        source = value
        package_part = _python_requirement_package_from_source(value)
    else:
        package_part = value
    if package_part is None:
        return None
    marker: str | None = None
    if ";" in package_part:
        package_part, marker = (item.strip() for item in package_part.split(";", 1))
    match = PYTHON_REQUIREMENT_NAME_PATTERN.match(package_part.strip())
    if match is None:
        return None
    package_name = match.group("name")
    specifier = match.group("specifier").strip()
    if specifier and not specifier.startswith(("=", "!", "~", ">", "<")):
        return None
    extras = _python_requirement_extras(match.group("extras"))
    if source is not None and ";" in source:
        source, source_marker = (item.strip() for item in source.split(";", 1))
        marker = marker or source_marker
    return _PythonRequirement(
        package_name=package_name,
        specifier=specifier or None,
        extras=extras,
        environment_marker=marker,
        source=source,
        editable=editable,
        direct_url=_python_requirement_is_direct_source(source or ""),
        local_path=_python_requirement_is_local_path(source or ""),
        line_number=line_number,
        raw_kind="requirement",
    )


def _python_requirement_extras(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    inner = value.strip()[1:-1]
    return tuple(sorted(item.strip() for item in inner.split(",") if item.strip()))


def _python_requirement_package_from_source(value: str) -> str | None:
    if "#egg=" in value:
        egg = value.split("#egg=", 1)[1].split("&", 1)[0].strip()
        if PYTHON_REQUIREMENT_NAME_PATTERN.match(egg):
            return egg
    name = PurePosixPath(value.rstrip("/")).name
    if name.endswith((".git", ".zip", ".tar.gz", ".tgz", ".whl")):
        name = name.split(".", 1)[0]
    if PYTHON_REQUIREMENT_NAME_PATTERN.match(name):
        return name
    return None


def _python_requirement_observation(
    relative_path: str,
    requirement: _PythonRequirement,
    *,
    dependency_group: str = "requirements",
    source_suffix_prefix: str = "python-requirement",
) -> RawObservation:
    metadata: dict[str, Any] = {
        "profile": "python",
        "file_family": _python_requirement_file_family(relative_path),
        "source_format": PYTHON_REQUIREMENTS_FORMAT,
        "dependency_group": dependency_group,
        "editable": requirement.editable,
        "direct_url": requirement.direct_url,
        "local_path": requirement.local_path,
        "not_fetched": requirement.direct_url,
        "raw_profile_only": True,
    }
    if requirement.line_number is not None:
        metadata["line"] = requirement.line_number
    if requirement.package_name is not None:
        metadata["package_name"] = _python_bounded_string(requirement.package_name)
    if requirement.specifier is not None:
        metadata["specifier"] = _python_bounded_string(requirement.specifier)
    if requirement.extras:
        metadata["extras"] = list(requirement.extras)
    if requirement.environment_marker is not None:
        metadata["environment_marker"] = _python_bounded_string(
            requirement.environment_marker
        )
    if requirement.source is not None:
        metadata.update(_python_dependency_source_metadata(requirement.source))
    return RawObservation(
        kind="python.requirement",
        source_id=(
            f"{relative_path}#{source_suffix_prefix}:"
            f"{requirement.line_number or 'document'}:"
            f"{_python_slug(requirement.package_name or 'source')}"
        ),
        path=relative_path,
        start_line=requirement.line_number,
        end_line=requirement.line_number,
        name=requirement.package_name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _python_requirement_source_observations(
    relative_path: str,
    requirement: _PythonRequirement,
) -> tuple[list[RawObservation], list[RawObservation]]:
    if requirement.source is None:
        return [], []
    if requirement.local_path:
        refs, errors = _python_requirement_file_reference_observations(
            relative_path,
            _python_requirement_local_path_value(requirement.source),
            line_number=requirement.line_number,
            reference_kind="local_path",
        )
        return refs, errors
    return _python_requirement_url_reference_observations(
        relative_path,
        requirement.source,
        line_number=requirement.line_number,
        reference_kind="direct_url",
        redact_all=False,
    )


def _python_requirement_file_reference_observations(
    relative_path: str,
    value: str,
    *,
    line_number: int | None,
    reference_kind: str,
) -> tuple[list[RawObservation], list[RawObservation]]:
    target = _python_requirement_local_path_target(relative_path, value)
    if target is None:
        return [], [
            _python_parse_error_observation(
                relative_path,
                error_kind="repo-escaping-requirement-reference",
                message="requirement file reference escapes repository root",
                start_line=line_number,
                source_suffix=f"requirement-reference:{reference_kind}:{line_number}",
            )
        ]
    return [
        _python_reference_observation(
            relative_path,
            reference_kind=reference_kind,
            target=target,
            line_number=line_number,
            metadata={
                "resolution": "local",
                "not_fetched": False,
                "redacted": False,
            },
        )
    ], []


def _python_requirement_url_reference_observations(
    relative_path: str,
    value: str,
    *,
    line_number: int | None,
    reference_kind: str,
    redact_all: bool,
) -> tuple[list[RawObservation], list[RawObservation]]:
    redacted = redact_all or _url_has_credentials(value)
    if redacted:
        target = external_key("url", f"redacted-python-{reference_kind}")
    elif _is_url(value) or _python_requirement_is_vcs_source(value):
        target = external_url_key(value)
    else:
        target = external_key("python.source", "unknown-direct-source")
    metadata = {
        "not_fetched": True,
        "redacted": redacted,
        **_python_dependency_source_metadata(value),
    }
    if redacted:
        metadata["redaction_reason"] = (
            "credentialed-url" if _url_has_credentials(value) else "index-url"
        )
    references = [
        _python_reference_observation(
            relative_path,
            reference_kind=reference_kind,
            target=target,
            line_number=line_number,
            metadata=metadata,
        )
    ]
    redactions = []
    if redacted:
        redactions.append(
            _python_redaction_observation(
                relative_path,
                redaction_kind=reference_kind,
                reason=metadata["redaction_reason"],
                line_number=line_number,
            )
        )
    return references, redactions


def _python_reference_observation(
    relative_path: str,
    *,
    reference_kind: str,
    target: str,
    line_number: int | None,
    metadata: dict[str, Any],
) -> RawObservation:
    return RawObservation(
        kind="python.reference",
        source_id=f"{relative_path}#python-reference:{reference_kind}:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=reference_kind,
        target=target,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": PYTHON_REQUIREMENTS_FORMAT,
            "reference_kind": reference_kind,
            "raw_profile_only": True,
            **metadata,
        },
    )


def _python_pyproject_metadata_overrides(
    value: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for pointer_segments, item in _python_pyproject_walk(value):
        pointer = json_pointer(pointer_segments)
        if _python_pyproject_value_requires_redaction(pointer_segments, item):
            overrides[pointer] = {
                "redacted": True,
                "redaction_reason": "python-profile-redaction",
            }
            if pointer_segments:
                parent_pointer = json_pointer(pointer_segments[:-1])
                if parent_pointer:
                    overrides[parent_pointer] = {
                        "redacted": True,
                        "redaction_reason": "python-profile-redaction",
                    }
    return overrides


def _python_pyproject_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    project = value.get("project")
    if isinstance(project, dict):
        metadata: dict[str, Any] = {
            "source_format": "pyproject.toml",
            "raw_profile_only": True,
            "dependency_count": _python_sequence_count(project.get("dependencies")),
        }
        name_summary = _safe_value_summary(project.get("name"))
        if isinstance(name_summary, str) and not _is_secret_key(name_summary):
            metadata["project_name"] = _python_bounded_string(name_summary)
        version_summary = _safe_value_summary(project.get("version"))
        if isinstance(version_summary, str):
            metadata["project_version"] = _python_bounded_string(version_summary)
        dynamic = project.get("dynamic")
        if isinstance(dynamic, list):
            metadata["dynamic_metadata"] = [
                _python_bounded_string(str(item))
                for item in dynamic
                if isinstance(item, str) and not _is_secret_key(item)
            ]
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            metadata["optional_dependency_groups"] = sorted(str(key) for key in optional)
        observations.append(
            _profile_observation(
                "python.pyproject",
                relative_path,
                profile="python",
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                name=metadata.get("project_name", "pyproject.toml"),
                source_suffix="python-pyproject",
            )
        )
        observations.extend(
            _python_requirement_observations_from_values(
                relative_path,
                project.get("dependencies"),
                dependency_group="project.dependencies",
                source_suffix_prefix="python-pyproject-dependency",
            )
        )
        if isinstance(optional, dict):
            for group in sorted(str(key) for key in optional):
                observations.append(
                    _profile_observation(
                        "python.dependency_group",
                        relative_path,
                        profile="python",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            "source_format": "pyproject.toml",
                            "dependency_group": f"project.optional-dependencies.{group}",
                            "optional_group": group,
                            "dependency_count": _python_sequence_count(
                                optional.get(group)
                            ),
                            "raw_profile_only": True,
                        },
                        name=group,
                        source_suffix=f"python-dependency-group:{group}",
                    )
                )
                observations.extend(
                    _python_requirement_observations_from_values(
                        relative_path,
                        optional.get(group),
                        dependency_group=f"project.optional-dependencies.{group}",
                        source_suffix_prefix=f"python-pyproject-optional:{group}",
                    )
                )
        for section_name in ("scripts", "gui-scripts"):
            observations.extend(
                _python_entry_point_observations(
                    relative_path,
                    project.get(section_name),
                    entry_point_group=f"project.{section_name}",
                    format_name=format_name,
                    confidence=confidence,
                )
            )
        entry_points = project.get("entry-points")
        if isinstance(entry_points, dict):
            for group in sorted(str(key) for key in entry_points):
                observations.extend(
                    _python_entry_point_observations(
                        relative_path,
                        entry_points.get(group),
                        entry_point_group=f"project.entry-points.{group}",
                        format_name=format_name,
                        confidence=confidence,
                    )
                )
    build_system = value.get("build-system")
    if isinstance(build_system, dict):
        requires = build_system.get("requires")
        metadata = {
            "source_format": "pyproject.toml",
            "requires_count": _python_sequence_count(requires),
            "raw_profile_only": True,
        }
        backend_summary = _safe_value_summary(build_system.get("build-backend"))
        if isinstance(backend_summary, str):
            metadata["build_backend"] = _python_bounded_string(backend_summary)
        observations.append(
            _profile_observation(
                "python.build_system",
                relative_path,
                profile="python",
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                name=metadata.get("build_backend", "build-system"),
                source_suffix="python-build-system",
            )
        )
        observations.extend(
            _python_requirement_observations_from_values(
                relative_path,
                requires,
                dependency_group="build-system.requires",
                source_suffix_prefix="python-build-system-requirement",
            )
        )
    tool = value.get("tool")
    if isinstance(tool, dict):
        for tool_name in sorted(str(key) for key in tool):
            if len(observations) >= PYTHON_MAX_REQUIREMENTS:
                break
            observations.append(
                _profile_observation(
                    "python.tool_config",
                    relative_path,
                    profile="python",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        "source_format": "pyproject.toml",
                        "tool_name": _python_bounded_string(tool_name),
                        "tool_section": f"tool.{tool_name}",
                        "raw_profile_only": True,
                    },
                    name=tool_name,
                    source_suffix=f"python-tool-config:{tool_name}",
                )
            )
    groups = value.get("dependency-groups")
    if isinstance(groups, dict):
        for group in sorted(str(key) for key in groups):
            observations.extend(
                _python_requirement_observations_from_values(
                    relative_path,
                    groups.get(group),
                    dependency_group=f"dependency-groups.{group}",
                    source_suffix_prefix=f"python-dependency-group:{group}",
                )
            )
    return tuple(observations)


def _python_requirement_observations_from_values(
    relative_path: str,
    value: Any,
    *,
    dependency_group: str,
    source_suffix_prefix: str,
) -> list[RawObservation]:
    if not isinstance(value, list):
        return []
    observations: list[RawObservation] = []
    for index, item in enumerate(value[:PYTHON_MAX_REQUIREMENTS]):
        if not isinstance(item, str):
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="unsupported-pyproject-dependency",
                    message="dependency entry is not a string",
                    start_line=None,
                    source_suffix=f"{source_suffix_prefix}:{index}:unsupported",
                )
            )
            continue
        requirement = _parse_python_requirement_line(item, line_number=None)
        if requirement is None:
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="malformed-pyproject-dependency",
                    message="dependency entry is not statically supported",
                    start_line=None,
                    source_suffix=f"{source_suffix_prefix}:{index}:malformed",
                )
            )
            continue
        observations.append(
            _python_requirement_observation(
                relative_path,
                requirement,
                dependency_group=dependency_group,
                source_suffix_prefix=f"{source_suffix_prefix}:{index}",
            )
        )
        refs, redactions = _python_requirement_source_observations(
            relative_path,
            requirement,
        )
        observations.extend(refs)
        observations.extend(redactions)
    return observations


def _python_entry_point_observations(
    relative_path: str,
    value: Any,
    *,
    entry_point_group: str,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    if not isinstance(value, dict):
        return []
    observations = []
    for entry_point_name in sorted(str(key) for key in value):
        target_summary = _safe_value_summary(value.get(entry_point_name))
        metadata = {
            "source_format": "pyproject.toml",
            "entry_point_group": entry_point_group,
            "entry_point_name": _python_bounded_string(entry_point_name),
            "raw_profile_only": True,
        }
        if isinstance(target_summary, str) and not _looks_like_secret_scalar(
            target_summary
        ):
            metadata["entry_point_target"] = _python_bounded_string(target_summary)
        observations.append(
            _profile_observation(
                "python.entry_point",
                relative_path,
                profile="python",
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                name=entry_point_name,
                source_suffix=f"python-entry-point:{entry_point_group}:{entry_point_name}",
            )
        )
    return observations


def _python_parse_error_observation(
    relative_path: str,
    *,
    error_kind: str,
    message: str,
    start_line: int | None,
    source_suffix: str,
) -> RawObservation:
    return RawObservation(
        kind="python.parse_error",
        source_id=f"{relative_path}#python-parse-error:{source_suffix}",
        path=relative_path,
        start_line=start_line,
        end_line=start_line,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "pyproject.toml"
            if _is_pyproject_file_name(relative_path)
            else PYTHON_REQUIREMENTS_FORMAT,
            "error_kind": error_kind,
            "message_summary": _safe_error_message(None, message),
            "recovered": False,
            "raw_profile_only": True,
        },
    )


def _python_redaction_observation(
    relative_path: str,
    *,
    redaction_kind: str,
    reason: str,
    line_number: int | None,
) -> RawObservation:
    return RawObservation(
        kind="python.redaction",
        source_id=f"{relative_path}#python-redaction:{redaction_kind}:{line_number or 'document'}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "pyproject.toml"
            if _is_pyproject_file_name(relative_path)
            else PYTHON_REQUIREMENTS_FORMAT,
            "redaction_kind": redaction_kind,
            "redaction_reason": reason,
            "redacted": True,
            "raw_profile_only": True,
        },
    )


def _python_dependency_source_metadata(value: str) -> dict[str, Any]:
    parsed = urlsplit(value)
    credentialed = _url_has_credentials(value)
    metadata: dict[str, Any] = {
        "source_present": True,
        "source_length": len(value),
        "source_sha256": _stable_text_sha256(value),
    }
    if parsed.scheme:
        metadata["source_scheme"] = _python_bounded_string(parsed.scheme)
    if parsed.hostname and not credentialed:
        metadata["source_host"] = _python_bounded_string(parsed.hostname)
    if credentialed:
        metadata["redacted"] = True
        metadata["redaction_reason"] = "credentialed-url"
    return metadata


def _python_requirement_file_family(relative_path: str) -> str:
    name = PurePosixPath(relative_path).name
    if name == "requirements.txt":
        return "requirements.txt"
    if name == "dev-requirements.txt":
        return "dev-requirements.txt"
    if name == "test-requirements.txt":
        return "test-requirements.txt"
    if name.startswith("requirements-") and name.endswith(".txt"):
        return "requirements-variant"
    return "requirements"


def _python_requirement_is_direct_source(value: str) -> bool:
    return (
        _is_url(value)
        or value.startswith("file:")
        or _python_requirement_is_vcs_source(value)
    )


def _python_requirement_is_vcs_source(value: str) -> bool:
    return value.startswith(("git+", "hg+", "svn+", "bzr+"))


def _python_requirement_is_local_path(value: str) -> bool:
    if value.startswith("file:"):
        return not _is_url(value.removeprefix("file:"))
    return value.startswith(("./", "../", "/")) and not _is_url(value)


def _python_requirement_local_path_value(value: str) -> str:
    return value.removeprefix("file:")


def _python_requirement_local_path_target(
    relative_path: str,
    value: str,
) -> str | None:
    local_value = _python_requirement_local_path_value(value)
    if local_value.startswith("/"):
        return None
    if local_value.startswith(("./", "../")):
        resolved = _resolve_repo_path(relative_path, local_value)
    else:
        resolved = _normalize_repo_path(local_value)
    if resolved is None:
        return None
    return file_key(resolved)


def _python_pyproject_walk(
    value: Any,
    pointer_segments: tuple[str, ...] = (),
) -> tuple[tuple[tuple[str, ...], Any], ...]:
    items: list[tuple[tuple[str, ...], Any]] = [(pointer_segments, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            items.extend(_python_pyproject_walk(item, (*pointer_segments, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            items.extend(_python_pyproject_walk(item, (*pointer_segments, str(index))))
    return tuple(items)


def _python_pyproject_value_requires_redaction(
    pointer_segments: tuple[str, ...],
    value: Any,
) -> bool:
    if any(_is_secret_key(segment) for segment in pointer_segments):
        return True
    if isinstance(value, str):
        if (
            _url_has_credentials(value)
            or _python_value_has_credentialed_url_fragment(value)
            or _looks_like_secret_scalar(value)
        ):
            return True
        if pointer_segments and _normalized_key(pointer_segments[-1]) in (
            "index_url",
            "extra_index_url",
            "url",
        ):
            return _is_url(value)
    return False


def _python_value_has_credentialed_url_fragment(value: str) -> bool:
    fragments = re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s,]+", value)
    return any(_url_has_credentials(fragment.strip("\"'")) for fragment in fragments)


def _python_sequence_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _python_bounded_string(value: str) -> str:
    if len(value) <= PYTHON_MAX_METADATA_STRING:
        return value
    return f"<string:{len(value)}>"


def _python_slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "-", value).strip("-") or "unknown"


def _is_python_requirements_file_name(relative_path: str) -> bool:
    return bool(PYTHON_REQUIREMENTS_NAME_PATTERN.match(PurePosixPath(relative_path).name))


def _is_pyproject_file_name(relative_path: str) -> bool:
    return PurePosixPath(relative_path).name == "pyproject.toml"


def _package_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    content: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    declared_sections = sorted(
        key
        for key in (
            "scripts",
            *TFJSON_PACKAGE_DEPENDENCY_GROUPS,
            "workspaces",
            "bin",
            "exports",
            "imports",
            "engines",
        )
        if key in value
    )
    package_metadata: dict[str, Any] = {
        "declared_sections": declared_sections,
        "source_document_key": config_document_key(relative_path),
    }
    for source_key, target_key in (
        ("name", "package_name"),
        ("version", "package_version"),
        ("type", "package_type"),
        ("packageManager", "package_manager"),
    ):
        summary = _safe_value_summary(value.get(source_key))
        if isinstance(summary, str):
            package_metadata[target_key] = summary
    if isinstance(value.get("private"), bool):
        package_metadata["private"] = value["private"]
    observations.append(
        _profile_observation(
            "npm.package",
            relative_path,
            profile="package_json",
            format_name=format_name,
            confidence=confidence,
            metadata=package_metadata,
            name=str(value.get("name") or "package.json"),
            source_suffix="npm-package",
        )
    )
    scripts = value.get("scripts")
    if isinstance(scripts, dict):
        for script_name in sorted(str(key) for key in scripts):
            script_value = scripts.get(script_name)
            if not isinstance(script_value, str):
                continue
            redacted = _script_is_secret_prone(script_value)
            metadata = {
                "script_name": script_name,
                "redacted": redacted,
                "source_path_key": config_path_key(
                    relative_path,
                    json_pointer(("scripts", script_name)),
                ),
            }
            if redacted:
                metadata["redaction_reason"] = "secret-prone-script"
                metadata["command_summary"] = "<redacted-script>"
            else:
                metadata["command_summary"] = _script_command_summary(script_value)
            observations.append(
                _profile_observation(
                    "npm.script",
                    relative_path,
                    profile="package_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=script_name,
                    source_suffix=f"npm-script:{script_name}",
                )
            )
    observations.extend(
        _package_dependency_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    observations.extend(
        _package_framework_hints(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    observations.extend(
        _package_reference_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    return observations


def _package_dependency_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for group in TFJSON_PACKAGE_DEPENDENCY_GROUPS:
        dependencies = value.get(group)
        if not isinstance(dependencies, dict):
            continue
        for dependency_name in sorted(str(key) for key in dependencies):
            version_summary = _safe_value_summary(dependencies.get(dependency_name))
            metadata = {
                "dependency_name": dependency_name,
                "dependency_group": group,
                "target_reference": external_key("npm.package", dependency_name),
                "source_path_key": config_path_key(
                    relative_path,
                    json_pointer((group, dependency_name)),
                ),
            }
            if isinstance(version_summary, str):
                metadata["version_constraint"] = version_summary
            observations.append(
                _profile_observation(
                    "npm.dependency",
                    relative_path,
                    profile="package_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=dependency_name,
                    target=external_key("npm.package", dependency_name),
                    source_suffix=f"npm-dependency:{group}:{dependency_name}",
                )
            )
    return observations


def _package_framework_hints(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    dependency_names: set[str] = set()
    for group in TFJSON_PACKAGE_DEPENDENCY_GROUPS:
        dependencies = value.get(group)
        if isinstance(dependencies, dict):
            dependency_names.update(str(key) for key in dependencies)
    for dependency_name in sorted(dependency_names):
        framework = TFJSON_FRAMEWORK_DEPENDENCY_HINTS.get(dependency_name)
        if framework is None:
            continue
        observations.append(
            _profile_observation(
                "ecosystem.framework_hint",
                relative_path,
                profile="package_json",
                format_name=format_name,
                confidence="heuristic",
                metadata={
                    "framework": framework,
                    "hint_reason": "package-dependency",
                    "dependency_name": dependency_name,
                },
                name=framework,
                source_suffix=f"ecosystem-framework:{framework}:{dependency_name}",
            )
        )
    scripts = value.get("scripts")
    if isinstance(scripts, dict):
        for script_name, script_value in sorted((str(k), v) for k, v in scripts.items()):
            if not isinstance(script_value, str) or _script_is_secret_prone(script_value):
                continue
            command = _script_command_summary(script_value)
            if command in ("jest", "next", "ng", "nest", "playwright"):
                observations.append(
                    _profile_observation(
                        "ecosystem.framework_hint",
                        relative_path,
                        profile="package_json",
                        format_name=format_name,
                        confidence="heuristic",
                        metadata={
                            "framework": command,
                            "hint_reason": "package-script",
                            "script_name": script_name,
                        },
                        name=command,
                        source_suffix=f"ecosystem-framework:script:{script_name}",
                    )
                )
    return observations


def _package_reference_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for pointer, raw_value in (
        ("/repository/url", value.get("repository", {}).get("url") if isinstance(value.get("repository"), dict) else value.get("repository")),
        ("/homepage", value.get("homepage")),
        ("/bugs/url", value.get("bugs", {}).get("url") if isinstance(value.get("bugs"), dict) else value.get("bugs")),
    ):
        if not isinstance(raw_value, str) or not _is_url(raw_value):
            continue
        observations.append(
            _profile_observation(
                "ecosystem.reference",
                relative_path,
                profile="package_json",
                format_name=format_name,
                confidence="heuristic",
                metadata={
                    "reference_kind": "external.url",
                    "pointer": pointer,
                    "resolution_reason": "package-url-field",
                    "raw_value_summary": _safe_value_summary(raw_value),
                },
                target=external_url_key(raw_value),
                source_suffix=f"ecosystem-reference:{pointer}",
            )
        )
    return observations


def _package_lock_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    package_count = 0
    packages = value.get("packages")
    dependencies = value.get("dependencies")
    if isinstance(packages, dict):
        package_count = len(packages)
    elif isinstance(dependencies, dict):
        package_count = len(dependencies)
    return [
        _profile_observation(
            "ecosystem.package",
            relative_path,
            profile="package_lock_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "lockfile": True,
                "lockfile_version": _safe_value_summary(value.get("lockfileVersion")),
                "package_count": package_count,
            },
            source_suffix="ecosystem-package-lock",
        )
    ]


def _typescript_config_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    content: str,
) -> list[RawObservation]:
    compiler_options = value.get("compilerOptions")
    metadata = {
        "source_document_key": config_document_key(relative_path),
        "has_compiler_options": isinstance(compiler_options, dict),
        "extends": _safe_value_summary(value.get("extends")),
        "jsx": (
            _safe_value_summary(compiler_options.get("jsx"))
            if isinstance(compiler_options, dict)
            else None
        ),
    }
    path_aliases = compiler_options.get("paths") if isinstance(compiler_options, dict) else None
    if isinstance(path_aliases, dict):
        metadata["path_alias_count"] = len(path_aliases)
        metadata["path_aliases"] = sorted(str(key) for key in path_aliases)[:20]
    references = value.get("references")
    if isinstance(references, list):
        metadata["project_reference_count"] = len(references)
    observations = [
        _profile_observation(
            "typescript.config",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={key: item for key, item in metadata.items() if item is not None},
            source_suffix="typescript-config",
        )
    ]
    if isinstance(value.get("extends"), str):
        observations.append(
            _typescript_reference_observation(
                relative_path,
                value["extends"],
                pointer="/extends",
                reference_kind="extends",
                format_name=format_name,
                confidence="heuristic",
                profile=profile,
                content=content,
            )
        )
    if isinstance(references, list):
        for index, item in enumerate(references):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                observations.append(
                    _typescript_reference_observation(
                        relative_path,
                        item["path"],
                        pointer=f"/references/{index}/path",
                        reference_kind="project-reference",
                        format_name=format_name,
                        confidence="heuristic",
                        profile=profile,
                        content=content,
                    )
                )
    return observations


def _typescript_reference_observation(
    relative_path: str,
    value: str,
    *,
    pointer: str,
    reference_kind: str,
    format_name: str,
    confidence: str,
    profile: str,
    content: str,
) -> RawObservation:
    reference = _file_reference(relative_path, value, redacted=False)
    line_number = _line_for_pointer(content, pointer)
    return RawObservation(
        kind="typescript.reference",
        source_id=f"{relative_path}#typescript-reference:{pointer}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=pointer,
        target=reference["target"],
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "format": format_name,
            "profile": profile,
            "pointer": pointer,
            "reference_kind": reference_kind,
            "resolution_reason": reference["reason"],
            "raw_value_summary": _safe_value_summary(value),
            "source_document_key": config_document_key(relative_path),
        },
    )


def _angular_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    content: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    projects = value.get("projects")
    if not isinstance(projects, dict):
        return observations
    for project_name in sorted(str(key) for key in projects):
        project = projects.get(project_name)
        if not isinstance(project, dict):
            continue
        metadata = {
            "project_name": project_name,
            "root": _safe_value_summary(project.get("root")),
            "source_root": _safe_value_summary(project.get("sourceRoot")),
            "source_path_key": config_path_key(
                relative_path,
                json_pointer(("projects", project_name)),
            ),
        }
        observations.append(
            _profile_observation(
                "angular.project",
                relative_path,
                profile="angular_workspace",
                format_name=format_name,
                confidence=confidence,
                metadata={key: item for key, item in metadata.items() if item is not None},
                name=project_name,
                source_suffix=f"angular-project:{project_name}",
            )
        )
        targets = project.get("architect") or project.get("targets")
        if not isinstance(targets, dict):
            continue
        for target_name in sorted(str(key) for key in targets):
            target_value = targets.get(target_name)
            builder = (
                target_value.get("builder")
                if isinstance(target_value, dict)
                else None
            )
            observations.append(
                _profile_observation(
                    "angular.target",
                    relative_path,
                    profile="angular_workspace",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        "project_name": project_name,
                        "target_name": target_name,
                        "builder": _safe_value_summary(builder),
                        "source_path_key": config_path_key(
                            relative_path,
                            json_pointer(("projects", project_name, "architect", target_name)),
                        ),
                    },
                    name=f"{project_name}:{target_name}",
                    source_suffix=f"angular-target:{project_name}:{target_name}",
                )
            )
    return observations


def _playwright_observation(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
) -> RawObservation:
    project_names: list[str] = []
    projects = value.get("projects")
    if isinstance(projects, list):
        for project in projects:
            if isinstance(project, dict):
                name = _safe_value_summary(project.get("name"))
                if isinstance(name, str):
                    project_names.append(name)
    return _profile_observation(
        "playwright.config",
        relative_path,
        profile=profile,
        format_name=format_name,
        confidence=confidence,
        metadata={
            "test_dir": _safe_value_summary(value.get("testDir")),
            "project_names": project_names,
            "project_count": len(project_names),
        },
        source_suffix="playwright-config",
    )


def _openapi_profile_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    document_count: int = 1,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for document_index, document in enumerate(
        _yaml_documents(value, document_count=document_count)
        if format_name == YAML_FORMAT
        else (value,)
    ):
        document_pointer_prefix = (
            ("documents", str(document_index))
            if format_name == YAML_FORMAT and document_count > 1
            else ()
        )
        if not isinstance(document, dict) or not _is_openapi_document(document):
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="unsupported-openapi-document",
                    message="OpenAPI profile file lacks a supported OpenAPI/Swagger object",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        spec_metadata = _openapi_spec_metadata(document)
        if spec_metadata is None:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="unsupported-openapi-version",
                    message="OpenAPI/Swagger version is unsupported",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        paths = document.get("paths")
        paths_dict = paths if isinstance(paths, dict) else {}
        if len(paths_dict) > OPENAPI_MAX_PATHS:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-path-limit",
                    message="OpenAPI path count exceeds OPENAPI1 limit",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        operation_count = _openapi_operation_count(paths_dict)
        if operation_count > OPENAPI_MAX_OPERATIONS:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-operation-limit",
                    message="OpenAPI operation count exceeds OPENAPI1 limit",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        components = _openapi_components(document, spec_metadata["spec_family"])
        schema_count = len(components.get("schemas", {}))
        if schema_count > OPENAPI_MAX_SCHEMAS:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-schema-limit",
                    message="OpenAPI schema count exceeds OPENAPI1 limit",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        observations.append(
            _profile_observation(
                "openapi.document",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    **spec_metadata,
                    "source_document_key": config_document_key(relative_path),
                    "document_index": (
                        document_index if document_count > 1 else None
                    ),
                    "path_count": len(paths_dict),
                    "operation_count": operation_count,
                    "schema_count": schema_count,
                    "server_count": _openapi_server_count(document, spec_metadata["spec_family"]),
                    "raw_profile_only": True,
                },
                source_suffix=_openapi_source_suffix(
                    "document", json_pointer(document_pointer_prefix)
                ),
            )
        )
        observations.extend(
            _openapi_info_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_server_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_path_operation_observations(
                relative_path,
                paths_dict,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=(*document_pointer_prefix, "paths"),
            )
        )
        observations.extend(
            _openapi_component_observations(
                relative_path,
                components,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_reference_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_example_and_redaction_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
    return observations


def _openapi_spec_metadata(value: dict[str, Any]) -> dict[str, str] | None:
    openapi_version = value.get("openapi")
    if isinstance(openapi_version, str) and openapi_version.startswith("3."):
        return {"spec_family": "openapi3", "spec_version": openapi_version}
    swagger_version = value.get("swagger")
    if str(swagger_version) == "2.0":
        return {"spec_family": "swagger2", "spec_version": "2.0"}
    return None


def _openapi_info_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    info = value.get("info")
    if not isinstance(info, dict):
        return []
    description = info.get("description")
    metadata: dict[str, Any] = {
        **spec_metadata,
        "source_document_key": config_document_key(relative_path),
        "title": _openapi_safe_string(info.get("title")),
        "version": _openapi_safe_string(info.get("version")),
        **_openapi_text_metadata(description, "description"),
    }
    pointer = json_pointer((*pointer_prefix, "info"))
    return [
        _profile_observation(
            "openapi.info",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={key: item for key, item in metadata.items() if item is not None},
            name=_openapi_safe_string(info.get("title")),
            source_suffix=_openapi_source_suffix("info", pointer),
        )
    ]


def _openapi_server_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    if spec_metadata["spec_family"] == "openapi3":
        servers = value.get("servers")
        if not isinstance(servers, list):
            return observations
        for index, server in enumerate(servers):
            if not isinstance(server, dict):
                continue
            url = server.get("url")
            metadata = {
                **spec_metadata,
                "server_index": index,
                "not_fetched": True,
                **_openapi_url_metadata(url),
            }
            pointer = json_pointer((*pointer_prefix, "servers", str(index), "url"))
            observations.append(
                _profile_observation(
                    "openapi.server",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    source_suffix=_openapi_source_suffix("server", pointer),
                )
            )
        return observations

    host = value.get("host")
    base_path = value.get("basePath")
    schemes = value.get("schemes")
    metadata = {
        **spec_metadata,
        "not_fetched": True,
        "host": _openapi_safe_string(host),
        "base_path_present": isinstance(base_path, str),
        "schemes": [
            scheme
            for scheme in schemes
            if isinstance(scheme, str) and len(scheme) <= 16
        ]
        if isinstance(schemes, list)
        else [],
    }
    observations.append(
        _profile_observation(
            "openapi.server",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata=metadata,
            source_suffix=_openapi_source_suffix(
                "server", json_pointer((*pointer_prefix, "host"))
            ),
        )
    )
    return observations


def _openapi_path_operation_observations(
    relative_path: str,
    paths: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for path_template in sorted(str(key) for key in paths):
        path_item = paths.get(path_template)
        if not isinstance(path_item, dict):
            continue
        path_pointer = json_pointer((*pointer_prefix, path_template))
        observations.append(
            _profile_observation(
                "openapi.path",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    **spec_metadata,
                    "path_template": _openapi_bounded_string(path_template),
                    "method_count": sum(
                        1
                        for method in path_item
                        if _normalized_key(str(method)) in OPENAPI_HTTP_METHODS
                    ),
                    "source_path_key": config_path_key(relative_path, path_pointer),
                },
                name=_openapi_bounded_string(path_template),
                source_suffix=_openapi_source_suffix("path", path_pointer),
            )
        )
        path_parameters = path_item.get("parameters")
        for method_name in sorted(str(key) for key in path_item):
            method = _normalized_key(method_name)
            if method not in OPENAPI_HTTP_METHODS:
                continue
            operation = path_item.get(method_name)
            if not isinstance(operation, dict):
                continue
            operation_pointer_segments = (*pointer_prefix, path_template, method_name)
            operation_pointer = json_pointer(operation_pointer_segments)
            operation_id = _openapi_safe_string(operation.get("operationId"))
            observations.append(
                _profile_observation(
                    "openapi.operation",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        **spec_metadata,
                        "path_template": _openapi_bounded_string(path_template),
                        "method": method.upper(),
                        "operation_id": operation_id,
                        "tags": _openapi_string_list(operation.get("tags")),
                        **_openapi_text_metadata(operation.get("summary"), "summary"),
                        **_openapi_text_metadata(
                            operation.get("description"), "description"
                        ),
                        "source_path_key": config_path_key(relative_path, operation_pointer),
                    },
                    name=operation_id or f"{method.upper()} {path_template}",
                    source_suffix=_openapi_source_suffix("operation", operation_pointer),
                )
            )
            parameters = _openapi_parameters(operation, path_parameters)
            if len(parameters) > OPENAPI_MAX_PARAMETERS_PER_OPERATION:
                observations.append(
                    _openapi_parse_error_observation(
                        relative_path,
                        format_name=format_name,
                        error_kind="openapi-parameter-limit",
                        message="OpenAPI parameter count exceeds OPENAPI1 limit",
                    )
                )
            else:
                for index, parameter in enumerate(parameters):
                    observations.extend(
                        _openapi_parameter_observation(
                            relative_path,
                            parameter,
                            format_name=format_name,
                            confidence=confidence,
                            profile=profile,
                            spec_metadata=spec_metadata,
                            pointer_segments=(
                                *operation_pointer_segments,
                                "parameters",
                                str(index),
                            ),
                        )
                    )
            observations.extend(
                _openapi_request_body_observations(
                    relative_path,
                    operation,
                    format_name=format_name,
                    confidence=confidence,
                    profile=profile,
                    spec_metadata=spec_metadata,
                    pointer_segments=operation_pointer_segments,
                )
            )
            observations.extend(
                _openapi_response_observations(
                    relative_path,
                    operation,
                    format_name=format_name,
                    confidence=confidence,
                    profile=profile,
                    spec_metadata=spec_metadata,
                    pointer_segments=operation_pointer_segments,
                )
            )
            observations.extend(
                _openapi_tag_observations(
                    relative_path,
                    operation,
                    format_name=format_name,
                    confidence=confidence,
                    profile=profile,
                    spec_metadata=spec_metadata,
                    pointer_segments=operation_pointer_segments,
                )
            )
    return observations


def _openapi_parameter_observation(
    relative_path: str,
    parameter: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    if not isinstance(parameter, dict):
        return []
    pointer = json_pointer(pointer_segments)
    return [
        _profile_observation(
            "openapi.parameter",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={
                **spec_metadata,
                "parameter_name": _openapi_safe_string(parameter.get("name")),
                "parameter_in": _openapi_safe_string(parameter.get("in")),
                "required": bool(parameter.get("required", False)),
                "source_path_key": config_path_key(relative_path, pointer),
            },
            name=_openapi_safe_string(parameter.get("name")),
            source_suffix=_openapi_source_suffix("parameter", pointer),
        )
    ]


def _openapi_request_body_observations(
    relative_path: str,
    operation: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return []
    pointer = json_pointer((*pointer_segments, "requestBody"))
    return [
        _profile_observation(
            "openapi.request_body",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={
                **spec_metadata,
                "media_types": _openapi_media_types(request_body),
                "source_path_key": config_path_key(relative_path, pointer),
            },
            source_suffix=_openapi_source_suffix("request-body", pointer),
        )
    ]


def _openapi_response_observations(
    relative_path: str,
    operation: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return []
    observations: list[RawObservation] = []
    if len(responses) > OPENAPI_MAX_RESPONSES_PER_OPERATION:
        return [
            _openapi_parse_error_observation(
                relative_path,
                format_name=format_name,
                error_kind="openapi-response-limit",
                message="OpenAPI response count exceeds OPENAPI1 limit",
            )
        ]
    for status_code in sorted(str(key) for key in responses):
        response = responses.get(status_code)
        if not isinstance(response, dict):
            continue
        pointer = json_pointer((*pointer_segments, "responses", status_code))
        observations.append(
            _profile_observation(
                "openapi.response",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    **spec_metadata,
                    "status_code": status_code,
                    "media_types": _openapi_media_types(response),
                    "description_present": isinstance(response.get("description"), str),
                    "source_path_key": config_path_key(relative_path, pointer),
                },
                name=status_code,
                source_suffix=_openapi_source_suffix("response", pointer),
            )
        )
    return observations


def _openapi_tag_observations(
    relative_path: str,
    operation: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for tag in _openapi_string_list(operation.get("tags")):
        pointer = json_pointer((*pointer_segments, "tags", tag))
        observations.append(
            _profile_observation(
                "openapi.tag",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={**spec_metadata, "tag_name": tag},
                name=tag,
                source_suffix=_openapi_source_suffix("tag", pointer),
            )
        )
    return observations


def _openapi_component_observations(
    relative_path: str,
    components: dict[str, dict[str, Any]],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for component_type in sorted(components):
        entries = components[component_type]
        if not isinstance(entries, dict):
            continue
        for component_name in sorted(str(key) for key in entries):
            component = entries.get(component_name)
            if not isinstance(component, dict):
                continue
            pointer_segments = (
                (*pointer_prefix, component_type, component_name)
                if spec_metadata["spec_family"] == "swagger2"
                else (*pointer_prefix, "components", component_type, component_name)
            )
            pointer = json_pointer(pointer_segments)
            metadata = {
                **spec_metadata,
                "component_type": component_type,
                "component_name": _openapi_safe_string(component_name),
                "source_path_key": config_path_key(relative_path, pointer),
            }
            observations.append(
                _profile_observation(
                    "openapi.component",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=_openapi_safe_string(component_name),
                    source_suffix=_openapi_source_suffix("component", pointer),
                )
            )
            if component_type in ("schemas", "definitions"):
                observations.append(
                    _profile_observation(
                        "openapi.schema",
                        relative_path,
                        profile=profile,
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            **metadata,
                            "schema_name": _openapi_safe_string(component_name),
                            "schema_type": _openapi_safe_string(component.get("type")),
                            "property_count": len(component.get("properties", {}))
                            if isinstance(component.get("properties"), dict)
                            else 0,
                        },
                        name=_openapi_safe_string(component_name),
                        source_suffix=_openapi_source_suffix("schema", pointer),
                    )
                )
            if component_type in ("securitySchemes", "securityDefinitions"):
                observations.append(
                    _profile_observation(
                        "openapi.security_scheme",
                        relative_path,
                        profile=profile,
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            **metadata,
                            "scheme_name": _openapi_safe_string(component_name),
                            "type": _openapi_safe_string(component.get("type")),
                            "in": _openapi_safe_string(component.get("in")),
                            "name_present": isinstance(component.get("name"), str),
                            "scheme": _openapi_safe_string(component.get("scheme")),
                            "bearer_format": _openapi_safe_string(
                                component.get("bearerFormat")
                            ),
                            "oauth_flow_names": _openapi_oauth_flow_names(component),
                            "scope_names": _openapi_scope_names(component),
                        },
                        name=_openapi_safe_string(component_name),
                        source_suffix=_openapi_source_suffix("security", pointer),
                    )
                )
    return observations


def _openapi_reference_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for pointer_segments, ref_value in _openapi_ref_values(value):
        if len(observations) >= OPENAPI_MAX_REFERENCES:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-reference-limit",
                    message="OpenAPI reference count exceeds OPENAPI1 limit",
                )
            )
            break
        pointer = json_pointer((*pointer_prefix, *pointer_segments))
        metadata, target = _openapi_reference_metadata(
            relative_path,
            ref_value,
            spec_metadata=spec_metadata,
            source_pointer=pointer,
        )
        observations.append(
            _profile_observation(
                "openapi.reference",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                target=target,
                source_suffix=_openapi_source_suffix("reference", pointer),
            )
        )
        if metadata.get("reference_scope") == "local_file" and target.startswith(
            "unknown:file:"
        ):
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-local-ref-outside-root",
                    message="OpenAPI local file reference is outside the repository root",
                )
            )
    external_docs = value.get("externalDocs") if isinstance(value, dict) else None
    if isinstance(external_docs, dict) and isinstance(external_docs.get("url"), str):
        pointer = json_pointer((*pointer_prefix, "externalDocs", "url"))
        metadata, target = _openapi_reference_metadata(
            relative_path,
            external_docs["url"],
            spec_metadata=spec_metadata,
            source_pointer=pointer,
            reference_scope_override="external_docs",
        )
        observations.append(
            _profile_observation(
                "openapi.reference",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                target=target,
                source_suffix=_openapi_source_suffix("external-docs", pointer),
            )
        )
    return observations


def _openapi_example_and_redaction_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    example_count = 0
    for pointer_segments, path_value in _openapi_walk(value):
        pointer = json_pointer((*pointer_prefix, *pointer_segments))
        key = pointer_segments[-1] if pointer_segments else ""
        if _normalized_key(key) in OPENAPI_EXAMPLE_KEYS:
            if example_count < OPENAPI_MAX_EXAMPLES:
                observations.append(
                    _profile_observation(
                        "openapi.example",
                        relative_path,
                        profile=profile,
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            **spec_metadata,
                            "pointer": pointer,
                            "value_type": _value_type(path_value),
                            "value_shape": _value_shape(path_value),
                            "value_sha256": _stable_value_sha256(path_value),
                            "redacted": _openapi_pointer_is_redacted(
                                pointer, path_value
                            ),
                        },
                        source_suffix=_openapi_source_suffix("example", pointer),
                    )
                )
                example_count += 1
        if _openapi_pointer_is_redacted(pointer, path_value):
            observations.append(
                _profile_observation(
                    "openapi.redaction",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        **spec_metadata,
                        "pointer": pointer,
                        "value_type": _value_type(path_value),
                        "value_sha256": _stable_value_sha256(path_value),
                        "redaction_reason": _openapi_redaction_reason(
                            pointer, path_value
                        ),
                    },
                    source_suffix=_openapi_source_suffix("redaction", pointer),
                )
            )
    return observations


def _openapi_components(
    value: dict[str, Any],
    spec_family: str,
) -> dict[str, dict[str, Any]]:
    if spec_family == "swagger2":
        components: dict[str, dict[str, Any]] = {}
        definitions = value.get("definitions")
        if isinstance(definitions, dict):
            components["definitions"] = definitions
        security_definitions = value.get("securityDefinitions")
        if isinstance(security_definitions, dict):
            components["securityDefinitions"] = security_definitions
        return components
    raw_components = value.get("components")
    if not isinstance(raw_components, dict):
        return {}
    components = {}
    for key in ("schemas", "responses", "parameters", "securitySchemes"):
        item = raw_components.get(key)
        if isinstance(item, dict):
            components[key] = item
    return components


def _openapi_parameters(
    operation: dict[str, Any],
    path_parameters: Any,
) -> list[Any]:
    parameters: list[Any] = []
    if isinstance(path_parameters, list):
        parameters.extend(path_parameters)
    operation_parameters = operation.get("parameters")
    if isinstance(operation_parameters, list):
        parameters.extend(operation_parameters)
    return parameters


def _openapi_media_types(value: dict[str, Any]) -> list[str]:
    content = value.get("content")
    if not isinstance(content, dict):
        return []
    return sorted(
        media_type
        for media_type in (str(key) for key in content)
        if len(media_type) <= 120 and "/" in media_type
    )


def _openapi_operation_count(paths: dict[str, Any]) -> int:
    count = 0
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        count += sum(
            1
            for method in path_item
            if _normalized_key(str(method)) in OPENAPI_HTTP_METHODS
        )
    return count


def _openapi_server_count(value: dict[str, Any], spec_family: str) -> int:
    if spec_family == "openapi3":
        servers = value.get("servers")
        return len(servers) if isinstance(servers, list) else 0
    return 1 if value.get("host") is not None or value.get("basePath") is not None else 0


def _openapi_ref_values(value: Any) -> tuple[tuple[tuple[str, ...], str], ...]:
    refs: list[tuple[tuple[str, ...], str]] = []
    for pointer_segments, path_value in _openapi_walk(value):
        if pointer_segments and pointer_segments[-1] == "$ref" and isinstance(path_value, str):
            refs.append((pointer_segments, path_value))
    return tuple(refs)


def _openapi_walk(value: Any, pointer_segments: tuple[str, ...] = ()) -> tuple[tuple[tuple[str, ...], Any], ...]:
    items: list[tuple[tuple[str, ...], Any]] = [(pointer_segments, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            items.extend(_openapi_walk(item, (*pointer_segments, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            items.extend(_openapi_walk(item, (*pointer_segments, str(index))))
    return tuple(items)


def _openapi_reference_metadata(
    relative_path: str,
    ref_value: str,
    *,
    spec_metadata: dict[str, str],
    source_pointer: str,
    reference_scope_override: str | None = None,
) -> tuple[dict[str, Any], str]:
    credentialed = _url_has_credentials(ref_value)
    scope = reference_scope_override or _openapi_reference_scope(ref_value)
    target: str
    if scope == "internal" and ref_value.startswith("#/"):
        target = config_path_key(relative_path, ref_value[1:])
    elif scope == "local_file":
        path_part = ref_value.split("#", 1)[0]
        target = _file_reference(relative_path, path_part, redacted=False)["target"]
    elif _is_url(ref_value) and not credentialed:
        target = external_url_key(ref_value)
    elif _is_url(ref_value):
        target = external_key("url", "credentialed-openapi-reference")
    else:
        target = unknown_key("openapi.reference", "unsupported-ref")
    local_ref_outside_root = scope == "local_file" and target.startswith(
        "unknown:file:"
    )
    metadata = {
        **spec_metadata,
        "pointer": source_pointer,
        "reference_scope": scope,
        "not_fetched": True,
        "redacted": credentialed or local_ref_outside_root,
        "target_kind": target.split(":", 1)[0],
        "ref_summary": "<redacted-url>"
        if credentialed
        else "<redacted-local-ref>"
        if local_ref_outside_root
        else _openapi_bounded_string(ref_value),
        "ref_sha256": _stable_text_sha256(ref_value),
    }
    if credentialed:
        metadata["redaction_reason"] = "credentialed-url"
    if local_ref_outside_root:
        metadata["redaction_reason"] = "local-ref-outside-root"
    return metadata, target


def _openapi_reference_scope(ref_value: str) -> str:
    if ref_value.startswith("#/"):
        return "internal"
    if _is_url(ref_value):
        return "remote"
    return "local_file"


def _openapi_oauth_flow_names(value: dict[str, Any]) -> list[str]:
    flows = value.get("flows")
    if not isinstance(flows, dict):
        return []
    return sorted(
        str(name)
        for name in flows
        if len(str(name)) <= OPENAPI_MAX_METADATA_STRING
    )


def _openapi_scope_names(value: dict[str, Any]) -> list[str]:
    scope_names: set[str] = set()
    flows = value.get("flows")
    if not isinstance(flows, dict):
        return []
    for flow in flows.values():
        if not isinstance(flow, dict):
            continue
        scopes = flow.get("scopes")
        if isinstance(scopes, dict):
            scope_names.update(
                str(name)
                for name in scopes
                if len(str(name)) <= OPENAPI_MAX_METADATA_STRING
                and not _openapi_sensitive_key(str(name))
            )
    return sorted(scope_names)


def _openapi_text_metadata(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, str):
        return {f"{key}_present": False}
    return {
        f"{key}_present": True,
        f"{key}_length": len(value),
        f"{key}_sha256": _stable_text_sha256(value),
    }


def _openapi_url_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {"url_present": False}
    parsed = urlsplit(value)
    credentialed = _url_has_credentials(value)
    metadata: dict[str, Any] = {
        "url_present": True,
        "url_length": len(value),
        "url_sha256": _stable_text_sha256(value),
        "redacted": credentialed,
    }
    if parsed.scheme and len(parsed.scheme) <= 16:
        metadata["scheme"] = parsed.scheme
    if parsed.hostname and not credentialed:
        metadata["host"] = _openapi_bounded_string(parsed.hostname)
    if credentialed:
        metadata["redaction_reason"] = "credentialed-url"
    return metadata


def _openapi_safe_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if _openapi_sensitive_key(value) or _looks_like_secret_scalar(value):
        return None
    return _openapi_bounded_string(value)


def _openapi_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        safe = _openapi_safe_string(item)
        if safe is not None:
            strings.append(safe)
    return strings[:32]


def _openapi_bounded_string(value: str) -> str:
    if len(value) <= OPENAPI_MAX_METADATA_STRING:
        return value
    return f"<string:{len(value)}>"


def _openapi_pointer_is_redacted(pointer: str, value: Any) -> bool:
    segments = _pointer_segments(pointer)
    normalized_segments = tuple(_normalized_key(segment) for segment in segments)
    if (
        normalized_segments
        and normalized_segments[-1] == "$ref"
        and isinstance(value, str)
        and value.startswith("../")
    ):
        return True
    if any(_openapi_sensitive_key(segment) for segment in normalized_segments):
        return True
    if any(segment in OPENAPI_TEXT_KEYS for segment in normalized_segments):
        return True
    if any(segment in OPENAPI_EXAMPLE_KEYS for segment in normalized_segments):
        return True
    if isinstance(value, str) and _url_has_credentials(value):
        return True
    return _looks_like_secret_scalar(value)


def _openapi_redaction_reason(pointer: str, value: Any) -> str:
    if isinstance(value, str) and _url_has_credentials(value):
        return "credentialed-url"
    segments = tuple(_normalized_key(segment) for segment in _pointer_segments(pointer))
    if (
        segments
        and segments[-1] == "$ref"
        and isinstance(value, str)
        and value.startswith("../")
    ):
        return "openapi-ref-summary-only"
    if any(segment in OPENAPI_TEXT_KEYS for segment in segments):
        return "openapi-text-summary-only"
    if any(segment in OPENAPI_EXAMPLE_KEYS for segment in segments):
        return "openapi-example-summary-only"
    return "secret-prone-openapi-field"


def _openapi_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    squashed = re.sub(r"[^0-9a-z]", "", normalized)
    markers = tuple(SECRET_PRONE_KEYS) + (
        "key",
        "authorization",
        "jwt",
        "database_url",
        "webhook",
        "oauth",
        "openid",
        "x_api_key",
    )
    return any(marker.replace("_", "") in squashed for marker in markers)


def _url_has_credentials(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.username is not None or parsed.password is not None


def _stable_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_value_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError:
        encoded = repr(value)
    return _stable_text_sha256(encoded)


def _openapi_source_suffix(kind: str, pointer: str) -> str:
    return f"openapi-{kind}:{_stable_text_sha256(pointer)[:16]}"


def _openapi_parse_error_observation(
    relative_path: str,
    *,
    format_name: str,
    error_kind: str,
    message: str,
    start_line: int | None = None,
    document_index: int | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": format_name,
        "profile": "openapi" if format_name == YAML_FORMAT else "openapi_json",
        "error_kind": error_kind,
        "message_summary": _safe_error_message(None, message),
        "recovered": False,
        "raw_profile_only": True,
    }
    if document_index is not None:
        metadata["document_index"] = document_index
    if start_line is not None:
        metadata["line_number"] = start_line
    return RawObservation(
        kind="openapi.parse_error",
        source_id=(
            f"{relative_path}#openapi-parse-error:"
            f"{_stable_text_sha256(error_kind + ':' + message)[:16]}"
        ),
        path=relative_path,
        start_line=start_line,
        end_line=start_line,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _terraform_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = [
        _profile_observation(
            "terraform.file",
            relative_path,
            profile="terraform_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "variant": "tf.json",
                "declared_sections": sorted(str(key) for key in value),
            },
            source_suffix="terraform-file",
        )
    ]
    terraform = value.get("terraform")
    if isinstance(terraform, dict):
        required_version = _safe_value_summary(terraform.get("required_version"))
        if isinstance(required_version, str):
            observations.append(
                _profile_observation(
                    "terraform.required_version",
                    relative_path,
                    profile="terraform_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={"version_constraint": required_version},
                    source_suffix="terraform-required-version",
                )
            )
        required_providers = terraform.get("required_providers")
        if isinstance(required_providers, dict):
            for provider_name in sorted(str(key) for key in required_providers):
                provider_config = required_providers.get(provider_name)
                source = provider_name
                version = None
                if isinstance(provider_config, dict):
                    source = str(provider_config.get("source") or provider_name)
                    version = _safe_value_summary(provider_config.get("version"))
                observations.append(
                    _profile_observation(
                        "terraform.required_provider",
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            "provider_name": provider_name,
                            "provider_source": source,
                            "version_constraint": version,
                        },
                        name=provider_name,
                        target=external_key("terraform.provider", source),
                        source_suffix=f"terraform-required-provider:{provider_name}",
                    )
                )
                observations.append(
                    _terraform_reference_observation(
                        relative_path,
                        "provider_source",
                        source,
                        target=external_key("terraform.provider", source),
                        confidence="heuristic",
                        format_name=format_name,
                    )
                )
        backend = terraform.get("backend")
        if isinstance(backend, dict):
            for backend_type in sorted(str(key) for key in backend):
                observations.append(
                    _profile_observation(
                        "terraform.backend",
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={"backend_type": backend_type},
                        name=backend_type,
                        source_suffix=f"terraform-backend:{backend_type}",
                    )
                )
    observations.extend(
        _terraform_named_block_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    return observations


def _terraform_named_block_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for provider_name in _terraform_block_names(value.get("provider")):
        observations.append(
            _profile_observation(
                "terraform.provider",
                relative_path,
                profile="terraform_json",
                format_name=format_name,
                confidence=confidence,
                metadata={"provider_name": provider_name},
                name=provider_name,
                source_suffix=f"terraform-provider:{provider_name}",
            )
        )
    for kind, raw_kind, type_key, name_key in (
        ("resource", "terraform.resource", "resource_type", "resource_name"),
        ("data", "terraform.data_source", "data_source_type", "data_source_name"),
    ):
        section = value.get(kind)
        if not isinstance(section, dict):
            continue
        for block_type in sorted(str(key) for key in section):
            instances = section.get(block_type)
            if not isinstance(instances, dict):
                continue
            for block_name in sorted(str(key) for key in instances):
                observations.append(
                    _profile_observation(
                        raw_kind,
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={type_key: block_type, name_key: block_name},
                        name=f"{block_type}.{block_name}",
                        source_suffix=f"{raw_kind.replace('.', '-')}:{block_type}:{block_name}",
                    )
                )
    modules = value.get("module")
    if isinstance(modules, dict):
        for module_name in sorted(str(key) for key in modules):
            module_config = modules.get(module_name)
            source = None
            if isinstance(module_config, dict) and isinstance(module_config.get("source"), str):
                source = module_config["source"]
            metadata = {"module_name": module_name}
            if source is not None:
                metadata["source_summary"] = _safe_value_summary(source)
            observations.append(
                _profile_observation(
                    "terraform.module",
                    relative_path,
                    profile="terraform_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=module_name,
                    source_suffix=f"terraform-module:{module_name}",
                )
            )
            if source is not None:
                observations.append(
                    _terraform_reference_observation(
                        relative_path,
                        "module_source",
                        source,
                        target=external_key("terraform.module", source),
                        confidence="heuristic",
                        format_name=format_name,
                    )
                )
    for section_name, observation_kind, metadata_key in (
        ("variable", "terraform.variable", "variable_name"),
        ("output", "terraform.output", "output_name"),
    ):
        section = value.get(section_name)
        if isinstance(section, dict):
            for item_name in sorted(str(key) for key in section):
                observations.append(
                    _profile_observation(
                        observation_kind,
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={metadata_key: item_name},
                        name=item_name,
                        source_suffix=f"{observation_kind.replace('.', '-')}:{item_name}",
                    )
                )
    locals_section = value.get("locals")
    if isinstance(locals_section, dict):
        for local_name in sorted(str(key) for key in locals_section):
            observations.append(
                _profile_observation(
                    "terraform.local",
                    relative_path,
                    profile="terraform_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={"local_name": local_name},
                    name=local_name,
                    source_suffix=f"terraform-local:{local_name}",
                )
            )
    return observations


def _terraform_block_names(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(sorted(str(key) for key in value))
    if isinstance(value, list):
        names = []
        for item in value:
            if isinstance(item, dict):
                names.extend(str(key) for key in item)
        return tuple(sorted(set(names)))
    return ()


def _terraform_reference_observation(
    relative_path: str,
    reference_kind: str,
    raw_value: str,
    *,
    target: str,
    confidence: str,
    format_name: str,
) -> RawObservation:
    return _profile_observation(
        "terraform.reference",
        relative_path,
        profile="terraform_json",
        format_name=format_name,
        confidence=confidence,
        metadata={
            "reference_kind": reference_kind,
            "raw_value_summary": _safe_value_summary(raw_value),
            "not_fetched": True,
        },
        target=target,
        source_suffix=f"terraform-reference:{reference_kind}:{raw_value}",
    )


def _terraform_tfvars_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations = [
        _profile_observation(
            "terraform.file",
            relative_path,
            profile="terraform_tfvars_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "variant": "tfvars.json",
                "all_values_sensitive": True,
                "variable_count": len(value),
            },
            source_suffix="terraform-file",
        )
    ]
    for variable_name in sorted(str(key) for key in value):
        variable_value = value[variable_name]
        observations.append(
            _profile_observation(
                "terraform.variable",
                relative_path,
                profile="terraform_tfvars_json",
                format_name=format_name,
                confidence=confidence,
                metadata={
                    "variable_name": variable_name,
                    "value_type": _value_type(variable_value),
                    "value_shape": _value_shape(variable_value),
                    "redacted": True,
                    "redaction_reason": "tfvars-sensitive-by-default",
                },
                name=variable_name,
                source_suffix=f"terraform-variable:{variable_name}",
            )
        )
    return observations


def _extract_terraform_hcl_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    diagnostics: list[RawObservation] = []
    observations: list[RawObservation] = []
    encoded_size = len(content.encode("utf-8"))
    observations.append(
        _terraform_hcl_observation(
            "terraform.file",
            relative_path,
            metadata={
                "file_family": "tf",
                "parser": TERRAFORM_HCL_PARSER,
                "byte_count": encoded_size,
            },
            source_suffix="terraform-file",
        )
    )
    if encoded_size > TERRAFORM_HCL_MAX_FILE_BYTES:
        observations.append(
            _terraform_hcl_parse_error_observation(
                relative_path,
                error_kind="terraform-file-byte-limit",
                message="Terraform HCL file exceeds conservative byte limit",
                recovered=False,
            )
        )
        return tuple(observations)

    blocks, block_diagnostics = _terraform_hcl_scan_blocks(relative_path, content)
    observations.extend(block_diagnostics)
    for block in blocks:
        observations.append(_terraform_hcl_block_observation(relative_path, block))
        observations.extend(_terraform_hcl_block_profile_observations(relative_path, block))
    return tuple(observations)


def _extract_terraform_hcl_tfvars_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    encoded_size = len(content.encode("utf-8"))
    observations.append(
        _terraform_hcl_observation(
            "terraform.file",
            relative_path,
            profile=TERRAFORM_HCL_TFVARS_PROFILE,
            metadata={
                "file_family": "tfvars",
                "parser": TERRAFORM_HCL_PARSER,
                "byte_count": encoded_size,
                "all_values_sensitive": True,
            },
            source_suffix="terraform-file",
        )
    )
    if encoded_size > TERRAFORM_HCL_MAX_FILE_BYTES:
        observations.append(
            _terraform_hcl_parse_error_observation(
                relative_path,
                error_kind="terraform-file-byte-limit",
                message="Terraform tfvars file exceeds conservative byte limit",
                recovered=False,
            )
        )
        return tuple(observations)

    attributes, diagnostics = _terraform_hcl_top_level_attributes(
        relative_path,
        content,
        base_line=1,
    )
    observations.extend(diagnostics)
    for attribute in attributes:
        value_type = _terraform_hcl_value_type(attribute.value)
        observations.append(
            _terraform_hcl_observation(
                "terraform.variable",
                relative_path,
                profile=TERRAFORM_HCL_TFVARS_PROFILE,
                confidence="heuristic",
                metadata={
                    "file_family": "tfvars",
                    "variable_name": attribute.name,
                    "value_type": value_type,
                    "value_shape": {"type": value_type},
                    "redacted": True,
                    "redaction_reason": "tfvars-sensitive-by-default",
                },
                name=attribute.name,
                start_line=attribute.start_line,
                source_suffix=f"terraform-variable:{attribute.name}",
            )
        )
        observations.append(
            _terraform_hcl_redaction_observation(
                relative_path,
                redaction_reason="tfvars-sensitive-by-default",
                field_name=attribute.name,
                start_line=attribute.start_line,
            )
        )
    return tuple(observations)


def _terraform_hcl_scan_blocks(
    relative_path: str,
    content: str,
) -> tuple[list[_TerraformHclBlock], list[RawObservation]]:
    blocks: list[_TerraformHclBlock] = []
    diagnostics: list[RawObservation] = []
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is None or match.group("block_type") not in TERRAFORM_HCL_BLOCK_TYPES:
            index += 1
            continue
        if len(blocks) >= TERRAFORM_HCL_MAX_BLOCKS:
            diagnostics.append(
                _terraform_hcl_parse_error_observation(
                    relative_path,
                    error_kind="terraform-block-limit",
                    message="Terraform HCL block limit reached",
                    start_line=index + 1,
                    recovered=True,
                )
            )
            break

        block_type = match.group("block_type")
        labels = _terraform_hcl_labels(match.group("labels"))
        start_line = index + 1
        depth = _terraform_hcl_brace_delta(line)
        body_lines: list[str] = []
        index += 1
        if depth <= 0:
            blocks.append(
                _TerraformHclBlock(
                    block_type=block_type,
                    labels=labels,
                    body="",
                    start_line=start_line,
                    end_line=start_line,
                )
            )
            continue
        while index < len(lines) and depth > 0:
            body_line = lines[index]
            depth += _terraform_hcl_brace_delta(body_line)
            if depth > 0:
                body_lines.append(body_line)
            index += 1
        if depth > 0:
            diagnostics.append(
                _terraform_hcl_parse_error_observation(
                    relative_path,
                    error_kind="terraform-unclosed-block",
                    message="Terraform HCL block is missing a closing brace",
                    start_line=start_line,
                    recovered=True,
                )
            )
            end_line = len(lines)
        else:
            end_line = index
        blocks.append(
            _TerraformHclBlock(
                block_type=block_type,
                labels=labels,
                body="\n".join(body_lines),
                start_line=start_line,
                end_line=end_line,
            )
        )
    return blocks, diagnostics[:TERRAFORM_HCL_MAX_DIAGNOSTICS]


def _terraform_hcl_block_profile_observations(
    relative_path: str,
    block: _TerraformHclBlock,
) -> list[RawObservation]:
    attributes, diagnostics = _terraform_hcl_top_level_attributes(
        relative_path,
        block.body,
        base_line=block.start_line + 1,
    )
    by_name = {attribute.name: attribute for attribute in attributes}
    observations: list[RawObservation] = list(diagnostics)
    observations.extend(
        _terraform_hcl_attribute_redactions(relative_path, attributes)
    )
    if block.block_type == "terraform":
        observations.extend(
            _terraform_hcl_terraform_block_observations(
                relative_path,
                block,
                by_name,
            )
        )
    elif block.block_type == "provider":
        observations.extend(
            _terraform_hcl_provider_observations(relative_path, block, by_name)
        )
    elif block.block_type == "resource":
        observations.extend(
            _terraform_hcl_resource_observations(relative_path, block, by_name)
        )
    elif block.block_type == "data":
        observations.extend(_terraform_hcl_data_observations(relative_path, block))
    elif block.block_type == "module":
        observations.extend(
            _terraform_hcl_module_observations(relative_path, block, by_name)
        )
    elif block.block_type == "variable":
        observations.extend(
            _terraform_hcl_variable_observations(relative_path, block, by_name)
        )
    elif block.block_type == "output":
        observations.extend(
            _terraform_hcl_output_observations(relative_path, block, by_name)
        )
    elif block.block_type == "locals":
        observations.extend(_terraform_hcl_local_observations(relative_path, attributes))
    elif block.block_type == "moved":
        observations.extend(
            _terraform_hcl_move_like_observations(
                relative_path,
                "terraform.moved",
                block,
                by_name,
                fields=("from", "to"),
            )
        )
    elif block.block_type == "import":
        observations.extend(_terraform_hcl_import_observations(relative_path, block, by_name))
    elif block.block_type == "removed":
        observations.extend(
            _terraform_hcl_move_like_observations(
                relative_path,
                "terraform.removed",
                block,
                by_name,
                fields=("from",),
            )
        )
    elif block.block_type == "check":
        observations.append(
            _terraform_hcl_observation(
                "terraform.check",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "check_name": block.labels[0] if block.labels else None,
                    "assertion_count": _terraform_hcl_nested_block_count(
                        block.body,
                        "assert",
                    ),
                },
                name=block.labels[0] if block.labels else None,
                start_line=block.start_line,
                end_line=block.end_line,
                source_suffix=f"terraform-check:{block.labels[0] if block.labels else block.start_line}",
            )
        )
    return observations


def _terraform_hcl_terraform_block_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    required_version = attributes.get("required_version")
    if required_version is not None:
        version_constraint = _terraform_hcl_literal_string(required_version.value)
        if version_constraint is None:
            version_constraint = _terraform_hcl_expression_summary(required_version.value)
        observations.append(
            _terraform_hcl_observation(
                "terraform.required_version",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "version_constraint": version_constraint,
                    "expression_kind": _terraform_hcl_expression_kind(
                        required_version.value
                    ),
                },
                start_line=required_version.start_line,
                source_suffix="terraform-required-version",
            )
        )
        observations.append(
            _terraform_hcl_reference_observation(
                relative_path,
                "required_version",
                version_constraint,
                target=external_key("terraform.version", version_constraint),
                start_line=required_version.start_line,
            )
        )

    required_providers_body = _terraform_hcl_nested_block_body(
        block.body,
        "required_providers",
    )
    if required_providers_body is not None:
        provider_attributes, diagnostics = _terraform_hcl_top_level_attributes(
            relative_path,
            required_providers_body,
            base_line=block.start_line,
        )
        observations.extend(diagnostics)
        for provider in provider_attributes:
            provider_body = _terraform_hcl_collection_body(provider.value)
            provider_source = provider.name
            version_constraint = None
            if provider_body is not None:
                provider_config, provider_diagnostics = _terraform_hcl_top_level_attributes(
                    relative_path,
                    provider_body,
                    base_line=provider.start_line,
                )
                observations.extend(provider_diagnostics)
                provider_fields = {item.name: item for item in provider_config}
                source = provider_fields.get("source")
                version = provider_fields.get("version")
                if source is not None:
                    provider_source = (
                        _terraform_hcl_literal_string(source.value) or provider.name
                    )
                if version is not None:
                    version_constraint = (
                        _terraform_hcl_literal_string(version.value)
                        or _terraform_hcl_expression_summary(version.value)
                    )
            observations.append(
                _terraform_hcl_observation(
                    "terraform.required_provider",
                    relative_path,
                    confidence="heuristic",
                    metadata={
                        "file_family": "tf",
                        "provider_name": provider.name,
                        "provider_source": provider_source,
                        "version_constraint": version_constraint,
                        "not_fetched": True,
                    },
                    name=provider.name,
                    target=external_key("terraform.provider", provider_source),
                    start_line=provider.start_line,
                    source_suffix=f"terraform-required-provider:{provider.name}",
                )
            )
            observations.append(
                _terraform_hcl_reference_observation(
                    relative_path,
                    "provider_source",
                    provider_source,
                    target=external_key("terraform.provider", provider_source),
                    start_line=provider.start_line,
                )
            )

    for backend_type in _terraform_hcl_nested_block_labels(block.body, "backend"):
        observations.append(
            _terraform_hcl_observation(
                "terraform.backend",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "backend_type": backend_type,
                    "not_fetched": True,
                },
                name=backend_type,
                source_suffix=f"terraform-backend:{backend_type}",
                start_line=block.start_line,
            )
        )
    return observations


def _terraform_hcl_provider_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    provider_name = block.labels[0] if block.labels else "unknown"
    alias = None
    if "alias" in attributes:
        alias = _terraform_hcl_literal_string(attributes["alias"].value)
    return [
        _terraform_hcl_observation(
            "terraform.provider",
            relative_path,
            confidence="heuristic",
            metadata={
                "file_family": "tf",
                "provider_name": provider_name,
                "alias": alias,
            },
            name=provider_name,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-provider:{provider_name}:{alias or 'default'}",
        )
    ]


def _terraform_hcl_resource_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    resource_type = block.labels[0] if len(block.labels) >= 1 else "unknown"
    resource_name = block.labels[1] if len(block.labels) >= 2 else "unknown"
    observations = [
        _terraform_hcl_observation(
            "terraform.resource",
            relative_path,
            confidence="heuristic",
            metadata={
                "file_family": "tf",
                "resource_type": resource_type,
                "resource_name": resource_name,
                "provider_prefix": resource_type.split("_", 1)[0]
                if "_" in resource_type
                else resource_type,
                "count_present": "count" in attributes,
                "for_each_present": "for_each" in attributes,
                "lifecycle_present": _terraform_hcl_nested_block_count(
                    block.body,
                    "lifecycle",
                )
                > 0,
                "connection_present": _terraform_hcl_nested_block_count(
                    block.body,
                    "connection",
                )
                > 0,
                "provisioner_present": _terraform_hcl_nested_block_count(
                    block.body,
                    "provisioner",
                )
                > 0,
            },
            name=f"{resource_type}.{resource_name}",
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-resource:{resource_type}:{resource_name}",
        )
    ]
    observations.extend(
        _terraform_hcl_reference_observations_from_attribute(
            relative_path,
            attributes.get("depends_on"),
            "depends_on",
        )
    )
    observations.extend(
        _terraform_hcl_reference_observations_from_attribute(
            relative_path,
            attributes.get("provider"),
            "provider_alias",
            target_kind="terraform.provider",
        )
    )
    return observations


def _terraform_hcl_data_observations(
    relative_path: str,
    block: _TerraformHclBlock,
) -> list[RawObservation]:
    data_source_type = block.labels[0] if len(block.labels) >= 1 else "unknown"
    data_source_name = block.labels[1] if len(block.labels) >= 2 else "unknown"
    return [
        _terraform_hcl_observation(
            "terraform.data_source",
            relative_path,
            confidence="heuristic",
            metadata={
                "file_family": "tf",
                "data_source_type": data_source_type,
                "data_source_name": data_source_name,
                "not_fetched": True,
            },
            name=f"{data_source_type}.{data_source_name}",
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-data-source:{data_source_type}:{data_source_name}",
        )
    ]


def _terraform_hcl_module_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    module_name = block.labels[0] if block.labels else "unknown"
    metadata: dict[str, Any] = {"file_family": "tf", "module_name": module_name}
    target = None
    observations: list[RawObservation] = []
    source = attributes.get("source")
    if source is not None:
        source_value = _terraform_hcl_literal_string(source.value)
        if source_value is not None:
            source_metadata, target, reference_kind = _terraform_hcl_module_source(
                relative_path,
                source_value,
            )
            metadata.update(source_metadata)
            observations.append(
                _terraform_hcl_reference_observation(
                    relative_path,
                    reference_kind,
                    source_value,
                    target=target,
                    start_line=source.start_line,
                    redacted=bool(source_metadata.get("redacted")),
                )
            )
        else:
            metadata.update(
                {
                    "source_expression_kind": _terraform_hcl_expression_kind(
                        source.value
                    ),
                    "dynamic": True,
                    "not_fetched": True,
                }
            )
    observations.insert(
        0,
        _terraform_hcl_observation(
            "terraform.module",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            name=module_name,
            target=target,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-module:{module_name}",
        ),
    )
    return observations


def _terraform_hcl_variable_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    variable_name = block.labels[0] if block.labels else "unknown"
    default = attributes.get("default")
    type_attr = attributes.get("type")
    description = attributes.get("description")
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "variable_name": variable_name,
        "default_present": default is not None,
        "validation_present": _terraform_hcl_nested_block_count(
            block.body,
            "validation",
        )
        > 0,
    }
    if type_attr is not None:
        metadata["type_expression_kind"] = _terraform_hcl_expression_kind(
            type_attr.value
        )
        metadata["type_summary"] = _terraform_hcl_expression_summary(type_attr.value)
    if default is not None:
        metadata["default_value_type"] = _terraform_hcl_value_type(default.value)
        metadata["default_expression_kind"] = _terraform_hcl_expression_kind(
            default.value
        )
    if "sensitive" in attributes:
        metadata["sensitive"] = _terraform_hcl_bool_literal(
            attributes["sensitive"].value
        )
    if description is not None:
        metadata.update(_terraform_hcl_text_presence_metadata("description", description.value))
    return [
        _terraform_hcl_observation(
            "terraform.variable",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            name=variable_name,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-variable:{variable_name}",
        )
    ]


def _terraform_hcl_output_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    output_name = block.labels[0] if block.labels else "unknown"
    value = attributes.get("value")
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "output_name": output_name,
        "value_expression_kind": _terraform_hcl_expression_kind(value.value)
        if value is not None
        else "unknown",
        "value_redacted": True,
    }
    if "sensitive" in attributes:
        metadata["sensitive"] = _terraform_hcl_bool_literal(
            attributes["sensitive"].value
        )
    if "description" in attributes:
        metadata.update(
            _terraform_hcl_text_presence_metadata(
                "description",
                attributes["description"].value,
            )
        )
    return [
        _terraform_hcl_observation(
            "terraform.output",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            name=output_name,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-output:{output_name}",
        )
    ]


def _terraform_hcl_local_observations(
    relative_path: str,
    attributes: list[_TerraformHclAttribute],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for attribute in attributes[:TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK]:
        redacted = _is_secret_key(attribute.name)
        observations.append(
            _terraform_hcl_observation(
                "terraform.local",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "local_name": attribute.name,
                    "expression_kind": "redacted"
                    if redacted
                    else _terraform_hcl_expression_kind(attribute.value),
                    "redacted": redacted,
                },
                name=attribute.name,
                start_line=attribute.start_line,
                source_suffix=f"terraform-local:{attribute.name}",
            )
        )
        if redacted:
            observations.append(
                _terraform_hcl_redaction_observation(
                    relative_path,
                    redaction_reason="secret-prone-terraform-local",
                    field_name=attribute.name,
                    start_line=attribute.start_line,
                )
            )
    return observations


def _terraform_hcl_move_like_observations(
    relative_path: str,
    kind: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
    *,
    fields: tuple[str, ...],
) -> list[RawObservation]:
    metadata: dict[str, Any] = {"file_family": "tf"}
    for field in fields:
        attribute = attributes.get(field)
        if attribute is not None:
            metadata[f"{field}_summary"] = _terraform_hcl_expression_summary(
                attribute.value
            )
    return [
        _terraform_hcl_observation(
            kind,
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"{kind.replace('.', '-')}:{block.start_line}",
        )
    ]


def _terraform_hcl_import_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    target = attributes.get("to")
    import_id = attributes.get("id")
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "id_redacted": import_id is not None,
    }
    if target is not None:
        metadata["to_summary"] = _terraform_hcl_expression_summary(target.value)
    if import_id is not None:
        metadata["id_expression_kind"] = _terraform_hcl_expression_kind(import_id.value)
        metadata["redacted"] = True
        metadata["redaction_reason"] = "terraform-import-id-sensitive-by-default"
    observations = [
        _terraform_hcl_observation(
            "terraform.import",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-import:{block.start_line}",
        )
    ]
    if import_id is not None:
        observations.append(
            _terraform_hcl_redaction_observation(
                relative_path,
                redaction_reason="terraform-import-id-sensitive-by-default",
                field_name="id",
                start_line=import_id.start_line,
            )
        )
    return observations


def _terraform_hcl_block_observation(
    relative_path: str,
    block: _TerraformHclBlock,
) -> RawObservation:
    return _terraform_hcl_observation(
        "terraform.block",
        relative_path,
        metadata={
            "file_family": "tf",
            "block_type": block.block_type,
            "labels": list(block.labels),
        },
        name=".".join((block.block_type, *block.labels)),
        start_line=block.start_line,
        end_line=block.end_line,
        source_suffix=(
            f"terraform-block:{block.block_type}:"
            f"{_stable_text_sha256('|'.join(block.labels))[:16]}:{block.start_line}"
        ),
    )


def _terraform_hcl_observation(
    kind: str,
    relative_path: str,
    *,
    metadata: dict[str, Any],
    profile: str = TERRAFORM_HCL_PROFILE,
    confidence: str = "extracted",
    name: str | None = None,
    target: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    source_suffix: str | None = None,
) -> RawObservation:
    full_metadata = {
        "format": TERRAFORM_HCL_FORMAT,
        "profile": profile,
        **metadata,
    }
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{source_suffix or kind.replace('.', '-')}",
        path=relative_path,
        start_line=start_line,
        end_line=end_line if end_line is not None else start_line,
        name=name,
        target=target,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=full_metadata,
    )


def _terraform_hcl_reference_observations_from_attribute(
    relative_path: str,
    attribute: _TerraformHclAttribute | None,
    reference_kind: str,
    *,
    target_kind: str = "terraform.reference",
) -> list[RawObservation]:
    if attribute is None:
        return []
    observations: list[RawObservation] = []
    for reference in _terraform_hcl_reference_names(attribute.value):
        observations.append(
            _terraform_hcl_reference_observation(
                relative_path,
                reference_kind,
                reference,
                target=external_key(target_kind, reference),
                start_line=attribute.start_line,
            )
        )
        if len(observations) >= TERRAFORM_HCL_MAX_REFERENCES:
            observations.append(
                _terraform_hcl_parse_error_observation(
                    relative_path,
                    error_kind="terraform-reference-limit",
                    message="Terraform HCL reference limit reached",
                    start_line=attribute.start_line,
                    recovered=True,
                )
            )
            break
    return observations


def _terraform_hcl_reference_observation(
    relative_path: str,
    reference_kind: str,
    raw_value: str,
    *,
    target: str,
    start_line: int | None = None,
    redacted: bool = False,
) -> RawObservation:
    metadata = {
        "file_family": "tf",
        "reference_kind": reference_kind,
        "not_fetched": True,
        "redacted": redacted,
    }
    if not redacted:
        metadata["raw_value_summary"] = _terraform_hcl_bounded_string(raw_value)
    return _terraform_hcl_observation(
        "terraform.reference",
        relative_path,
        confidence="heuristic",
        metadata=metadata,
        target=target,
        start_line=start_line,
        source_suffix=(
            f"terraform-reference:{reference_kind}:"
            f"{_stable_text_sha256(raw_value)[:16]}"
        ),
    )


def _terraform_hcl_redaction_observation(
    relative_path: str,
    *,
    redaction_reason: str,
    field_name: str | None = None,
    start_line: int | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "redaction_reason": redaction_reason,
        "redacted": True,
    }
    if field_name is not None:
        metadata["field_name"] = field_name
    return _terraform_hcl_observation(
        "terraform.redaction",
        relative_path,
        confidence="heuristic",
        metadata=metadata,
        start_line=start_line,
        source_suffix=(
            f"terraform-redaction:{redaction_reason}:"
            f"{_stable_text_sha256(field_name or 'document')[:16]}:"
            f"{start_line or 'document'}"
        ),
    )


def _terraform_hcl_parse_error_observation(
    relative_path: str,
    *,
    error_kind: str,
    message: str,
    start_line: int | None = None,
    recovered: bool,
) -> RawObservation:
    return _terraform_hcl_observation(
        "terraform.parse_error",
        relative_path,
        confidence="unknown",
        metadata={
            "file_family": "tf",
            "parser": TERRAFORM_HCL_PARSER,
            "error_kind": error_kind,
            "message_summary": message[:120],
            "recovered": recovered,
        },
        start_line=start_line,
        source_suffix=f"terraform-parse-error:{error_kind}:{start_line or 'document'}",
    )


def _terraform_hcl_attribute_redactions(
    relative_path: str,
    attributes: list[_TerraformHclAttribute],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for attribute in attributes:
        literal = _terraform_hcl_literal_string(attribute.value)
        if _is_secret_key(attribute.name):
            observations.append(
                _terraform_hcl_redaction_observation(
                    relative_path,
                    redaction_reason="secret-prone-terraform-attribute",
                    field_name=attribute.name,
                    start_line=attribute.start_line,
                )
            )
        elif literal is not None and _terraform_hcl_credentialed_url(literal):
            observations.append(
                _terraform_hcl_redaction_observation(
                    relative_path,
                    redaction_reason="credentialed-terraform-url",
                    field_name=attribute.name,
                    start_line=attribute.start_line,
                )
            )
    return observations


def _terraform_hcl_top_level_attributes(
    relative_path: str,
    content: str,
    *,
    base_line: int,
) -> tuple[list[_TerraformHclAttribute], list[RawObservation]]:
    attributes: list[_TerraformHclAttribute] = []
    diagnostics: list[RawObservation] = []
    lines = content.splitlines()
    nested_block_depth = 0
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped_line = _terraform_hcl_strip_comment(raw_line).strip()
        line_number = base_line + index
        if not stripped_line:
            index += 1
            continue
        if nested_block_depth > 0:
            nested_block_depth += _terraform_hcl_brace_delta(raw_line)
            nested_block_depth = max(nested_block_depth, 0)
            index += 1
            continue
        match = TERRAFORM_HCL_ATTRIBUTE_PATTERN.match(stripped_line)
        if match is None:
            block_match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped_line)
            if block_match is not None:
                nested_block_depth += _terraform_hcl_brace_delta(raw_line)
                nested_block_depth = max(nested_block_depth, 0)
            index += 1
            continue
        if len(attributes) >= TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK:
            diagnostics.append(
                _terraform_hcl_parse_error_observation(
                    relative_path,
                    error_kind="terraform-attribute-limit",
                    message="Terraform HCL attribute limit reached",
                    start_line=line_number,
                    recovered=True,
                )
            )
            break
        name = match.group("name")
        value_lines = [match.group("value")]
        depth = _terraform_hcl_collection_delta(match.group("value"))
        index += 1
        while index < len(lines) and depth > 0:
            continuation = lines[index]
            value_lines.append(continuation.strip())
            depth += _terraform_hcl_collection_delta(continuation)
            index += 1
        attributes.append(
            _TerraformHclAttribute(
                name=name,
                value="\n".join(value_lines).strip(),
                start_line=line_number,
            )
        )
    return attributes, diagnostics[:TERRAFORM_HCL_MAX_DIAGNOSTICS]


def _terraform_hcl_labels(label_text: str) -> tuple[str, ...]:
    return tuple(
        bytes(match.group(1), "utf-8").decode("unicode_escape")
        for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', label_text)
    )


def _terraform_hcl_brace_delta(line: str) -> int:
    return _terraform_hcl_delimiter_delta(line, openings="{", closings="}")


def _terraform_hcl_collection_delta(line: str) -> int:
    return _terraform_hcl_delimiter_delta(line, openings="{[(", closings="}])")


def _terraform_hcl_delimiter_delta(
    line: str,
    *,
    openings: str,
    closings: str,
) -> int:
    stripped = _terraform_hcl_strip_comment(line)
    depth = 0
    in_string = False
    escape = False
    for character in stripped:
        if escape:
            escape = False
            continue
        if character == "\\" and in_string:
            escape = True
            continue
        if character == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if character in openings:
            depth += 1
        elif character in closings:
            depth -= 1
    return depth


def _terraform_hcl_strip_comment(line: str) -> str:
    in_string = False
    escape = False
    index = 0
    while index < len(line):
        character = line[index]
        if escape:
            escape = False
            index += 1
            continue
        if character == "\\" and in_string:
            escape = True
            index += 1
            continue
        if character == '"':
            in_string = not in_string
            index += 1
            continue
        if not in_string and character == "#":
            return line[:index]
        if not in_string and line[index : index + 2] == "//":
            return line[:index]
        index += 1
    return line


def _terraform_hcl_nested_block_body(content: str, block_type: str) -> str | None:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is None or match.group("block_type") != block_type:
            continue
        depth = _terraform_hcl_brace_delta(line)
        body_lines: list[str] = []
        index += 1
        while index < len(lines) and depth > 0:
            nested_line = lines[index]
            depth += _terraform_hcl_brace_delta(nested_line)
            if depth > 0:
                body_lines.append(nested_line)
            index += 1
        return "\n".join(body_lines)
    return None


def _terraform_hcl_nested_block_labels(content: str, block_type: str) -> tuple[str, ...]:
    labels: list[str] = []
    for line in content.splitlines():
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is None or match.group("block_type") != block_type:
            continue
        block_labels = _terraform_hcl_labels(match.group("labels"))
        if block_labels:
            labels.append(block_labels[0])
    return tuple(labels)


def _terraform_hcl_nested_block_count(content: str, block_type: str) -> int:
    count = 0
    for line in content.splitlines():
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is not None and match.group("block_type") == block_type:
            count += 1
    return count


def _terraform_hcl_collection_body(value: str) -> str | None:
    stripped = value.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    return stripped[1:-1]


def _terraform_hcl_module_source(
    relative_path: str,
    source: str,
) -> tuple[dict[str, Any], str, str]:
    if _terraform_hcl_credentialed_url(source):
        return (
            {
                "source_kind": "remote",
                "not_fetched": True,
                "redacted": True,
                "redaction_reason": "credentialed-terraform-module-source",
            },
            external_key("terraform.module", "redacted-module-source"),
            "module_source",
        )
    local_target = _terraform_hcl_local_path_target(relative_path, source)
    if local_target is not None:
        return (
            {
                "source_kind": "local",
                "source_summary": _terraform_hcl_bounded_string(source),
                "not_fetched": True,
            },
            local_target,
            "module_source_local",
        )
    return (
        {
            "source_kind": "remote",
            "source_summary": _terraform_hcl_bounded_string(source),
            "not_fetched": True,
        },
        external_key("terraform.module", source),
        "module_source",
    )


def _terraform_hcl_local_path_target(relative_path: str, source: str) -> str | None:
    if source.startswith("/") or _is_url(source) or source.startswith(("git::", "ssh://")):
        return None
    if not (source.startswith("./") or source.startswith("../")):
        return None
    base_dir = PurePosixPath(relative_path).parent
    candidate = posixpath.normpath((base_dir / source).as_posix())
    if candidate == "." or candidate.startswith("../") or candidate == "..":
        return unknown_key("file", "repo-escaping-terraform-module-source")
    if PurePosixPath(candidate).is_absolute():
        return unknown_key("file", "repo-escaping-terraform-module-source")
    return file_key(candidate)


def _terraform_hcl_reference_names(value: str) -> tuple[str, ...]:
    names = []
    for match in TERRAFORM_HCL_TRAVERSAL_PATTERN.finditer(value):
        names.append(match.group(0))
    return tuple(dict.fromkeys(names))


def _terraform_hcl_literal_string(value: str) -> str | None:
    stripped = value.strip()
    match = re.match(r'^"((?:[^"\\]|\\.)*)"$', stripped, flags=re.DOTALL)
    if match is None:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape")


def _terraform_hcl_bool_literal(value: str) -> bool | None:
    stripped = value.strip().lower()
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    return None


def _terraform_hcl_value_type(value: str) -> str:
    kind = _terraform_hcl_expression_kind(value)
    if kind == "literal_string":
        return "string"
    if kind == "literal_number":
        return "number"
    if kind == "literal_bool":
        return "boolean"
    if kind == "literal_null":
        return "null"
    stripped = value.strip()
    if stripped.startswith("{"):
        return "object"
    if stripped.startswith("["):
        return "array"
    return "expression"


def _terraform_hcl_expression_kind(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "unknown"
    literal = _terraform_hcl_literal_string(stripped)
    if literal is not None:
        if "${" in literal:
            return "template_interpolation"
        return "literal_string"
    lowered = stripped.lower()
    if lowered in ("true", "false"):
        return "literal_bool"
    if lowered == "null":
        return "literal_null"
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", stripped):
        return "literal_number"
    if stripped.startswith(("{", "[")):
        return "collection_shape"
    if "${" in stripped:
        return "template_interpolation"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(", stripped):
        return "function_call"
    if "?" in stripped and ":" in stripped:
        return "conditional"
    if TERRAFORM_HCL_TRAVERSAL_PATTERN.fullmatch(stripped):
        return "traversal_reference"
    if "dynamic " in stripped or stripped.startswith("dynamic"):
        return "dynamic_block"
    return "unknown"


def _terraform_hcl_expression_summary(value: str) -> str:
    kind = _terraform_hcl_expression_kind(value)
    if kind in (
        "literal_string",
        "literal_number",
        "literal_bool",
        "literal_null",
        "traversal_reference",
    ):
        literal = _terraform_hcl_literal_string(value)
        if literal is not None:
            return _terraform_hcl_bounded_string(literal)
        return _terraform_hcl_bounded_string(value.strip())
    return kind


def _terraform_hcl_text_presence_metadata(key: str, value: str) -> dict[str, Any]:
    literal = _terraform_hcl_literal_string(value)
    text = literal if literal is not None else value.strip()
    return {
        f"{key}_present": True,
        f"{key}_length": len(text),
        f"{key}_sha256": _stable_text_sha256(text),
    }


def _terraform_hcl_credentialed_url(value: str) -> bool:
    candidate = value.removeprefix("git::")
    parsed = urlsplit(candidate)
    if parsed.scheme in ("http", "https", "ssh", "git") and (
        parsed.username is not None or parsed.password is not None
    ):
        return True
    return bool(re.search(r"://[^/\s:@]+:[^/\s@]+@", candidate))


def _terraform_hcl_bounded_string(value: str) -> str:
    if len(value) <= TERRAFORM_HCL_MAX_METADATA_STRING and all(
        character.isprintable() for character in value
    ):
        return value
    return f"<string:{len(value)}>"


def _is_terraform_hcl_file_name(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name.lower()
    return name.endswith(".tf") and not name.endswith(".tf.json")


def _is_terraform_tfvars_hcl_file_name(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name.lower()
    return (
        name == "terraform.tfvars"
        or name.endswith(".auto.tfvars")
        or (name.endswith(".tfvars") and not name.endswith(".tfvars.json"))
    )


def _kubernetes_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    observations = [
        _profile_observation(
            "kubernetes.resource",
            relative_path,
            profile="kubernetes_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "api_version": _safe_value_summary(value.get("apiVersion")),
                "kind": _safe_value_summary(value.get("kind")),
                "name": _safe_value_summary(metadata.get("name")),
                "namespace": _safe_value_summary(metadata.get("namespace")),
            },
            name=str(metadata.get("name") or value.get("kind") or "resource"),
            source_suffix=(
                f"kubernetes-resource:{value.get('kind')}:"
                f"{metadata.get('name') or 'unnamed'}"
            ),
        )
    ]
    observations.extend(
        _docker_image_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence="heuristic",
            profile="kubernetes_json",
        )
    )
    return observations


def _argocd_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    spec = value.get("spec") if isinstance(value.get("spec"), dict) else {}
    source = spec.get("source") if isinstance(spec.get("source"), dict) else {}
    return [
        _profile_observation(
            "argocd.application",
            relative_path,
            profile="argocd_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "kind": _safe_value_summary(value.get("kind")),
                "name": _safe_value_summary(metadata.get("name")),
                "repo_url_summary": _safe_value_summary(source.get("repoURL")),
                "path_summary": _safe_value_summary(source.get("path")),
                "target_revision_summary": _safe_value_summary(
                    source.get("targetRevision")
                ),
                "not_fetched": True,
            },
            name=str(metadata.get("name") or "argocd-application"),
            target=(
                external_url_key(source["repoURL"])
                if isinstance(source.get("repoURL"), str) and _is_url(source["repoURL"])
                else None
            ),
            source_suffix=f"argocd-application:{metadata.get('name') or 'unnamed'}",
        )
    ]


def _liquibase_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    changelog = value.get("databaseChangeLog")
    entries = changelog if isinstance(changelog, list) else []
    observations = [
        _profile_observation(
            "liquibase.changelog",
            relative_path,
            profile="liquibase_json",
            format_name=format_name,
            confidence=confidence,
            metadata={"changeset_count": _liquibase_changeset_count(entries)},
            source_suffix="liquibase-changelog",
        )
    ]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("changeSet"), dict):
            continue
        changeset = entry["changeSet"]
        observations.append(
            _profile_observation(
                "liquibase.changeset",
                relative_path,
                profile="liquibase_json",
                format_name=format_name,
                confidence=confidence,
                metadata={
                    "changeset_id": _safe_value_summary(changeset.get("id")),
                    "author": _safe_value_summary(changeset.get("author")),
                    "context": _safe_value_summary(changeset.get("context")),
                    "labels": _safe_value_summary(changeset.get("labels")),
                },
                name=str(changeset.get("id") or index),
                source_suffix=f"liquibase-changeset:{index}",
            )
        )
    return observations


def _liquibase_changeset_count(entries: list[Any]) -> int:
    return sum(
        1
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("changeSet"), dict)
    )


def _docker_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
) -> list[RawObservation]:
    return list(
        _docker_image_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
            profile=profile,
        )
    )


def _docker_image_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for pointer, image in _json_image_values(value):
        observations.append(
            _profile_observation(
                "docker.reference",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    "reference_kind": "docker.image",
                    "pointer": pointer,
                    "image_summary": _safe_value_summary(image),
                    "not_fetched": True,
                },
                target=external_key("docker.image", image),
                source_suffix=f"docker-reference:{pointer}",
            )
        )
    return tuple(observations)


def _json_image_values(value: Any) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []

    def walk(current: Any, segments: tuple[str, ...]) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                child_segments = (*segments, str(key))
                if (
                    _normalized_key(str(key)) == "image"
                    and isinstance(child, str)
                    and _looks_like_container_image(child)
                ):
                    result.append((json_pointer(child_segments), child))
                walk(child, child_segments)
        elif isinstance(current, list):
            for index, child in enumerate(current):
                walk(child, (*segments, str(index)))

    walk(value, ())
    return tuple(result)


def _is_argocd_json_document(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and str(value.get("apiVersion", "")).startswith("argoproj.io/")
        and value.get("kind") in ("Application", "ApplicationSet")
    )


def _is_liquibase_json_document(value: Any) -> bool:
    return isinstance(value, dict) and "databaseChangeLog" in value


def _safe_selected_metadata(
    value: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in keys:
        item = value.get(key)
        if _is_secret_key(key):
            metadata[f"{key}_redacted"] = True
            continue
        summary = _safe_value_summary(item)
        if summary is not None:
            metadata[key] = summary
        elif isinstance(item, (dict, list)):
            metadata[f"{key}_type"] = _value_type(item)
            metadata[f"{key}_shape"] = _value_shape(item)
    return metadata


def _script_is_secret_prone(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = _normalized_key(value)
    if any(marker in normalized for marker in ("token", "secret", "password", "credential")):
        return True
    return bool(re.search(r"\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY)=", value))


def _script_command_summary(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "<empty-script>"
    first = stripped.split()[0]
    if "=" in first and len(stripped.split()) > 1:
        first = stripped.split()[1]
    if _is_clear_command_name(first):
        return first
    return "<script-command>"


def _value_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "key_count": len(value)}
    if isinstance(value, list):
        return {"type": "array", "item_count": len(value)}
    return {"type": _value_type(value)}


def _yaml_documents(value: Any, *, document_count: int) -> tuple[Any, ...]:
    if (
        document_count > 1
        and isinstance(value, dict)
        and isinstance(value.get("documents"), dict)
    ):
        documents = value["documents"]
        return tuple(documents[str(index)] for index in range(document_count))
    return (value,)


def _is_openapi_document(value: Any) -> bool:
    return isinstance(value, dict) and (
        "openapi" in value
        or "swagger" in value
        or ("paths" in value and "components" in value)
    )


def _is_openapi_file_name(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name.lower()
    return name in (
        "openapi.json",
        "openapi.yaml",
        "openapi.yml",
        "swagger.json",
        "swagger.yaml",
        "swagger.yml",
    ) or name.endswith(
        (
            ".openapi.json",
            ".openapi.yaml",
            ".openapi.yml",
            ".swagger.json",
            ".swagger.yaml",
            ".swagger.yml",
        )
    )


def _is_kubernetes_document(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "apiVersion" in value
        and "kind" in value
        and isinstance(value.get("metadata"), dict)
    )


def _is_docker_compose_document(value: Any) -> bool:
    return isinstance(value, dict) and "services" in value and (
        "networks" in value or "volumes" in value or "secrets" in value
    )


def _is_grafana_document(value: Any) -> bool:
    return isinstance(value, dict) and (
        "datasources" in value or "dashboards" in value or "secureJsonData" in value
    )


def _apply_yaml_profile_metadata(
    value: Any,
    metadata_overrides: dict[str, dict[str, Any]],
    *,
    profile: str,
    document_count: int,
) -> None:
    for pointer, path_value in _yaml_pointer_values(value):
        metadata = metadata_overrides.setdefault(pointer, {})
        metadata["profile"] = profile
        if document_count > 1:
            document_index = _yaml_document_index_from_pointer(pointer)
            if document_index is not None:
                metadata["document_index"] = document_index
        if _yaml_pointer_is_redacted(
            pointer,
            path_value=path_value,
            root_value=value,
            profile=profile,
        ):
            metadata["redacted"] = True
            metadata.setdefault("redaction_reason", _yaml_redaction_reason(pointer, profile))
    _apply_yaml_stable_array_metadata(value, metadata_overrides)


def _apply_yaml_stable_array_metadata(
    value: Any,
    metadata_overrides: dict[str, dict[str, Any]],
) -> None:
    def walk(
        current: Any,
        segments: tuple[str, ...],
        active_stable_keys: tuple[str, ...],
    ) -> None:
        if segments and active_stable_keys:
            metadata_overrides.setdefault(json_pointer(segments), {}).setdefault(
                "stable_member_keys",
                list(active_stable_keys),
            )
        if isinstance(current, dict):
            for key, child in current.items():
                walk(child, (*segments, str(key)), active_stable_keys)
            return
        if isinstance(current, list):
            stable_members = _stable_array_members(current)
            if not stable_members:
                return
            stable_keys = tuple(sorted({member.key for member in stable_members}))
            for member in stable_members:
                walk(member.value, (*segments, member.segment), stable_keys)

    walk(value, (), ())


def _yaml_pointer_values(value: Any) -> tuple[tuple[str, Any], ...]:
    result: list[tuple[str, Any]] = []

    def walk(current: Any, segments: tuple[str, ...]) -> None:
        if segments:
            result.append((json_pointer(segments), current))
        if isinstance(current, dict):
            for key, child in current.items():
                walk(child, (*segments, str(key)))
        elif isinstance(current, list):
            for member in _stable_array_members(current):
                walk(member.value, (*segments, member.segment))

    walk(value, ())
    return tuple(result)


def _yaml_document_index_from_pointer(pointer: str) -> int | None:
    segments = _pointer_segments(pointer)
    if len(segments) >= 2 and segments[0] == "documents" and segments[1].isdigit():
        return int(segments[1])
    return None


def _yaml_pointer_is_redacted(
    pointer: str,
    *,
    path_value: Any,
    root_value: Any,
    profile: str,
) -> bool:
    segments = _pointer_segments(pointer)
    normalized_segments = tuple(_normalized_key(segment) for segment in segments)
    if _is_secret_pointer(pointer):
        return True
    if any(segment in ("securejsondata", "dockerconfigjson") for segment in normalized_segments):
        return True
    if profile == "kubernetes" and _yaml_pointer_is_kubernetes_secret_data(pointer, root_value):
        return True
    if profile == "github_actions" and "secrets" in normalized_segments:
        return True
    if profile == "grafana" and "securejsondata" in normalized_segments:
        return True
    if profile == "openapi" and _openapi_pointer_is_redacted(pointer, path_value):
        return True
    return _looks_like_secret_scalar(path_value)


def _yaml_pointer_is_kubernetes_secret_data(pointer: str, root_value: Any) -> bool:
    segments = _pointer_segments(pointer)
    if "data" not in segments and "stringData" not in segments:
        return False
    if len(segments) >= 2 and segments[0] == "documents" and segments[1].isdigit():
        document = root_value.get("documents", {}).get(segments[1]) if isinstance(root_value, dict) else None
    else:
        document = root_value
    return isinstance(document, dict) and document.get("kind") == "Secret"


def _yaml_redaction_reason(pointer: str, profile: str) -> str:
    if profile == "kubernetes" and (
        "/data/" in pointer or "/stringData/" in pointer
    ):
        return "secret-prone-yaml-path"
    if _is_secret_pointer(pointer):
        return "secret-prone-yaml-path"
    return "secret-prone-yaml-context"


def _looks_like_secret_scalar(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if "-----BEGIN " in stripped and "PRIVATE KEY-----" in stripped:
        return True
    if len(stripped) >= 32 and re.fullmatch(r"[A-Za-z0-9_./+=:-]+", stripped):
        markers = ("token", "secret", "password", "key")
        return any(marker in stripped.lower() for marker in markers)
    return False


def _extract_plist_xml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        _check_safe_plist_xml(content)
        root = ElementTree.fromstring(content)
        parsed = _plist_root_value(root)
    except PlistXmlSafetyError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name=PLIST_XML_FORMAT,
                error_kind="unsafe-xml-construct",
                message=str(error),
                recovered=False,
            ),
        )
    except ElementTree.ParseError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name=PLIST_XML_FORMAT,
                error_kind="malformed-plist-xml",
                message=str(error),
                start_line=_xml_parse_error_line(error),
                recovered=False,
            ),
        )
    except PlistXmlParseError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name=PLIST_XML_FORMAT,
                error_kind="unsupported-plist-shape",
                message=str(error),
                recovered=False,
            ),
        )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name=PLIST_XML_FORMAT,
        confidence="extracted",
        content=content,
    )
    document = _document_observation(
        relative_path,
        format_name=PLIST_XML_FORMAT,
        parser=_parser_name(PLIST_XML_FORMAT),
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
    )
    return (document, *path_observations, *reference_observations)


def _extract_generic_xml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        _check_safe_generic_xml(content)
        root = ElementTree.fromstring(content)
    except GenericXmlSafetyError as error:
        return (
            _xml_parse_error_observation(
                relative_path,
                error_kind="unsafe-xml-construct",
                message=str(error),
                recovered=False,
            ),
        )
    except ElementTree.ParseError as error:
        return (
            _xml_parse_error_observation(
                relative_path,
                error_kind="malformed-xml",
                message=str(error),
                start_line=_xml_parse_error_line(error),
                recovered=False,
            ),
        )

    namespaces = _xml_namespace_summary(content)
    root_parts = _xml_name_parts(root.tag)
    document_role = _generic_xml_document_role(relative_path, root, namespaces)
    elements: list[RawObservation] = []
    attributes: list[RawObservation] = []
    references: list[RawObservation] = []
    _walk_xml_element(
        relative_path,
        root,
        pointer=f"/{root_parts['local_name']}",
        document_role=document_role,
        content=content,
        elements=elements,
        attributes=attributes,
        references=references,
    )
    document = RawObservation(
        kind="xml.document",
        source_id=f"{relative_path}#xml-document",
        path=relative_path,
        target=xml_document_key(relative_path),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "format": GENERIC_XML_FORMAT,
            "parser": _parser_name(GENERIC_XML_FORMAT),
            "safety_mode": GENERIC_XML_SAFETY_MODE,
            "root_tag": root_parts["display_name"],
            "root_local_name": root_parts["local_name"],
            "root_namespace_uri": root_parts.get("namespace_uri"),
            "namespace_summary": namespaces,
            "document_role": document_role,
            "parse_error_count": 0,
            "element_count": len(elements),
            "attribute_count": len(attributes),
            "reference_count": len(references),
        },
    )
    return (document, *elements, *attributes, *references)


def _looks_like_plist_xml(content: str) -> bool:
    return bool(PLIST_ROOT_PATTERN.search(content))


def _check_safe_plist_xml(content: str) -> None:
    if UNSAFE_XML_DECLARATION_PATTERN.search(content):
        raise PlistXmlSafetyError(
            "doctype and entity declarations are not supported"
        )
    if UNSAFE_PROCESSING_INSTRUCTION_PATTERN.search(content):
        raise PlistXmlSafetyError(
            "non-XML processing instructions are not supported"
        )


def _check_safe_generic_xml(content: str) -> None:
    if UNSAFE_XML_DECLARATION_PATTERN.search(content):
        raise GenericXmlSafetyError(
            "doctype and entity declarations are not supported"
        )
    if UNSAFE_PROCESSING_INSTRUCTION_PATTERN.search(content):
        raise GenericXmlSafetyError(
            "non-XML processing instructions are not supported"
        )


def _xml_parse_error_line(error: ElementTree.ParseError) -> int | None:
    position = getattr(error, "position", None)
    if isinstance(position, tuple) and position:
        line = position[0]
        if isinstance(line, int) and line > 0:
            return line
    return None


def _plist_root_value(root: ElementTree.Element) -> Any:
    if _xml_local_name(root.tag) != "plist":
        raise PlistXmlParseError("root element is not plist")
    children = list(root)
    if len(children) != 1:
        raise PlistXmlParseError("plist root must contain exactly one value element")
    return _plist_value(children[0])


def _plist_value(element: ElementTree.Element) -> Any:
    tag = _xml_local_name(element.tag)
    if tag == "dict":
        return _plist_dict(element)
    if tag == "array":
        return [_plist_value(child) for child in element]
    if tag in ("string", "date", "data"):
        return (element.text or "").strip()
    if tag == "integer":
        text = (element.text or "").strip()
        try:
            return int(text)
        except ValueError as error:
            raise PlistXmlParseError("integer value is malformed") from error
    if tag == "real":
        text = (element.text or "").strip()
        try:
            return float(text)
        except ValueError as error:
            raise PlistXmlParseError("real value is malformed") from error
    if tag == "true":
        return True
    if tag == "false":
        return False
    raise PlistXmlParseError(f"unsupported plist value element: {tag}")


def _plist_dict(element: ElementTree.Element) -> dict[str, Any]:
    children = list(element)
    result: dict[str, Any] = {}
    index = 0
    while index < len(children):
        key_element = children[index]
        if _xml_local_name(key_element.tag) != "key":
            raise PlistXmlParseError("dict entries must begin with key elements")
        key = (key_element.text or "").strip()
        if not key:
            raise PlistXmlParseError("dict key must not be empty")
        index += 1
        if index >= len(children):
            raise PlistXmlParseError("dict key is missing a value element")
        if key in result:
            raise PlistXmlParseError("duplicate dict keys are not supported")
        value_element = children[index]
        if _xml_local_name(value_element.tag) == "key":
            raise PlistXmlParseError("dict key is missing a value element")
        result[key] = _plist_value(value_element)
        index += 1
    return result


def _xml_local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def _xml_name_parts(name: str) -> dict[str, str]:
    if name.startswith("{"):
        namespace_uri, local_name = name[1:].split("}", 1)
        return {
            "display_name": local_name,
            "local_name": local_name,
            "namespace_uri": namespace_uri,
        }
    return {"display_name": name, "local_name": name}


def _xml_attribute_parts(name: str) -> dict[str, str]:
    parts = _xml_name_parts(name)
    namespace_uri = parts.get("namespace_uri")
    if namespace_uri == "http://www.w3.org/2001/XMLSchema-instance":
        parts["display_name"] = f"xsi:{parts['local_name']}"
    return parts


def _xml_namespace_summary(content: str) -> list[dict[str, str]]:
    namespace_pattern = re.compile(
        r"\sxmlns(?::(?P<prefix>[A-Za-z_][\w.-]*))?=\"(?P<uri>[^\"]+)\""
    )
    summary = []
    seen: set[tuple[str, str]] = set()
    for match in namespace_pattern.finditer(content):
        prefix = match.group("prefix") or ""
        uri = match.group("uri")
        key = (prefix, uri)
        if key in seen:
            continue
        seen.add(key)
        summary.append({"prefix": prefix, "uri": uri})
    return summary


def _generic_xml_document_role(
    relative_path: str,
    root: ElementTree.Element,
    namespaces: list[dict[str, str]],
) -> str:
    root_local = _xml_local_name(root.tag)
    namespace_uris = {item["uri"] for item in namespaces}
    path = PurePosixPath(relative_path)
    if path.name == "pom.xml" or (
        root_local == "project"
        and "http://maven.apache.org/POM/4.0.0" in namespace_uris
    ):
        return "maven-pom"
    if root_local == "beans" or any(
        uri.startswith("http://www.springframework.org/schema/")
        for uri in namespace_uris
    ):
        return "spring-config"
    if path.suffix == ".xml":
        return "xml-config"
    return "config"


def _walk_xml_element(
    relative_path: str,
    element: ElementTree.Element,
    *,
    pointer: str,
    document_role: str,
    content: str,
    elements: list[RawObservation],
    attributes: list[RawObservation],
    references: list[RawObservation],
) -> None:
    parts = _xml_name_parts(element.tag)
    local_name = parts["local_name"]
    redacted = _is_secret_xml_element(element)
    element_key = xml_element_key(relative_path, pointer)
    metadata = _xml_element_metadata(
        element,
        pointer=pointer,
        document_role=document_role,
        redacted=redacted,
    )
    elements.append(
        RawObservation(
            kind="xml.element",
            source_id=f"{relative_path}#xml-element:{pointer}",
            path=relative_path,
            name=pointer,
            target=element_key,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata=metadata,
        )
    )
    text = (element.text or "").strip()
    if text:
        references.extend(
            _xml_reference_observations(
                relative_path,
                value=text,
                key_context=local_name,
                source_key=element_key,
                source_kind="xml.element",
                pointer=pointer,
                attribute_name=None,
                redacted=redacted,
            )
        )
    for attr_name, attr_value in sorted(element.attrib.items()):
        attr_parts = _xml_attribute_parts(attr_name)
        attr_display_name = attr_parts["display_name"]
        attr_redacted = redacted or _is_secret_key(attr_display_name)
        semantic_key = _xml_attribute_semantic_key(
            attr_display_name,
            element,
            element_local_name=local_name,
        )
        attr_key = xml_attribute_key(relative_path, pointer, attr_display_name)
        attr_metadata = _xml_attribute_metadata(
            attr_value,
            attr_parts=attr_parts,
            pointer=pointer,
            semantic_key=semantic_key,
            redacted=attr_redacted,
        )
        attributes.append(
            RawObservation(
                kind="xml.attribute",
                source_id=(
                    f"{relative_path}#xml-attribute:{pointer}:{attr_display_name}"
                ),
                path=relative_path,
                name=attr_display_name,
                target=attr_key,
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=attr_metadata,
            )
        )
        references.extend(
            _xml_reference_observations(
                relative_path,
                value=attr_value,
                key_context=semantic_key,
                source_key=attr_key,
                source_kind="xml.attribute",
                pointer=pointer,
                attribute_name=attr_display_name,
                redacted=attr_redacted,
            )
        )
    for child, child_pointer in _xml_child_pointers(element, pointer):
        _walk_xml_element(
            relative_path,
            child,
            pointer=child_pointer,
            document_role=document_role,
            content=content,
            elements=elements,
            attributes=attributes,
            references=references,
        )


def _xml_child_pointers(
    element: ElementTree.Element,
    parent_pointer: str,
) -> tuple[tuple[ElementTree.Element, str], ...]:
    children = list(element)
    totals: dict[str, int] = {}
    for child in children:
        local = _xml_local_name(child.tag)
        totals[local] = totals.get(local, 0) + 1
    seen: dict[str, int] = {}
    result = []
    for child in children:
        local = _xml_local_name(child.tag)
        seen[local] = seen.get(local, 0) + 1
        segment = local if seen[local] == 1 else f"{local}[{seen[local]}]"
        result.append((child, f"{parent_pointer}/{segment}"))
    return tuple(result)


def _xml_element_metadata(
    element: ElementTree.Element,
    *,
    pointer: str,
    document_role: str,
    redacted: bool,
) -> dict[str, Any]:
    parts = _xml_name_parts(element.tag)
    children = list(element)
    metadata: dict[str, Any] = {
        "format": GENERIC_XML_FORMAT,
        "parser": _parser_name(GENERIC_XML_FORMAT),
        "safety_mode": GENERIC_XML_SAFETY_MODE,
        "element_name": parts["display_name"],
        "local_name": parts["local_name"],
        "xml_pointer": pointer,
        "attribute_count": len(element.attrib),
        "child_count": len(children),
        "identity_mode": "structural-document",
        "role_hint": _xml_role_hint(element, document_role=document_role),
        "redacted": redacted,
    }
    if "namespace_uri" in parts:
        metadata["namespace_uri"] = parts["namespace_uri"]
    if redacted:
        metadata["redaction_reason"] = "secret-prone-key"
    else:
        text = (element.text or "").strip()
        if text and not _is_placeholder_heavy(text):
            summary = _safe_value_summary(text)
            if summary is not None:
                metadata["text_summary"] = summary
    metadata.update(_xml_domain_metadata(element, document_role=document_role))
    return metadata


def _xml_attribute_metadata(
    value: str,
    *,
    attr_parts: dict[str, str],
    pointer: str,
    semantic_key: str,
    redacted: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "format": GENERIC_XML_FORMAT,
        "parser": _parser_name(GENERIC_XML_FORMAT),
        "safety_mode": GENERIC_XML_SAFETY_MODE,
        "element_pointer": pointer,
        "attribute_name": attr_parts["display_name"],
        "local_name": attr_parts["local_name"],
        "semantic_key": semantic_key,
        "value_type": "string",
        "redacted": redacted,
    }
    if "namespace_uri" in attr_parts:
        metadata["namespace_uri"] = attr_parts["namespace_uri"]
    if redacted:
        metadata["redaction_reason"] = "secret-prone-key"
        return metadata
    summary = _safe_value_summary(value)
    if summary is not None:
        metadata["value_summary"] = summary
    return metadata


def _xml_role_hint(
    element: ElementTree.Element,
    *,
    document_role: str,
) -> str:
    local = _xml_local_name(element.tag)
    if document_role == "spring-config":
        if local == "bean":
            return "spring-bean"
        if local == "property":
            return "spring-property"
    if document_role == "maven-pom":
        if local == "dependency":
            return "maven-dependency"
        if local == "plugin":
            return "maven-plugin"
        if _xml_parentish_property_name(local):
            return "maven-property"
    return "unknown"


def _xml_domain_metadata(
    element: ElementTree.Element,
    *,
    document_role: str,
) -> dict[str, Any]:
    local = _xml_local_name(element.tag)
    metadata: dict[str, Any] = {}
    if document_role == "spring-config" and local == "bean":
        bean_id = element.attrib.get("id")
        class_name = element.attrib.get("class")
        if bean_id:
            metadata["bean_id"] = bean_id
        if class_name:
            metadata["class_name"] = class_name
    if document_role == "spring-config" and local == "property":
        property_name = element.attrib.get("name")
        ref = element.attrib.get("ref")
        if property_name:
            metadata["property_name"] = property_name
        if ref:
            metadata["bean_ref"] = ref
    if document_role == "maven-pom" and local in ("project", "dependency", "plugin"):
        child_values = _xml_direct_child_texts(element)
        if "groupId" in child_values:
            metadata["maven_group_id"] = child_values["groupId"]
        if "artifactId" in child_values:
            metadata["maven_artifact_id"] = child_values["artifactId"]
        if "version" in child_values:
            metadata["maven_version"] = child_values["version"]
    return metadata


def _xml_direct_child_texts(element: ElementTree.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        local = _xml_local_name(child.tag)
        text = (child.text or "").strip()
        if text and local not in values and not _is_secret_key(local):
            values[local] = text
    return values


def _xml_parentish_property_name(local_name: str) -> bool:
    return local_name not in (
        "project",
        "modelVersion",
        "groupId",
        "artifactId",
        "version",
        "dependencies",
        "dependency",
        "build",
        "plugins",
        "plugin",
    )


def _xml_attribute_semantic_key(
    attr_name: str,
    element: ElementTree.Element,
    *,
    element_local_name: str,
) -> str:
    semantic_parts = [attr_name, element_local_name]
    xml_name_attr = element.attrib.get("name")
    if isinstance(xml_name_attr, str) and xml_name_attr.strip():
        semantic_parts.append(xml_name_attr)
    return "_".join(_normalized_key(part) for part in semantic_parts)


def _is_secret_xml_element(element: ElementTree.Element) -> bool:
    local = _xml_local_name(element.tag)
    if _is_secret_key(local):
        return True
    xml_name_attr = element.attrib.get("name")
    return isinstance(xml_name_attr, str) and _is_secret_key(xml_name_attr)


def _is_placeholder_heavy(value: str) -> bool:
    return "${" in value or "$(" in value or "{{" in value


def _xml_reference_observations(
    relative_path: str,
    *,
    value: str,
    key_context: str,
    source_key: str,
    source_kind: str,
    pointer: str,
    attribute_name: str | None,
    redacted: bool,
) -> tuple[RawObservation, ...]:
    references = _detect_xml_references(
        relative_path,
        key_context,
        value,
        redacted=redacted,
    )
    observations = []
    for ordinal, reference in enumerate(references):
        metadata: dict[str, Any] = {
            "format": GENERIC_XML_FORMAT,
            "parser": _parser_name(GENERIC_XML_FORMAT),
            "safety_mode": GENERIC_XML_SAFETY_MODE,
            "source_key": source_key,
            "source_kind": source_kind,
            "element_pointer": pointer,
            "reference_kind": reference["kind"],
            "redacted": reference["redacted"],
            "resolution_reason": reference["reason"],
        }
        if attribute_name is not None:
            metadata["attribute_name"] = attribute_name
        if "summary" in reference:
            metadata["raw_value_summary"] = reference["summary"]
        if reference["redacted"]:
            metadata["redaction_reason"] = "secret-prone-key"
        observations.append(
            RawObservation(
                kind="xml.reference",
                source_id=(
                    f"{relative_path}#xml-reference:{pointer}:"
                    f"{attribute_name or 'text'}:{ordinal}"
                ),
                path=relative_path,
                name=pointer,
                target=reference["target"],
                confidence="heuristic",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _detect_xml_references(
    relative_path: str,
    key_context: str,
    value: str,
    *,
    redacted: bool,
) -> tuple[dict[str, Any], ...]:
    stripped = value.strip()
    if not stripped:
        return ()
    references = []
    for token in stripped.split():
        if _is_url(token):
            references.append(
                _reference(
                    "external.url",
                    external_url_key(token),
                    "url-literal",
                    token,
                    redacted=redacted,
                )
            )
    if references:
        return tuple(references)
    env_placeholder = re.fullmatch(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}", stripped)
    if env_placeholder is not None:
        return (
            _reference(
                "env",
                env_key(env_placeholder.group(1)),
                "env-property-placeholder",
                stripped,
                redacted=redacted,
            ),
        )
    if re.fullmatch(r"\$\{[^}]+\}", stripped):
        return (
            _reference(
                "dynamic",
                dynamic_key("xml.property-placeholder", "spring-maven-property"),
                "dynamic-property-placeholder",
                stripped,
                redacted=redacted,
            ),
        )
    normalized_context = _normalized_key(key_context)
    if _looks_like_xml_file_key(normalized_context, stripped):
        return (_xml_file_reference(relative_path, stripped, redacted=redacted),)
    return ()


def _looks_like_xml_file_key(key_context: str, value: str) -> bool:
    if _is_url(value):
        return False
    if value.startswith(("./", "../", "/", "${", "~")):
        return True
    markers = ("path", "file", "resource", "location", "config", "directory")
    return "/" in value and any(marker in key_context for marker in markers)


def _xml_file_reference(
    relative_path: str,
    value: str,
    *,
    redacted: bool,
) -> dict[str, Any]:
    if _is_dynamic_value(value):
        return _reference(
            "dynamic",
            dynamic_key("file", "xml-reference-expanded-from-variable"),
            "dynamic-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("/"):
        return _reference(
            "external",
            external_key("file", "absolute-xml-reference"),
            "absolute-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("../"):
        resolved = _resolve_repo_path(relative_path, value)
        if resolved is None:
            return _reference(
                "unknown",
                unknown_key("file", "repo-escaping-xml-reference"),
                "repo-escaping-file-reference",
                value,
                redacted=redacted,
            )
        return _reference(
            "file",
            file_key(resolved),
            "relative-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("./"):
        resolved = _resolve_repo_path(relative_path, value)
    else:
        resolved = _normalize_repo_path(value)
    if resolved is None:
        return _reference(
            "unknown",
            unknown_key("file", "repo-escaping-xml-reference"),
            "repo-escaping-file-reference",
            value,
            redacted=redacted,
        )
    return _reference(
        "file",
        file_key(resolved),
        "relative-file-reference",
        value,
        redacted=redacted,
    )


def normalize_jsonc(content: str) -> str:
    without_comments = _strip_jsonc_comments(content)
    return _strip_jsonc_trailing_commas(without_comments)


def _strip_jsonc_comments(content: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(content):
        character = content[index]
        next_character = content[index + 1] if index + 1 < len(content) else ""
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == "/" and next_character == "/":
            output.extend((" ", " "))
            index += 2
            while index < len(content) and content[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if character == "/" and next_character == "*":
            output.extend((" ", " "))
            index += 2
            closed = False
            while index < len(content):
                if content[index] == "*" and index + 1 < len(content) and content[index + 1] == "/":
                    output.extend((" ", " "))
                    index += 2
                    closed = True
                    break
                output.append("\n" if content[index] in "\r\n" else " ")
                index += 1
            if not closed:
                raise JsoncNormalizationError("unterminated block comment")
            continue
        output.append(character)
        index += 1
    if in_string:
        raise JsoncNormalizationError("unterminated string")
    return "".join(output)


def _strip_jsonc_trailing_commas(content: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(content):
        character = content[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(content) and content[lookahead].isspace():
                lookahead += 1
            if lookahead < len(content) and content[lookahead] in "}]":
                index += 1
                continue
        output.append(character)
        index += 1
    return "".join(output)


def _structure_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str = "",
    line_offset: int = 0,
    metadata_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[tuple[RawObservation, ...], tuple[RawObservation, ...]]:
    paths: list[RawObservation] = []
    references: list[RawObservation] = []
    _walk_value(
        relative_path,
        value,
        pointer_segments=(),
        parent_type=None,
        format_name=format_name,
        confidence=confidence,
        content=content,
        source_suffix=source_suffix,
        line_offset=line_offset,
        metadata_overrides=metadata_overrides or {},
        paths=paths,
        references=references,
    )
    return tuple(paths), tuple(references)


def _walk_value(
    relative_path: str,
    value: Any,
    *,
    pointer_segments: tuple[str, ...],
    parent_type: str | None,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str,
    line_offset: int,
    metadata_overrides: dict[str, dict[str, Any]],
    paths: list[RawObservation],
    references: list[RawObservation],
) -> None:
    if pointer_segments:
        pointer = json_pointer(pointer_segments)
        metadata_override = metadata_overrides.get(pointer, {})
        path_observation = _path_observation(
            relative_path,
            pointer,
            value,
            parent_type=parent_type,
            format_name=format_name,
            confidence=confidence,
            content=content,
            source_suffix=source_suffix,
            line_offset=line_offset,
            metadata_override=metadata_override,
        )
        paths.append(path_observation)
        references.extend(
            _reference_observations_for_value(
                relative_path,
                pointer_segments,
                value,
                source_path_key=path_observation.target or config_path_key(
                    relative_path,
                    pointer,
                ),
                format_name=format_name,
                confidence="heuristic",
                content=content,
                source_suffix=source_suffix,
                line_offset=line_offset,
                metadata_override=metadata_override,
            )
        )
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_value(
                relative_path,
                child,
                pointer_segments=(*pointer_segments, str(key)),
                parent_type="object",
                format_name=format_name,
                confidence=confidence,
                content=content,
                source_suffix=source_suffix,
                line_offset=line_offset,
                metadata_overrides=metadata_overrides,
                paths=paths,
                references=references,
            )
    if isinstance(value, list) and _uses_stable_array_member_paths(format_name):
        for member in _stable_array_members(value):
            _walk_value(
                relative_path,
                member.value,
                pointer_segments=(*pointer_segments, member.segment),
                parent_type="array",
                format_name=format_name,
                confidence=confidence,
                content=content,
                source_suffix=source_suffix,
                line_offset=line_offset,
                metadata_overrides=metadata_overrides,
                paths=paths,
                references=references,
            )


def _path_observation(
    relative_path: str,
    pointer: str,
    value: Any,
    *,
    parent_type: str | None,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str,
    line_offset: int,
    metadata_override: dict[str, Any] | None = None,
) -> RawObservation:
    metadata_override = metadata_override or {}
    redacted = bool(metadata_override.get("redacted")) or _is_secret_pointer(pointer)
    metadata = _path_metadata(
        pointer,
        value,
        parent_type=parent_type,
        format_name=format_name,
        redacted=redacted,
    )
    if metadata_override:
        metadata.update(metadata_override)
        if metadata.get("redacted"):
            metadata.pop("value_summary", None)
            metadata.pop("value_summaries", None)
            metadata.setdefault("redaction_reason", "secret-prone-key")
    line_number = _line_for_pointer(content, pointer)
    if line_number is not None:
        line_number += line_offset
    return RawObservation(
        kind="config.path",
        source_id=f"{relative_path}#config-path:{pointer}{source_suffix}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=pointer,
        target=config_path_key(relative_path, pointer),
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _path_metadata(
    pointer: str,
    value: Any,
    *,
    parent_type: str | None,
    format_name: str,
    redacted: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "format": format_name,
        "pointer": pointer,
        "display_path": pointer,
        "value_type": _value_type(value),
        "redacted": redacted,
    }
    if format_name == PLIST_XML_FORMAT:
        metadata["parser"] = _parser_name(format_name)
        metadata["safety_mode"] = PLIST_XML_SAFETY_MODE
    if parent_type is not None:
        metadata["container_type"] = parent_type
    if redacted:
        metadata["redaction_reason"] = "secret-prone-key"
        return metadata
    value_summary = _safe_value_summary(value)
    if value_summary is not None:
        metadata["value_summary"] = value_summary
    if isinstance(value, list):
        metadata["item_count"] = len(value)
        stable_members = (
            _stable_array_members(value)
            if _uses_stable_array_member_paths(format_name)
            else ()
        )
        if stable_members:
            metadata["array_policy"] = "stable-member-key"
            metadata["stable_member_keys"] = sorted(
                {member.key for member in stable_members}
            )
        else:
            metadata["array_policy"] = "summary-only"
        scalar_summaries = [
            summary
            for item in value[:5]
            if (summary := _safe_value_summary(item)) is not None
        ]
        if scalar_summaries:
            metadata["value_summaries"] = scalar_summaries
    return metadata


def _uses_stable_array_member_paths(format_name: str) -> bool:
    return format_name in ("toml", PLIST_XML_FORMAT, YAML_FORMAT)


class _StableArrayMember:
    def __init__(self, *, key: str, segment: str, value: dict[str, Any]) -> None:
        self.key = key
        self.segment = segment
        self.value = value


def _stable_array_members(value: list[Any]) -> tuple[_StableArrayMember, ...]:
    members: list[_StableArrayMember] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return ()
        stable_key = _stable_member_key(item)
        if stable_key is None:
            return ()
        stable_value = item[stable_key]
        summary = _safe_value_summary(stable_value)
        if summary is None or isinstance(summary, bool):
            return ()
        segment = str(summary)
        if segment in seen:
            return ()
        seen.add(segment)
        members.append(
            _StableArrayMember(key=stable_key, segment=segment, value=item)
        )
    return tuple(members)


def _stable_member_key(value: dict[str, Any]) -> str | None:
    normalized_keys = {_normalized_key(str(key)): str(key) for key in value}
    for candidate in STABLE_ARRAY_MEMBER_KEYS:
        key = normalized_keys.get(candidate)
        if key is not None and not _is_secret_key(key):
            return key
    return None


def _reference_observations_for_value(
    relative_path: str,
    pointer_segments: tuple[str, ...],
    value: Any,
    *,
    source_path_key: str,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str,
    line_offset: int,
    metadata_override: dict[str, Any] | None = None,
) -> tuple[RawObservation, ...]:
    pointer = json_pointer(pointer_segments)
    metadata_override = metadata_override or {}
    if metadata_override.get("redacted"):
        return ()
    references = _detect_references(
        relative_path,
        pointer_segments,
        value,
        format_name=format_name,
    )
    observations: list[RawObservation] = []
    for ordinal, reference in enumerate(references):
        line_number = _line_for_pointer(content, pointer)
        if line_number is not None:
            line_number += line_offset
        metadata = {
            "format": format_name,
            "pointer": pointer,
            "raw_key": pointer_segments[-1],
            "reference_kind": reference["kind"],
            "redacted": reference["redacted"],
            "resolution_reason": reference["reason"],
            "source_document_key": config_document_key(relative_path),
            "source_path_key": source_path_key,
        }
        if format_name == PLIST_XML_FORMAT:
            metadata["parser"] = _parser_name(format_name)
            metadata["safety_mode"] = PLIST_XML_SAFETY_MODE
        if format_name == YAML_FORMAT:
            for key in ("profile", "document_index", "yaml_tag", "anchor", "alias", "merge_key"):
                if key in metadata_override:
                    metadata[key] = metadata_override[key]
        if "summary" in reference:
            metadata["raw_value_summary"] = reference["summary"]
        if reference["redacted"]:
            metadata["redaction_reason"] = "secret-prone-key"
        observations.append(
            RawObservation(
                kind="config.reference",
                source_id=(
                    f"{relative_path}#config-reference:{pointer}:"
                    f"{ordinal}{source_suffix}"
                ),
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=pointer,
                target=reference["target"],
                confidence=confidence,
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _detect_references(
    relative_path: str,
    pointer_segments: tuple[str, ...],
    value: Any,
    *,
    format_name: str = "",
) -> tuple[dict[str, Any], ...]:
    if not pointer_segments:
        return ()
    key = pointer_segments[-1]
    key_normalized = _normalized_key(key)
    pointer_key_normalized = "_".join(
        _normalized_key(segment) for segment in pointer_segments
    )
    parent_key = _normalized_key(pointer_segments[-2]) if len(pointer_segments) > 1 else ""
    redacted = _is_secret_pointer(json_pointer(pointer_segments))
    references: list[dict[str, Any]] = []
    if parent_key in ENV_CONTAINER_KEYS:
        references.append(_env_key_reference(key, redacted=redacted))
    if isinstance(value, str):
        references.extend(
            _string_references(
                relative_path,
                key_normalized,
                pointer_key_normalized,
                value,
                pointer_segments=pointer_segments,
                format_name=format_name,
                redacted=redacted,
            )
        )
    elif isinstance(value, list) and key_normalized == "args" and value:
        first = value[0]
        if isinstance(first, str) and _is_clear_command_name(first):
            references.append(_tool_reference_from_command(first, redacted=redacted))
    return tuple(references)


def _string_references(
    relative_path: str,
    key_normalized: str,
    pointer_key_normalized: str,
    value: str,
    *,
    pointer_segments: tuple[str, ...],
    format_name: str,
    redacted: bool,
) -> tuple[dict[str, Any], ...]:
    if format_name == YAML_FORMAT:
        yaml_references = _yaml_string_references(
            relative_path,
            pointer_segments,
            key_normalized,
            pointer_key_normalized,
            value,
            redacted=redacted,
        )
        if yaml_references:
            return yaml_references
    if _is_url(value):
        return (
            _reference(
                "external.url",
                external_url_key(value),
                "url-literal",
                value,
                redacted=redacted,
            ),
        )
    env_match = ENV_REFERENCE_PATTERN.match(value)
    if env_match is not None:
        return (
            _reference(
                "env",
                env_key(env_match.group("name")),
                "env-var-reference",
                value,
                redacted=redacted,
            ),
        )
    if key_normalized in TOOL_KEYS:
        return (_tool_reference_from_command(value, redacted=redacted),)
    if _looks_like_file_key(key_normalized, value) or _looks_like_file_key(
        pointer_key_normalized,
        value,
    ):
        return (_file_reference(relative_path, value, redacted=redacted),)
    return ()


def _yaml_string_references(
    relative_path: str,
    pointer_segments: tuple[str, ...],
    key_normalized: str,
    pointer_key_normalized: str,
    value: str,
    *,
    redacted: bool,
) -> tuple[dict[str, Any], ...]:
    stripped = value.strip()
    if not stripped:
        return ()
    if pointer_segments[-1] == "$ref" or key_normalized in ("$ref", "ref"):
        return (_yaml_openapi_ref(relative_path, stripped, redacted=redacted),)
    if key_normalized == "uses":
        return (_yaml_uses_reference(relative_path, stripped, redacted=redacted),)
    if key_normalized == "image" and _looks_like_container_image(stripped):
        return (
            _reference(
                "external",
                external_key("docker.image", stripped),
                "yaml-container-image",
                stripped,
                redacted=redacted,
            ),
        )
    if key_normalized in ("context", "dockerfile", "env_file"):
        return (_file_reference(relative_path, stripped, redacted=redacted),)
    if key_normalized in ("import", "additional_location", "location"):
        spring_file = _yaml_spring_file_reference_value(stripped)
        if spring_file is not None:
            return (_file_reference(relative_path, spring_file, redacted=redacted),)
    if key_normalized in ("repository", "url") and _is_url(stripped):
        return (
            _reference(
                "external.url",
                external_url_key(stripped),
                "yaml-url-field",
                stripped,
                redacted=redacted,
            ),
        )
    if "path" in pointer_key_normalized or key_normalized in (
        "file",
        "files",
        "config",
        "config_path",
        "include_file",
    ):
        return (_file_reference(relative_path, stripped, redacted=redacted),)
    return ()


def _yaml_openapi_ref(
    relative_path: str,
    value: str,
    *,
    redacted: bool,
) -> dict[str, Any]:
    if _is_url(value):
        return _reference(
            "external.url",
            external_url_key(value),
            "openapi-remote-ref",
            value,
            redacted=redacted,
        )
    if value.startswith("#/"):
        return _reference(
            "config.path",
            config_path_key(relative_path, value[1:]),
            "openapi-local-pointer-ref",
            value,
            redacted=redacted,
        )
    if "#" in value:
        path_part, pointer_part = value.split("#", 1)
        if path_part and not _is_dynamic_value(path_part):
            target = _file_reference(relative_path, path_part, redacted=redacted)
            target["reason"] = "openapi-local-file-ref"
            if pointer_part:
                target["summary"] = _safe_value_summary(value)
            return target
    return _file_reference(relative_path, value, redacted=redacted)


def _yaml_uses_reference(
    relative_path: str,
    value: str,
    *,
    redacted: bool,
) -> dict[str, Any]:
    if value.startswith("./"):
        resolved = _normalize_repo_path(value)
        if resolved is None:
            return _reference(
                "unknown",
                unknown_key("file", "repo-escaping-config-reference"),
                "repo-escaping-file-reference",
                value,
                redacted=redacted,
            )
        return _reference(
            "file",
            file_key(resolved),
            "github-actions-local-uses",
            value,
            redacted=redacted,
        )
    if value.startswith(("../", "/")):
        return _file_reference(relative_path, value, redacted=redacted)
    if _is_dynamic_value(value):
        return _reference(
            "dynamic",
            dynamic_key("github.action", "dynamic-yaml-uses"),
            "dynamic-yaml-uses",
            value,
            redacted=redacted,
        )
    return _reference(
        "external",
        external_key("github.action", value),
        "github-actions-uses",
        value,
        redacted=redacted,
    )


def _yaml_spring_file_reference_value(value: str) -> str | None:
    for prefix in ("optional:file:", "file:"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return None


def _looks_like_container_image(value: str) -> bool:
    if _is_url(value) or value.startswith(("./", "../", "/", "$", "~")):
        return False
    return bool(YAML_SIMPLE_IMAGE_PATTERN.match(value)) and (
        "/" in value or ":" in value or "@" in value
    )


def _tool_reference_from_command(command: str, *, redacted: bool) -> dict[str, Any]:
    if _is_clear_command_name(command):
        return _reference(
            "tool",
            tool_key(command),
            "simple-command-field",
            command,
            redacted=redacted,
        )
    if _is_dynamic_value(command) or any(character.isspace() for character in command):
        return _reference(
            "dynamic",
            dynamic_key("tool", "config-command-fragment"),
            "dynamic-command-field",
            command,
            redacted=redacted,
        )
    return _reference(
        "unknown",
        unknown_key("tool", "unknown-config-command"),
        "unknown-command-field",
        command,
        redacted=redacted,
    )


def _is_clear_command_name(command: str) -> bool:
    return bool(SIMPLE_COMMAND_PATTERN.match(command)) and not command.startswith("-")


def _file_reference(relative_path: str, value: str, *, redacted: bool) -> dict[str, Any]:
    if _is_dynamic_value(value):
        return _reference(
            "dynamic",
            dynamic_key("file", "config-reference-expanded-from-variable"),
            "dynamic-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("/"):
        return _reference(
            "external",
            external_key("file", "absolute-config-reference"),
            "absolute-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("../"):
        resolved = _resolve_repo_path(relative_path, value)
        if resolved is None:
            return _reference(
                "unknown",
                unknown_key("file", "repo-escaping-config-reference"),
                "repo-escaping-file-reference",
                value,
                redacted=redacted,
            )
        return _reference("file", file_key(resolved), "relative-file-reference", value, redacted=redacted)
    if value.startswith("./"):
        resolved = _resolve_repo_path(relative_path, value)
    else:
        resolved = _normalize_repo_path(value)
    if resolved is None:
        return _reference(
            "unknown",
            unknown_key("file", "repo-escaping-config-reference"),
            "repo-escaping-file-reference",
            value,
            redacted=redacted,
        )
    return _reference("file", file_key(resolved), "relative-file-reference", value, redacted=redacted)


def _env_key_reference(name: str, *, redacted: bool) -> dict[str, Any]:
    if ENV_NAME_PATTERN.match(name):
        return _reference(
            "env",
            env_key(name),
            "env-object-key",
            name,
            redacted=redacted,
        )
    return _reference(
        "dynamic",
        dynamic_key("env", "dynamic-config-env-name"),
        "dynamic-env-object-key",
        name,
        redacted=redacted,
    )


def _reference(
    kind: str,
    target: str,
    reason: str,
    raw_value: Any,
    *,
    redacted: bool,
) -> dict[str, Any]:
    reference = {
        "kind": kind,
        "target": target,
        "reason": reason,
        "redacted": redacted,
    }
    if not redacted:
        summary = _safe_value_summary(raw_value)
        if summary is not None:
            reference["summary"] = summary
    return reference


def _document_observation(
    relative_path: str,
    *,
    format_name: str,
    parser: str,
    confidence: str,
    top_level_type: str,
    path_count: int,
    record_count: int | None,
    parse_error_count: int,
    extra_metadata: dict[str, Any] | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": format_name,
        "parser": parser,
        "top_level_type": top_level_type,
        "document_role": _document_role(relative_path),
        "path_count": path_count,
        "parse_error_count": parse_error_count,
    }
    if format_name == PLIST_XML_FORMAT:
        metadata["safety_mode"] = PLIST_XML_SAFETY_MODE
    if record_count is not None:
        metadata["record_count"] = record_count
    if extra_metadata:
        metadata.update(extra_metadata)
    return RawObservation(
        kind="config.document",
        source_id=f"{relative_path}#config-document",
        path=relative_path,
        target=config_document_key(relative_path),
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _jsonl_record_observation(
    relative_path: str,
    value: Any,
    *,
    line_number: int,
    record_index: int,
) -> RawObservation:
    metadata = {
        "format": "jsonl",
        "record_index": record_index,
        "line_number": line_number,
        "top_level_type": _value_type(value),
    }
    if isinstance(value, dict):
        safe_keys = []
        redacted_keys = []
        for key in sorted(str(item) for item in value):
            if _is_secret_key(key):
                redacted_keys.append(key)
            else:
                safe_keys.append(key)
        metadata["safe_keys"] = safe_keys
        metadata["redacted_keys"] = redacted_keys
    else:
        summary = _safe_value_summary(value)
        if summary is not None:
            metadata["value_summary"] = summary
    return RawObservation(
        kind="config.jsonl_record",
        source_id=f"{relative_path}#jsonl-record:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _parse_error_observation(
    relative_path: str,
    *,
    format_name: str,
    error_kind: str,
    error: Any | None = None,
    message: str | None = None,
    start_line: int | None = None,
    recovered: bool,
) -> RawObservation:
    line_number = start_line or (error.lineno if error is not None else None)
    metadata: dict[str, Any] = {
        "format": format_name,
        "parser": _parser_name(format_name),
        "error_kind": error_kind,
        "message_summary": _safe_error_message(error, message),
        "recovered": recovered,
    }
    if line_number is not None:
        metadata["line_number"] = line_number
    column_number = getattr(error, "colno", None)
    if column_number is not None:
        metadata["column_number"] = column_number
    return RawObservation(
        kind="config.parse_error",
        source_id=f"{relative_path}#config-parse-error:{line_number or 'document'}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _xml_parse_error_observation(
    relative_path: str,
    *,
    error_kind: str,
    message: str,
    start_line: int | None = None,
    recovered: bool,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": GENERIC_XML_FORMAT,
        "parser": _parser_name(GENERIC_XML_FORMAT),
        "safety_mode": GENERIC_XML_SAFETY_MODE,
        "error_kind": error_kind,
        "message_summary": _safe_error_message(None, message),
        "recovered": recovered,
    }
    if start_line is not None:
        metadata["line_number"] = start_line
    return RawObservation(
        kind="xml.parse_error",
        source_id=f"{relative_path}#xml-parse-error:{start_line or 'document'}",
        path=relative_path,
        start_line=start_line,
        end_line=start_line,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _safe_error_message(
    error: Any | None,
    message: str | None,
) -> str:
    if message is not None:
        summary = message
    elif error is not None:
        summary = getattr(error, "msg", str(error))
    else:
        summary = "parse error"
    return summary[:120]


def _parser_name(format_name: str) -> str:
    if format_name == YAML_FORMAT:
        return YAML_PARSER
    if format_name == "jsonc":
        return "jsonc-conservative"
    if format_name == "toml":
        return "stdlib-tomllib"
    if format_name == PLIST_XML_FORMAT:
        return "stdlib-elementtree-safe"
    if format_name == GENERIC_XML_FORMAT:
        return "stdlib-elementtree-safe"
    return "stdlib-json"


def _line_for_pointer(content: str, pointer: str) -> int | None:
    if pointer == "":
        return None
    toml_line = _line_for_toml_pointer(content, pointer)
    if toml_line is not None:
        return toml_line
    key = pointer.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
    json_pattern = re.compile(rf'"{re.escape(key)}"\s*:')
    toml_pattern = re.compile(
        rf"^\s*(?:{re.escape(key)}|\"{re.escape(key)}\"|'{re.escape(key)}')\s*="
    )
    yaml_pattern = re.compile(
        rf"^\s*(?:{re.escape(key)}|\"{re.escape(key)}\"|'{re.escape(key)}')\s*:"
    )
    plist_pattern = re.compile(rf"<key>\s*{re.escape(key)}\s*</key>")
    for line_number, line in enumerate(content.splitlines(), start=1):
        if (
            json_pattern.search(line)
            or toml_pattern.search(line)
            or yaml_pattern.search(line)
            or plist_pattern.search(line)
        ):
            return line_number
    return None


def _line_for_toml_pointer(content: str, pointer: str) -> int | None:
    pointer_segments = _pointer_segments(pointer)
    if not pointer_segments:
        return None
    sections = _toml_sections(content)
    for section in sections:
        if section.path == pointer_segments:
            return section.header_line
        member_segment = _toml_array_member_segment(section)
        for line_number, line in section.lines:
            key_segments = _toml_key_segments(line)
            if key_segments is None:
                continue
            if section.is_array:
                if member_segment is None:
                    continue
                candidate = (*section.path, member_segment, *key_segments)
            else:
                candidate = (*section.path, *key_segments)
            if candidate == pointer_segments:
                return line_number
    return None


class _TomlSection:
    def __init__(
        self,
        *,
        path: tuple[str, ...],
        header_line: int | None,
        is_array: bool,
        lines: tuple[tuple[int, str], ...],
    ) -> None:
        self.path = path
        self.header_line = header_line
        self.is_array = is_array
        self.lines = lines


def _toml_sections(content: str) -> tuple[_TomlSection, ...]:
    sections: list[_TomlSection] = []
    path: tuple[str, ...] = ()
    header_line: int | None = None
    is_array = False
    lines: list[tuple[int, str]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        header = _toml_table_header(line)
        if header is not None:
            sections.append(
                _TomlSection(
                    path=path,
                    header_line=header_line,
                    is_array=is_array,
                    lines=tuple(lines),
                )
            )
            path, is_array = header
            header_line = line_number
            lines = []
            continue
        lines.append((line_number, line))
    sections.append(
        _TomlSection(
            path=path,
            header_line=header_line,
            is_array=is_array,
            lines=tuple(lines),
        )
    )
    return tuple(sections)


def _toml_table_header(line: str) -> tuple[tuple[str, ...], bool] | None:
    stripped = line.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return _toml_dotted_segments(stripped[2:-2]), True
    if stripped.startswith("[") and stripped.endswith("]"):
        return _toml_dotted_segments(stripped[1:-1]), False
    return None


def _toml_array_member_segment(section: _TomlSection) -> str | None:
    if not section.is_array:
        return None
    parsed = _parse_toml_section_lines(section.lines)
    if not isinstance(parsed, dict):
        return None
    stable_key = _stable_member_key(parsed)
    if stable_key is None:
        return None
    summary = _safe_value_summary(parsed[stable_key])
    if summary is None or isinstance(summary, bool):
        return None
    return str(summary)


def _parse_toml_section_lines(lines: tuple[tuple[int, str], ...]) -> dict[str, Any] | None:
    body = "\n".join(line for _line_number, line in lines)
    if not body.strip():
        return None
    try:
        parsed = tomllib.loads(body)
    except tomllib.TOMLDecodeError:
        return None
    return parsed


def _toml_key_segments(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key_text = stripped.split("=", 1)[0].strip()
    if not key_text:
        return None
    return _toml_dotted_segments(key_text)


def _toml_dotted_segments(value: str) -> tuple[str, ...]:
    return tuple(
        segment.strip().strip("\"'")
        for segment in value.split(".")
        if segment.strip()
    )


def _value_type(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    return "number"


def _safe_value_summary(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= 120 and all(character.isprintable() for character in value):
            return value
        return f"<string:{len(value)}>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _is_secret_pointer(pointer: str) -> bool:
    return any(_is_secret_key(segment) for segment in _pointer_segments(pointer))


def _is_secret_key(key: str) -> bool:
    normalized = _normalized_key(key)
    squashed = re.sub(r"[^0-9a-z]", "", normalized)
    return any(marker.replace("_", "") in squashed for marker in SECRET_PRONE_KEYS)


def _normalized_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _pointer_segments(pointer: str) -> tuple[str, ...]:
    if not pointer:
        return ()
    return tuple(
        segment.replace("~1", "/").replace("~0", "~")
        for segment in pointer.removeprefix("/").split("/")
    )


def _escape_pointer_segment(segment: str) -> str:
    return str(segment).replace("~", "~0").replace("/", "~1")


def _is_url(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme in ("http", "https"):
        return bool(parsed.netloc)
    if parsed.scheme == "mailto":
        return bool(parsed.path)
    return False


def _is_dynamic_value(value: str) -> bool:
    return any(marker in value for marker in DYNAMIC_MARKERS)


def _looks_like_file_key(key_normalized: str, value: str) -> bool:
    if _is_url(value):
        return False
    if value.startswith(("./", "../", "/", "${", "~")):
        return True
    return "/" in value and any(marker in key_normalized for marker in PATH_KEY_MARKERS)


def _resolve_repo_path(relative_path: str, value: str) -> str | None:
    base = PurePosixPath(relative_path.replace("\\", "/")).parent
    return _normalize_repo_path(str(base / value))


def _normalize_repo_path(value: str) -> str | None:
    parts: list[str] = []
    for part in value.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return "."
    return "/".join(parts)


def _document_role(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    normalized_name = _normalized_key(path.name)
    if path.suffix in (".plist", ".xml") and "chrome" in normalized_name and "policy" in normalized_name:
        return "chrome-policy"
    if path.suffix == ".plist":
        return "plist-config"
    if path.name == "config.json" and "mcp" in path.parts:
        return "mcp-config"
    if path.suffix == ".jsonl":
        return "log"
    return "config"
