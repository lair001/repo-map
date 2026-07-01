"""Canonical graph key builders, parser, and validator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any


GRAPH_KEY_VERSION = 1
SAFE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
HEX_CHARS = frozenset("0123456789ABCDEF")

_SEGMENT_COUNTS = {
    "tool": 1,
    "env": 1,
    "host.category": 1,
    "python.module": 1,
    "python.class": 2,
    "python.function": 2,
    "python.method": 3,
    "nix.app": 3,
    "nix.package": 3,
    "nix.devShell": 3,
    "nix.check": 3,
    "nix.output": 2,
    "doc.page": 1,
    "doc.section": 2,
    "doc.adr": 1,
    "doc.skill": 1,
    "external.url": 1,
    "config.document": 1,
    "config.path": 2,
    "css.document": 1,
    "css.rule": 2,
    "css.selector": 2,
    "css.custom_property": 2,
    "html.document": 1,
    "html.element": 2,
    "html.anchor": 2,
    "xml.document": 1,
    "xml.element": 2,
    "xml.attribute": 3,
    "feed.document": 1,
    "feed.channel": 2,
    "feed.item": 2,
    "feed.author": 2,
    "feed.category": 2,
    "warc.document": 1,
    "warc.record": 2,
    "document.file": 1,
    "document.section": 2,
    "document.table": 2,
    "document.sheet": 2,
    "document.column": 2,
    "document.latex_command": 2,
    "ruby.file": 1,
    "ruby.module": 1,
    "ruby.class": 1,
    "ruby.method": 2,
    "ruby.singleton_method": 2,
    "ruby.constant": 2,
    "ruby.test_case": 2,
    "ruby.test_method": 2,
    "ruby.route": 2,
    "js.file": 1,
    "js.module": 1,
    "js.function": 2,
    "js.class": 2,
    "js.method": 2,
    "js.variable": 2,
    "js.component": 2,
    "js.test_suite": 2,
    "js.test_case": 2,
    "js.route": 2,
    "email.mailbox": 1,
    "email.message": 2,
    "email.address": 1,
    "email.part": 2,
    "email.attachment_stub": 2,
    "email.thread_hint": 2,
    "dynamic": 2,
    "external": 2,
    "unknown": 2,
}


class GraphKeyError(ValueError):
    """Raised when a canonical graph key cannot be built or parsed."""


@dataclass(frozen=True)
class ParsedGraphKey:
    graph_key_version: int
    namespace: str
    segments: tuple[str, ...]
    key: str
    path: str | None = None


@dataclass(frozen=True)
class GraphKeyValidation:
    valid: bool
    error: str | None = None


def file_key(path: str | os.PathLike[str]) -> str:
    components = _normalize_file_components(path)
    return "file:" + "/".join(_encode_segment(component) for component in components)


def tool_key(name: str) -> str:
    return _key("tool", name)


def env_key(name: str) -> str:
    return _key("env", name)


def host_category_key(category: str) -> str:
    return _key("host.category", category)


def python_module_key(name: str) -> str:
    return _key("python.module", name)


def python_class_key(module: str, class_name: str) -> str:
    return _key("python.class", module, class_name)


def python_function_key(module: str, function_name: str) -> str:
    return _key("python.function", module, function_name)


def python_method_key(module: str, class_name: str, method_name: str) -> str:
    return _key("python.method", module, class_name, method_name)


def nix_app_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.app", flake_ref, system, name)


def nix_package_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.package", flake_ref, system, name)


def nix_dev_shell_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.devShell", flake_ref, system, name)


def nix_check_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.check", flake_ref, system, name)


def nix_output_key(flake_ref: str, output_path: str) -> str:
    return _key("nix.output", flake_ref, output_path)


def doc_page_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("doc.page", _coerce_file_key(path_or_file_key))


def doc_section_key(path_or_file_key: str | os.PathLike[str], anchor: str) -> str:
    return _key("doc.section", _coerce_file_key(path_or_file_key), anchor)


def doc_adr_key(number: str) -> str:
    return _key("doc.adr", number)


def doc_skill_key(name: str) -> str:
    return _key("doc.skill", name)


def external_url_key(url: str) -> str:
    return _key("external.url", url)


def config_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("config.document", _coerce_file_key(path_or_file_key))


def config_path_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("config.path", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def css_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("css.document", _coerce_file_key(path_or_file_key))


def css_rule_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("css.rule", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def css_selector_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "css.selector",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def css_custom_property_key(
    path_or_file_key: str | os.PathLike[str], property_name: str
) -> str:
    return _key("css.custom_property", _coerce_file_key(path_or_file_key), property_name)


def html_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("html.document", _coerce_file_key(path_or_file_key))


def html_element_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("html.element", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def html_anchor_key(path_or_file_key: str | os.PathLike[str], fragment: str) -> str:
    return _key("html.anchor", _coerce_file_key(path_or_file_key), fragment)


def xml_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("xml.document", _coerce_file_key(path_or_file_key))


def xml_element_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("xml.element", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def xml_attribute_key(
    path_or_file_key: str | os.PathLike[str],
    pointer: str,
    attribute_name: str,
) -> str:
    return _key(
        "xml.attribute",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
        attribute_name,
    )


def feed_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("feed.document", _coerce_file_key(path_or_file_key))


def feed_channel_key(feed_document_canonical_key: str, channel_id: str) -> str:
    return _key(
        "feed.channel",
        _coerce_namespace_key(feed_document_canonical_key, "feed.document"),
        channel_id,
    )


def feed_item_key(feed_channel_canonical_key: str, item_id: str) -> str:
    return _key(
        "feed.item",
        _coerce_namespace_key(feed_channel_canonical_key, "feed.channel"),
        item_id,
    )


def feed_author_key(feed_channel_canonical_key: str, author_id: str) -> str:
    return _key(
        "feed.author",
        _coerce_namespace_key(feed_channel_canonical_key, "feed.channel"),
        author_id,
    )


def feed_category_key(feed_channel_canonical_key: str, category_id: str) -> str:
    return _key(
        "feed.category",
        _coerce_namespace_key(feed_channel_canonical_key, "feed.channel"),
        category_id,
    )


def warc_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("warc.document", _coerce_file_key(path_or_file_key))


def warc_record_key(warc_document_canonical_key: str, record_id: str) -> str:
    return _key(
        "warc.record",
        _coerce_namespace_key(warc_document_canonical_key, "warc.document"),
        record_id,
    )


def document_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("document.file", _coerce_file_key(path_or_file_key))


def document_section_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.section",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_table_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.table",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_sheet_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.sheet",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_column_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.column",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_latex_command_key(
    path_or_file_key: str | os.PathLike[str], pointer: str
) -> str:
    return _key(
        "document.latex_command",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def ruby_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("ruby.file", _coerce_file_key(path_or_file_key))


def ruby_module_key(name: str) -> str:
    return _key("ruby.module", name)


def ruby_class_key(class_name: str) -> str:
    return _key("ruby.class", class_name)


def ruby_method_key(owner: str, method_name: str) -> str:
    return _key("ruby.method", owner, method_name)


def ruby_singleton_method_key(owner: str, method_name: str) -> str:
    return _key("ruby.singleton_method", owner, method_name)


def ruby_constant_key(owner: str, constant_name: str) -> str:
    return _key("ruby.constant", owner, constant_name)


def ruby_test_case_key(path_or_file_key: str | os.PathLike[str], name: str) -> str:
    return _key("ruby.test_case", _coerce_file_key(path_or_file_key), name)


def ruby_test_method_key(test_case_canonical_key: str, method_name: str) -> str:
    return _key(
        "ruby.test_method",
        _coerce_namespace_key(test_case_canonical_key, "ruby.test_case"),
        method_name,
    )


def ruby_route_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("ruby.route", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def js_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("js.file", _coerce_file_key(path_or_file_key))


def js_module_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("js.module", _coerce_file_key(path_or_file_key))


def js_function_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.function", _coerce_file_key(path_or_file_key), _coerce_js_pointer(pointer))


def js_class_key(path_or_file_key: str | os.PathLike[str], class_name: str) -> str:
    return _key("js.class", _coerce_file_key(path_or_file_key), class_name)


def js_method_key(js_class_canonical_key: str, method_name: str) -> str:
    return _key(
        "js.method",
        _coerce_namespace_key(js_class_canonical_key, "js.class"),
        method_name,
    )


def js_variable_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.variable", _coerce_file_key(path_or_file_key), _coerce_js_pointer(pointer))


def js_component_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.component", _coerce_file_key(path_or_file_key), _coerce_js_pointer(pointer))


def js_test_suite_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.test_suite", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def js_test_case_key(owner_canonical_key: str, pointer: str) -> str:
    parsed = parse_key(owner_canonical_key)
    if parsed.namespace not in ("js.file", "js.test_suite"):
        raise GraphKeyError("js.test_case keys require js.file or js.test_suite owner")
    return _key("js.test_case", owner_canonical_key, _coerce_pointer(pointer))


def js_route_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.route", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def email_message_key(path_or_file_key: str | os.PathLike[str], identity: str) -> str:
    return _key("email.message", _coerce_file_key(path_or_file_key), identity)


def email_mailbox_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("email.mailbox", _coerce_file_key(path_or_file_key))


def email_address_key(address_identity: str) -> str:
    return _key("email.address", address_identity)


def email_part_key(email_message_canonical_key: str, pointer: str) -> str:
    return _key(
        "email.part",
        _coerce_namespace_key(email_message_canonical_key, "email.message"),
        _coerce_pointer(pointer),
    )


def email_attachment_stub_key(
    email_message_canonical_key: str, pointer: str
) -> str:
    return _key(
        "email.attachment_stub",
        _coerce_namespace_key(email_message_canonical_key, "email.message"),
        _coerce_pointer(pointer),
    )


def email_thread_hint_key(email_message_canonical_key: str, pointer: str) -> str:
    return _key(
        "email.thread_hint",
        _coerce_namespace_key(email_message_canonical_key, "email.message"),
        _coerce_pointer(pointer),
    )


def dynamic_key(domain: str, reason: str) -> str:
    return _key("dynamic", domain, reason)


def external_key(domain: str, stable_name: str) -> str:
    return _key("external", domain, stable_name)


def unknown_key(domain: str, reason: str) -> str:
    return _key("unknown", domain, reason)


def parse_key(key: str) -> ParsedGraphKey:
    if not isinstance(key, str):
        raise GraphKeyError("canonical key must be a string")
    if not key:
        raise GraphKeyError("canonical key is required")
    namespace, separator, remainder = key.partition(":")
    if not separator:
        raise GraphKeyError("canonical key must include a namespace separator")
    if namespace == "file":
        segments = _parse_file_segments(remainder)
        return ParsedGraphKey(
            graph_key_version=GRAPH_KEY_VERSION,
            namespace=namespace,
            segments=segments,
            key=key,
            path="/".join(segments),
        )
    expected_count = _SEGMENT_COUNTS.get(namespace)
    if expected_count is None:
        raise GraphKeyError(f"unknown canonical key namespace: {namespace}")
    raw_segments = remainder.split(":")
    if len(raw_segments) != expected_count:
        raise GraphKeyError(f"{namespace} keys require {expected_count} segments")
    segments = tuple(_decode_segment(segment) for segment in raw_segments)
    return ParsedGraphKey(
        graph_key_version=GRAPH_KEY_VERSION,
        namespace=namespace,
        segments=segments,
        key=key,
    )


def validate_key(key: Any) -> GraphKeyValidation:
    try:
        parse_key(key)
    except GraphKeyError as error:
        return GraphKeyValidation(valid=False, error=str(error))
    return GraphKeyValidation(valid=True)


def _key(namespace: str, *segments: str) -> str:
    expected_count = _SEGMENT_COUNTS[namespace]
    if len(segments) != expected_count:
        raise GraphKeyError(f"{namespace} keys require {expected_count} segments")
    return namespace + ":" + ":".join(_encode_segment(segment) for segment in segments)


def _coerce_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    if isinstance(path_or_file_key, str) and path_or_file_key.startswith("file:"):
        parsed = parse_key(path_or_file_key)
        if parsed.namespace != "file":
            raise GraphKeyError("documentation page keys require a file key")
        return path_or_file_key
    return file_key(path_or_file_key)


def _coerce_namespace_key(key: str, namespace: str) -> str:
    parsed = parse_key(key)
    if parsed.namespace != namespace:
        raise GraphKeyError(f"{namespace} keys require a {namespace} parent key")
    return key


def _coerce_pointer(pointer: str) -> str:
    if not isinstance(pointer, str) or not pointer:
        raise GraphKeyError("config pointer is required")
    if not pointer.startswith("/"):
        raise GraphKeyError("config pointer must be normalized")
    return pointer


def _coerce_js_pointer(pointer: str) -> str:
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("JavaScript pointer is required")
    return pointer


def _normalize_file_components(path: str | os.PathLike[str]) -> tuple[str, ...]:
    if isinstance(path, PurePath):
        raw_path = path.as_posix()
    elif isinstance(path, os.PathLike):
        raw_path = os.fspath(path)
    elif isinstance(path, str):
        raw_path = path
    else:
        raise GraphKeyError("file path must be a string or path-like object")
    if not isinstance(raw_path, str) or not raw_path:
        raise GraphKeyError("file path is required")
    raw_path = raw_path.replace("\\", "/")
    if raw_path.startswith("/"):
        raise GraphKeyError("file path must not be absolute")
    components: list[str] = []
    for component in raw_path.split("/"):
        if component in ("", "."):
            continue
        if component == "..":
            if not components:
                raise GraphKeyError("file path must not escape the repository")
            components.pop()
            continue
        components.append(component)
    if not components:
        return (".",)
    return tuple(components)


def _parse_file_segments(path_text: str) -> tuple[str, ...]:
    if not path_text:
        raise GraphKeyError("file key requires a path")
    raw_segments = path_text.split("/")
    if any(segment == "" for segment in raw_segments):
        raise GraphKeyError("file key path must not contain empty components")
    segments = tuple(_decode_segment(segment) for segment in raw_segments)
    if segments == (".",):
        return segments
    if "." in segments:
        raise GraphKeyError("file key path must be normalized")
    if ".." in segments:
        raise GraphKeyError("file key path must not escape the repository")
    return segments


def _encode_segment(segment: str) -> str:
    if not isinstance(segment, str) or not segment:
        raise GraphKeyError("canonical key segment is required")
    parts: list[str] = []
    for byte in segment.encode("utf-8"):
        character = chr(byte)
        if character in SAFE_CHARS:
            parts.append(character)
        else:
            parts.append(f"%{byte:02X}")
    return "".join(parts)


def _decode_segment(segment: str) -> str:
    if segment == "":
        raise GraphKeyError("canonical key segment is required")
    decoded = bytearray()
    index = 0
    while index < len(segment):
        character = segment[index]
        if character == "%":
            decoded.append(_decode_percent_byte(segment, index))
            index += 3
            continue
        if character not in SAFE_CHARS:
            raise GraphKeyError(
                f"reserved character {character!r} must be percent-encoded"
            )
        decoded.append(ord(character))
        index += 1
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GraphKeyError("percent-encoded segment is not valid UTF-8") from error


def _decode_percent_byte(segment: str, index: int) -> int:
    escape = segment[index : index + 3]
    if len(escape) != 3:
        raise GraphKeyError("malformed percent escape")
    if escape[1].upper() != escape[1] or escape[2].upper() != escape[2]:
        raise GraphKeyError("percent escapes must use uppercase hex digits")
    if escape[1] not in HEX_CHARS or escape[2] not in HEX_CHARS:
        raise GraphKeyError("malformed percent escape")
    return int(escape[1:], 16)
