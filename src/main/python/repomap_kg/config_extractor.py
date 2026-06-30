"""Static structured configuration raw observation extraction."""

from __future__ import annotations

import json
import re
import tomllib
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
)
ENV_CONTAINER_KEYS = frozenset(("env", "environment", "env_vars"))
TOOL_KEYS = frozenset(("command", "cmd", "executable", "program"))
PATH_KEY_MARKERS = ("path", "file", "cwd")
STABLE_ARRAY_MEMBER_KEYS = ("name", "id", "key", "project")
SIMPLE_COMMAND_PATTERN = re.compile(r"^[0-9A-Za-z_.+-]+$")
ENV_REFERENCE_PATTERN = re.compile(r"^\$(?P<brace>\{?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}?$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DYNAMIC_MARKERS = ("${", "$(", "{{", "}}", "*", "?", "~")


class JsoncNormalizationError(ValueError):
    """Raised when conservative JSONC normalization cannot safely continue."""


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
    paths: list[RawObservation],
    references: list[RawObservation],
) -> None:
    if pointer_segments:
        pointer = json_pointer(pointer_segments)
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
                paths=paths,
                references=references,
            )
    if isinstance(value, list) and format_name == "toml":
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
) -> RawObservation:
    redacted = _is_secret_pointer(pointer)
    metadata = _path_metadata(
        pointer,
        value,
        parent_type=parent_type,
        format_name=format_name,
        redacted=redacted,
    )
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
        stable_members = _stable_array_members(value) if format_name == "toml" else ()
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
) -> tuple[RawObservation, ...]:
    pointer = json_pointer(pointer_segments)
    references = _detect_references(relative_path, pointer_segments, value)
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
    redacted: bool,
) -> tuple[dict[str, Any], ...]:
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
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": format_name,
        "parser": parser,
        "top_level_type": top_level_type,
        "document_role": _document_role(relative_path),
        "path_count": path_count,
        "parse_error_count": parse_error_count,
    }
    if record_count is not None:
        metadata["record_count"] = record_count
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
    if format_name == "jsonc":
        return "jsonc-conservative"
    if format_name == "toml":
        return "stdlib-tomllib"
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
    for line_number, line in enumerate(content.splitlines(), start=1):
        if json_pattern.search(line) or toml_pattern.search(line):
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
    if path.name == "config.json" and "mcp" in path.parts:
        return "mcp-config"
    if path.suffix == ".jsonl":
        return "log"
    return "config"
