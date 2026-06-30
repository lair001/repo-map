"""Conservative static CSS raw observation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.graph_keys import (
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR_NAME = "repo-css"
PARSER_NAME = "stdlib-css-conservative"
PARSER_MODE = "static-no-cascade-no-layout-no-fetch"
SECRET_PRONE_MARKERS = (
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
DYNAMIC_MARKERS = ("${", "$(", "{{", "}}", "*", "?", "~", "var(")
IDENTIFIER_PATTERN = re.compile(r"-?[A-Za-z_][A-Za-z0-9_-]*")
CLASS_PATTERN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_-]*)")
ID_PATTERN = re.compile(r"#([A-Za-z_][A-Za-z0-9_-]*)")
ATTRIBUTE_PATTERN = re.compile(r"\[\s*([A-Za-z_][A-Za-z0-9_-]*)")
PSEUDO_ELEMENT_PATTERN = re.compile(r"::([A-Za-z_][A-Za-z0-9_-]*)")
PSEUDO_CLASS_PATTERN = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_-]*)")


@dataclass
class _CssRule:
    pointer: str
    rule_type: str
    start_index: int
    start_line: int
    parent_pointer: str | None = None
    selector_text: str | None = None
    at_rule_name: str | None = None
    at_rule_prelude: str | None = None
    declarations: list[_CssDeclaration] = field(default_factory=list)
    selectors: list[str] = field(default_factory=list)
    references: list[_CssReference] = field(default_factory=list)


@dataclass(frozen=True)
class _CssDeclaration:
    property_name: str
    value: str
    important: bool
    start_line: int


@dataclass(frozen=True)
class _CssReference:
    value: str
    source_kind: str
    rule_pointer: str
    property_name: str | None
    start_line: int


@dataclass(frozen=True)
class _CssParseError:
    error_kind: str
    message: str
    line_number: int
    recovered: bool
    rule_pointer: str | None = None


@dataclass
class _ParseState:
    content: str
    rules: list[_CssRule] = field(default_factory=list)
    errors: list[_CssParseError] = field(default_factory=list)


def extract_css_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    state = _ParseState(_strip_comments(content))
    _parse_rules(state, 0, len(state.content), parent_pointer=None)

    selector_count = sum(len(rule.selectors) for rule in state.rules)
    custom_properties = _custom_property_names(state.rules)
    reference_count = sum(len(rule.references) for rule in state.rules)
    observations: list[RawObservation] = [
        _document_observation(
            relative_path,
            rule_count=len(state.rules),
            selector_count=selector_count,
            custom_property_count=len(custom_properties),
            reference_count=reference_count,
            parse_error_count=len(state.errors),
        )
    ]
    for rule in state.rules:
        observations.append(_rule_observation(relative_path, rule))
        observations.extend(_selector_observations(relative_path, rule))
        observations.extend(_declaration_observations(relative_path, rule))
        observations.extend(_custom_property_observations(relative_path, rule))
        observations.extend(_reference_observations(relative_path, rule))
    for error in state.errors:
        observations.append(_parse_error_observation(relative_path, error))
    return tuple(observations)


def _parse_rules(
    state: _ParseState,
    start: int,
    end: int,
    *,
    parent_pointer: str | None,
) -> None:
    index = start
    counters: dict[str, int] = {}
    while index < end:
        index = _skip_whitespace(state.content, index, end)
        if index >= end:
            return
        if state.content[index] == "@":
            index = _parse_at_rule(state, index, end, parent_pointer, counters)
            continue
        index = _parse_style_rule(state, index, end, parent_pointer, counters)


def _parse_at_rule(
    state: _ParseState,
    index: int,
    end: int,
    parent_pointer: str | None,
    counters: dict[str, int],
) -> int:
    name_end = index + 1
    while name_end < end and (
        state.content[name_end].isalnum() or state.content[name_end] in "-_"
    ):
        name_end += 1
    at_name = state.content[index + 1 : name_end].lower() or "unknown"
    prelude_start = _skip_whitespace(state.content, name_end, end)
    delimiter_index, delimiter = _find_at_rule_delimiter(
        state.content, prelude_start, end
    )
    if delimiter_index is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-at-rule",
                message=f"unterminated @{at_name} rule",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    prelude = state.content[prelude_start:delimiter_index].strip()
    if delimiter == ";":
        if at_name == "import":
            pointer = _next_pointer(parent_pointer, "import", counters)
            rule = _CssRule(
                pointer=pointer,
                rule_type="import",
                at_rule_name=at_name,
                at_rule_prelude=prelude,
                start_index=index,
                start_line=_line_for_index(state.content, index),
                parent_pointer=parent_pointer,
            )
            rule.references.extend(
                _references_for_text(
                    prelude,
                    source_kind="import",
                    rule_pointer=pointer,
                    property_name=None,
                    line_number=rule.start_line,
                )
            )
            state.rules.append(rule)
        return delimiter_index + 1

    block_start = delimiter_index + 1
    block_end = _find_matching_brace(state.content, delimiter_index, end)
    if block_end is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-at-rule-block",
                message=f"unterminated @{at_name} block",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    if at_name in ("media", "supports"):
        pointer = _next_pointer(parent_pointer, at_name, counters)
        state.rules.append(
            _CssRule(
                pointer=pointer,
                rule_type=at_name,
                at_rule_name=at_name,
                at_rule_prelude=prelude,
                start_index=index,
                start_line=_line_for_index(state.content, index),
                parent_pointer=parent_pointer,
            )
        )
        _parse_rules(state, block_start, block_end, parent_pointer=pointer)
        return block_end + 1
    if at_name == "font-face":
        pointer = _next_pointer(parent_pointer, "font-face", counters)
        rule = _CssRule(
            pointer=pointer,
            rule_type="font-face",
            at_rule_name=at_name,
            at_rule_prelude=prelude,
            start_index=index,
            start_line=_line_for_index(state.content, index),
            parent_pointer=parent_pointer,
        )
        block = state.content[block_start:block_end]
        rule.declarations.extend(_parse_declarations(block, state.content, block_start))
        rule.references.extend(_references_for_declarations(rule))
        state.rules.append(rule)
        return block_end + 1
    pointer = _next_pointer(parent_pointer, "at-rule", counters)
    state.rules.append(
        _CssRule(
            pointer=pointer,
            rule_type="unknown-at-rule",
            at_rule_name=at_name,
            at_rule_prelude=prelude,
            start_index=index,
            start_line=_line_for_index(state.content, index),
            parent_pointer=parent_pointer,
        )
    )
    return block_end + 1


def _parse_style_rule(
    state: _ParseState,
    index: int,
    end: int,
    parent_pointer: str | None,
    counters: dict[str, int],
) -> int:
    brace_index = _find_next_top_level_char(state.content, "{", index, end)
    if brace_index is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-rule",
                message="style rule missing block",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    selector_text = state.content[index:brace_index].strip()
    if not selector_text:
        return brace_index + 1
    block_end = _find_matching_brace(state.content, brace_index, end)
    if block_end is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-rule-block",
                message="unterminated style rule",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    block = state.content[brace_index + 1 : block_end]
    pointer = _next_pointer(parent_pointer, "rule", counters)
    if "{" in block or "}" in block:
        state.errors.append(
            _CssParseError(
                error_kind="unsupported-nested-style-rule",
                message="nested style rules are not supported in CSS1",
                line_number=_line_for_index(state.content, brace_index + 1),
                recovered=True,
                rule_pointer=pointer,
            )
        )
        return block_end + 1
    rule = _CssRule(
        pointer=pointer,
        rule_type="style",
        selector_text=" ".join(selector_text.split()),
        selectors=_split_selectors(selector_text),
        start_index=index,
        start_line=_line_for_index(state.content, index),
        parent_pointer=parent_pointer,
    )
    rule.declarations.extend(_parse_declarations(block, state.content, brace_index + 1))
    rule.references.extend(_references_for_declarations(rule))
    state.rules.append(rule)
    return block_end + 1


def _document_observation(
    relative_path: str,
    *,
    rule_count: int,
    selector_count: int,
    custom_property_count: int,
    reference_count: int,
    parse_error_count: int,
) -> RawObservation:
    return RawObservation(
        kind="css.document",
        source_id=f"{relative_path}#css-document",
        path=relative_path,
        target=css_document_key(relative_path),
        confidence="extracted" if parse_error_count == 0 else "heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "source_kind": "file",
            "rule_count": rule_count,
            "selector_count": selector_count,
            "custom_property_count": custom_property_count,
            "reference_count": reference_count,
            "parse_error_count": parse_error_count,
        },
    )


def _rule_observation(relative_path: str, rule: _CssRule) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "css",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "rule_pointer": rule.pointer,
        "rule_type": rule.rule_type,
        "declaration_count": len(rule.declarations),
        "reference_count": len(rule.references),
        "identity_mode": "structural-document",
    }
    if rule.parent_pointer is not None:
        metadata["parent_rule_pointer"] = rule.parent_pointer
    if rule.selector_text is not None:
        metadata["selector_text"] = rule.selector_text
    if rule.at_rule_name is not None:
        metadata["at_rule_name"] = rule.at_rule_name
    if rule.at_rule_prelude:
        metadata["at_rule_prelude_summary"] = _safe_summary(rule.at_rule_prelude)
    custom_names = sorted(
        {declaration.property_name for declaration in rule.declarations if declaration.property_name.startswith("--")}
    )
    if custom_names:
        metadata["custom_property_names"] = custom_names
    font_family = _font_family(rule)
    if font_family is not None:
        metadata["font_family_summary"] = font_family
    return RawObservation(
        kind="css.rule",
        source_id=f"{relative_path}#css-rule:{rule.pointer}",
        path=relative_path,
        start_line=rule.start_line,
        end_line=rule.start_line,
        name=rule.pointer,
        target=css_rule_key(relative_path, rule.pointer),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _selector_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    for index, selector in enumerate(rule.selectors, start=1):
        pointer = f"{rule.pointer}/selector:{index}"
        metadata = _selector_metadata(selector, rule.pointer, pointer, index)
        observations.append(
            RawObservation(
                kind="css.selector",
                source_id=f"{relative_path}#css-selector:{pointer}",
                path=relative_path,
                start_line=rule.start_line,
                end_line=rule.start_line,
                name=pointer,
                target=css_selector_key(relative_path, pointer),
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _declaration_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    for index, declaration in enumerate(rule.declarations, start=1):
        references = _references_for_declaration(rule.pointer, declaration)
        reference_targets = [
            _target_for_reference_in_path(relative_path, reference.value)
            for reference in references
        ]
        redacted_for_data_url = any(
            target["reason"] == "data-url-redacted" for target in reference_targets
        )
        redacted = _is_secret_name(declaration.property_name) or _is_secret_name(
            declaration.value
        ) or redacted_for_data_url
        metadata: dict[str, Any] = {
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "rule_pointer": rule.pointer,
            "property_name": declaration.property_name,
            "value_type": _value_type(declaration.value),
            "important": declaration.important,
            "redacted": redacted,
        }
        if redacted_for_data_url:
            metadata["redaction_reason"] = "data-url-payload-redacted"
        elif redacted:
            metadata["redaction_reason"] = "secret-prone-css-declaration"
        else:
            summary = _safe_summary(declaration.value)
            if summary is not None:
                metadata["value_summary"] = summary
        if references:
            metadata["reference_targets"] = [
                target["target"] for target in reference_targets
            ]
        observations.append(
            RawObservation(
                kind="css.declaration",
                source_id=f"{relative_path}#css-declaration:{rule.pointer}:{index}",
                path=relative_path,
                start_line=declaration.start_line,
                end_line=declaration.start_line,
                name=declaration.property_name,
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _custom_property_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    for declaration in rule.declarations:
        if not declaration.property_name.startswith("--"):
            continue
        references = _references_for_declaration(rule.pointer, declaration)
        reference_targets = [
            _target_for_reference_in_path(relative_path, reference.value)
            for reference in references
        ]
        redacted_for_data_url = any(
            target["reason"] == "data-url-redacted" for target in reference_targets
        )
        redacted = _is_secret_name(declaration.property_name) or _is_secret_name(
            declaration.value
        ) or redacted_for_data_url
        metadata: dict[str, Any] = {
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "property_name": declaration.property_name,
            "rule_pointer": rule.pointer,
            "definition_count": 1,
            "value_type": _value_type(declaration.value),
            "redacted": redacted,
        }
        if redacted_for_data_url:
            metadata["redaction_reason"] = "data-url-payload-redacted"
        elif redacted:
            metadata["redaction_reason"] = "secret-prone-css-custom-property"
        else:
            summary = _safe_summary(declaration.value)
            if summary is not None:
                metadata["value_summary"] = summary
        observations.append(
            RawObservation(
                kind="css.custom_property",
                source_id=(
                    f"{relative_path}#css-custom-property:"
                    f"{declaration.property_name}:{rule.pointer}"
                ),
                path=relative_path,
                start_line=declaration.start_line,
                end_line=declaration.start_line,
                name=declaration.property_name,
                target=css_custom_property_key(relative_path, declaration.property_name),
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _reference_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    source_key = css_rule_key(relative_path, rule.pointer)
    for index, reference in enumerate(rule.references, start=1):
        target = _target_for_reference_in_path(relative_path, reference.value)
        redacted = target["kind"] == "unknown" and target["reason"] == "data-url-redacted"
        metadata: dict[str, Any] = {
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "reference_kind": target["kind"],
            "source_kind": reference.source_kind,
            "rule_pointer": reference.rule_pointer,
            "source_key": source_key,
            "resolution_reason": target["reason"],
            "redacted": redacted,
        }
        if reference.property_name is not None:
            metadata["property_name"] = reference.property_name
        if redacted:
            metadata["redaction_reason"] = "data-url-payload-redacted"
            metadata["raw_value_summary"] = "data-url-redacted"
        elif target.get("summary") is not None:
            metadata["raw_value_summary"] = target["summary"]
        observations.append(
            RawObservation(
                kind="css.reference",
                source_id=f"{relative_path}#css-reference:{rule.pointer}:{index}",
                path=relative_path,
                start_line=reference.start_line,
                end_line=reference.start_line,
                name=rule.pointer,
                target=target["target"],
                confidence="heuristic" if target["kind"] != "unknown" else "unknown",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _parse_error_observation(relative_path: str, error: _CssParseError) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "css",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "error_kind": error.error_kind,
        "message_summary": error.message[:120],
        "recovered": error.recovered,
        "line_number": error.line_number,
    }
    if error.rule_pointer is not None:
        metadata["rule_pointer"] = error.rule_pointer
    return RawObservation(
        kind="css.parse_error",
        source_id=f"{relative_path}#css-parse-error:{error.line_number}",
        path=relative_path,
        start_line=error.line_number,
        end_line=error.line_number,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _parse_declarations(
    block: str, full_content: str, block_offset: int
) -> list[_CssDeclaration]:
    declarations = []
    for segment, relative_start in _split_declaration_segments(block):
        if ":" not in segment:
            continue
        property_name, value = segment.split(":", 1)
        property_name = property_name.strip()
        value = value.strip()
        if not property_name:
            continue
        important = False
        if value.lower().endswith("!important"):
            important = True
            value = value[: -len("!important")].strip()
        declarations.append(
            _CssDeclaration(
                property_name=property_name,
                value=value,
                important=important,
                start_line=_line_for_index(full_content, block_offset + relative_start),
            )
        )
    return declarations


def _split_declaration_segments(block: str) -> list[tuple[str, int]]:
    parts: list[tuple[str, int]] = []
    start = 0
    index = 0
    in_string: str | None = None
    escaped = False
    paren_depth = 0
    while index < len(block):
        character = block[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == in_string:
                in_string = None
            index += 1
            continue
        if character in ("'", '"'):
            in_string = character
        elif character == "(":
            paren_depth += 1
        elif character == ")" and paren_depth:
            paren_depth -= 1
        elif character == ";" and paren_depth == 0:
            segment = block[start:index].strip()
            if segment:
                parts.append((segment, start))
            start = index + 1
        index += 1
    segment = block[start:].strip()
    if segment:
        parts.append((segment, start))
    return parts


def _references_for_declarations(rule: _CssRule) -> list[_CssReference]:
    references = []
    for declaration in rule.declarations:
        references.extend(_references_for_declaration(rule.pointer, declaration))
    return references


def _references_for_declaration(
    rule_pointer: str, declaration: _CssDeclaration
) -> list[_CssReference]:
    return [
        _CssReference(
            value=value,
            source_kind="url-function",
            rule_pointer=rule_pointer,
            property_name=declaration.property_name,
            start_line=declaration.start_line,
        )
        for value in _extract_url_values(declaration.value)
    ]


def _references_for_text(
    text: str,
    *,
    source_kind: str,
    rule_pointer: str,
    property_name: str | None,
    line_number: int,
) -> list[_CssReference]:
    values = _extract_url_values(text)
    if not values and source_kind == "import":
        stripped = _strip_css_string(text.strip())
        if stripped:
            values = [stripped]
    return [
        _CssReference(
            value=value,
            source_kind=source_kind,
            rule_pointer=rule_pointer,
            property_name=property_name,
            start_line=line_number,
        )
        for value in values
    ]


def _extract_url_values(value: str) -> list[str]:
    values = []
    lowered = value.lower()
    index = 0
    while True:
        start = lowered.find("url(", index)
        if start == -1:
            return values
        cursor = start + 4
        close = _find_matching_paren(value, cursor - 1, len(value))
        if close is None:
            raw = value[cursor:].strip()
            index = len(value)
        else:
            raw = value[cursor:close].strip()
            index = close + 1
        values.append(_strip_css_string(raw))


def _target_for_reference(value: str) -> dict[str, Any]:
    stripped = value.strip()
    if not stripped:
        return {
            "kind": "unknown",
            "target": unknown_key("css.reference", "missing-target"),
            "reason": "missing-reference-target",
        }
    lowered = stripped.lower()
    if lowered.startswith("data:"):
        return {
            "kind": "unknown",
            "target": unknown_key("external.url", "data-url-payload-redacted"),
            "reason": "data-url-redacted",
        }
    parsed = urlsplit(stripped)
    if parsed.scheme in ("http", "https", "mailto"):
        return {
            "kind": "external.url",
            "target": external_url_key(stripped),
            "reason": "url-literal",
            "summary": stripped,
        }
    if parsed.scheme:
        return {
            "kind": "dynamic",
            "target": dynamic_key("url", "unsupported-css-url-scheme"),
            "reason": "unsupported-url-scheme",
        }
    if _is_dynamic_value(stripped):
        return {
            "kind": "dynamic",
            "target": dynamic_key("file", "css-url-dynamic"),
            "reason": "dynamic-css-url",
        }
    path_part = stripped.split("#", 1)[0].split("?", 1)[0]
    if path_part.startswith("/"):
        return {
            "kind": "external",
            "target": external_key("file", "absolute-css-reference"),
            "reason": "absolute-file-reference",
            "summary": path_part,
        }
    return {
        "kind": "file-or-unknown",
        "target": path_part,
        "reason": "relative-file-reference",
        "summary": path_part,
    }


def _reference_observations_target_for_relative(
    relative_path: str, value: str
) -> dict[str, Any]:
    target = _target_for_reference(value)
    if target["kind"] != "file-or-unknown":
        return target
    resolved = _resolve_repo_path(relative_path, target["target"])
    if resolved is None:
        return {
            "kind": "unknown",
            "target": unknown_key("file", "repo-escaping-css-reference"),
            "reason": "repo-escaping-file-reference",
        }
    return {
        "kind": "file",
        "target": file_key(resolved),
        "reason": "relative-file-reference",
        "summary": target["summary"],
    }


def _target_for_reference_in_path(relative_path: str, value: str) -> dict[str, Any]:
    return _reference_observations_target_for_relative(relative_path, value)


def _selector_metadata(
    selector: str, rule_pointer: str, pointer: str, selector_index: int
) -> dict[str, Any]:
    classes = _ordered_unique(CLASS_PATTERN.findall(selector))
    ids = _ordered_unique(ID_PATTERN.findall(selector))
    attributes = _ordered_unique(ATTRIBUTE_PATTERN.findall(selector))
    pseudo_elements = _ordered_unique(PSEUDO_ELEMENT_PATTERN.findall(selector))
    pseudo_classes = _ordered_unique(PSEUDO_CLASS_PATTERN.findall(selector))
    element_names = _element_names(selector)
    return {
        "format": "css",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "selector_pointer": pointer,
        "rule_pointer": rule_pointer,
        "selector_text": " ".join(selector.split()),
        "selector_index": selector_index,
        "classes": classes,
        "ids": ids,
        "element_names": element_names,
        "attributes": attributes,
        "pseudo_classes": pseudo_classes,
        "pseudo_elements": pseudo_elements,
        "selector_kind": _selector_kind(selector, classes, ids, attributes, pseudo_classes, pseudo_elements, element_names),
    }


def _selector_kind(
    selector: str,
    classes: list[str],
    ids: list[str],
    attributes: list[str],
    pseudo_classes: list[str],
    pseudo_elements: list[str],
    element_names: list[str],
) -> str:
    component_count = (
        len(classes)
        + len(ids)
        + len(attributes)
        + len(pseudo_classes)
        + len(pseudo_elements)
        + len(element_names)
    )
    if any(combinator in selector for combinator in (" ", ">", "+", "~")):
        return "complex"
    if component_count <= 1:
        return "simple"
    return "complex" if (attributes or pseudo_classes or pseudo_elements) else "compound"


def _element_names(selector: str) -> list[str]:
    scrubbed = re.sub(r"\[[^\]]*\]", " ", selector)
    scrubbed = re.sub(r"::?[A-Za-z_][A-Za-z0-9_-]*", " ", scrubbed)
    scrubbed = re.sub(r"[.#][A-Za-z_][A-Za-z0-9_-]*", " ", scrubbed)
    names = []
    for candidate in IDENTIFIER_PATTERN.findall(scrubbed):
        if candidate in ("not", "is", "where"):
            continue
        names.append(candidate)
    return _ordered_unique(names)


def _split_selectors(selector_text: str) -> list[str]:
    selectors = []
    start = 0
    index = 0
    in_string: str | None = None
    escaped = False
    bracket_depth = 0
    paren_depth = 0
    while index < len(selector_text):
        character = selector_text[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == in_string:
                in_string = None
            index += 1
            continue
        if character in ("'", '"'):
            in_string = character
        elif character == "[":
            bracket_depth += 1
        elif character == "]" and bracket_depth:
            bracket_depth -= 1
        elif character == "(":
            paren_depth += 1
        elif character == ")" and paren_depth:
            paren_depth -= 1
        elif character == "," and bracket_depth == 0 and paren_depth == 0:
            selector = selector_text[start:index].strip()
            if selector:
                selectors.append(" ".join(selector.split()))
            start = index + 1
        index += 1
    selector = selector_text[start:].strip()
    if selector:
        selectors.append(" ".join(selector.split()))
    return selectors


def _custom_property_names(rules: list[_CssRule]) -> set[str]:
    return {
        declaration.property_name
        for rule in rules
        for declaration in rule.declarations
        if declaration.property_name.startswith("--")
    }


def _font_family(rule: _CssRule) -> str | None:
    for declaration in rule.declarations:
        if declaration.property_name.lower() == "font-family" and not _is_secret_name(
            declaration.value
        ):
            return _safe_summary(declaration.value)
    return None


def _next_pointer(
    parent_pointer: str | None, kind: str, counters: dict[str, int]
) -> str:
    counters[kind] = counters.get(kind, 0) + 1
    segment = f"{kind}:{counters[kind]}"
    if parent_pointer is None:
        return f"/{segment}"
    return f"{parent_pointer}/{segment}"


def _find_at_rule_delimiter(
    content: str, start: int, end: int
) -> tuple[int | None, str | None]:
    index = start
    in_string: str | None = None
    escaped = False
    paren_depth = 0
    while index < end:
        character = content[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == in_string:
                in_string = None
            index += 1
            continue
        if character in ("'", '"'):
            in_string = character
        elif character == "(":
            paren_depth += 1
        elif character == ")" and paren_depth:
            paren_depth -= 1
        elif paren_depth == 0 and character in (";", "{"):
            return index, character
        index += 1
    return None, None


def _find_next_top_level_char(
    content: str, needle: str, start: int, end: int
) -> int | None:
    index = start
    in_string: str | None = None
    escaped = False
    bracket_depth = 0
    paren_depth = 0
    while index < end:
        character = content[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == in_string:
                in_string = None
            index += 1
            continue
        if character in ("'", '"'):
            in_string = character
        elif character == "[":
            bracket_depth += 1
        elif character == "]" and bracket_depth:
            bracket_depth -= 1
        elif character == "(":
            paren_depth += 1
        elif character == ")" and paren_depth:
            paren_depth -= 1
        elif character == needle and bracket_depth == 0 and paren_depth == 0:
            return index
        index += 1
    return None


def _find_matching_brace(content: str, open_index: int, end: int) -> int | None:
    return _find_matching_delimiter(content, open_index, end, "{", "}")


def _find_matching_paren(content: str, open_index: int, end: int) -> int | None:
    return _find_matching_delimiter(content, open_index, end, "(", ")")


def _find_matching_delimiter(
    content: str, open_index: int, end: int, open_char: str, close_char: str
) -> int | None:
    depth = 0
    index = open_index
    in_string: str | None = None
    escaped = False
    while index < end:
        character = content[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == in_string:
                in_string = None
            index += 1
            continue
        if character in ("'", '"'):
            in_string = character
        elif character == open_char:
            depth += 1
        elif character == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _skip_whitespace(content: str, index: int, end: int) -> int:
    while index < end and content[index].isspace():
        index += 1
    return index


def _strip_comments(content: str) -> str:
    output: list[str] = []
    index = 0
    in_string: str | None = None
    escaped = False
    while index < len(content):
        character = content[index]
        next_character = content[index + 1] if index + 1 < len(content) else ""
        if in_string is not None:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == in_string:
                in_string = None
            index += 1
            continue
        if character in ("'", '"'):
            in_string = character
            output.append(character)
            index += 1
            continue
        if character == "/" and next_character == "*":
            output.extend((" ", " "))
            index += 2
            while index < len(content):
                if content[index] == "*" and index + 1 < len(content) and content[index + 1] == "/":
                    output.extend((" ", " "))
                    index += 2
                    break
                output.append("\n" if content[index] in "\r\n" else " ")
                index += 1
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _strip_css_string(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ("'", '"'):
        return stripped[1:-1]
    return stripped


def _line_for_index(content: str, index: int) -> int:
    return content.count("\n", 0, max(0, index)) + 1


def _safe_summary(value: str | None) -> str | None:
    if value is None:
        return None
    summary = " ".join(value.split())
    if not summary or _is_secret_name(summary):
        return None
    if not summary.isprintable():
        return None
    if summary.lower().startswith("data:"):
        return "data-url-redacted"
    return summary[:120]


def _value_type(value: str) -> str:
    lowered = value.lower()
    if "url(" in lowered:
        return "url"
    if "var(" in lowered:
        return "custom-property-reference"
    if "(" in value and ")" in value:
        return "function"
    return "literal"


def _is_secret_name(value: str | None) -> bool:
    if value is None:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return any(marker in normalized for marker in SECRET_PRONE_MARKERS)


def _is_dynamic_value(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in DYNAMIC_MARKERS)


def _resolve_repo_path(relative_path: str, value: str) -> str | None:
    if not value:
        return None
    base = PurePosixPath(relative_path).parent
    candidate = PurePosixPath(value)
    combined = base / candidate
    parts: list[str] = []
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _ordered_unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
