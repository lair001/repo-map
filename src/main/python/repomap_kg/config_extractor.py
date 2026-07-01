"""Static structured configuration raw observation extraction."""

from __future__ import annotations

import json
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


def extract_config_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    suffix = PurePosixPath(relative_path).suffix.lower()
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
        return (
            _parse_error_observation(
                relative_path,
                format_name="json",
                error_kind="malformed-json",
                error=error,
                recovered=False,
            ),
        )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="json",
        confidence="extracted",
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
    )
    return (document, *path_observations, *reference_observations)


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
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="jsonc",
        confidence="heuristic",
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
    )
    return (document, *path_observations, *reference_observations)


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
        return (
            _parse_error_observation(
                relative_path,
                format_name="toml",
                error_kind="malformed-toml",
                message=str(error),
                start_line=getattr(error, "lineno", None),
                recovered=False,
            ),
        )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="toml",
        confidence="extracted",
        content=content,
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
    return (document, *path_observations, *reference_observations)


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
    return (document, *path_observations, *reference_observations)


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
    if any(_is_openapi_document(document) for document in documents):
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
