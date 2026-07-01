"""Conservative local document raw observation extraction."""

from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from repomap_kg import __version__
from repomap_kg.graph_keys import (
    document_column_key,
    document_file_key,
    document_latex_command_key,
    document_section_key,
    document_sheet_key,
    document_table_key,
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR_NAME = "repo-documents"
PARSER_NAME = "stdlib-document-conservative"
MAX_TEXT_SUMMARY_CHARS = 160
MAX_ROWS = 2000
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
    "ssn",
    "social_security",
    "tax_id",
    "account_number",
    "routing_number",
    "iban",
    "credit_card",
    "medical_record",
    "patient_id",
)
URL_PATTERN = re.compile(r"\b(?:https?://[^\s<>)]+|mailto:[^\s<>)]+)")
PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_./~-])(?:/|\.{1,2}/)?[A-Za-z0-9_${}~*?.-]+"
    r"(?:/[A-Za-z0-9_${}~*?.-]+)+"
)
TXT_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LATEX_COMMAND_PATTERN = re.compile(r"\\([A-Za-z]+)\s*(?:\[[^\]]*\]\s*)?(?:\{([^{}]*)\})?")
LATEX_SECTION_LEVELS = {
    "part": 1,
    "chapter": 2,
    "section": 3,
    "subsection": 4,
    "subsubsection": 5,
    "paragraph": 6,
}
LATEX_COMMANDS = frozenset(
    (
        "label",
        "ref",
        "pageref",
        "autoref",
        "cite",
        "citep",
        "citet",
        "input",
        "include",
        "includegraphics",
        "bibliography",
        "addbibresource",
        "usepackage",
        "url",
        "href",
    )
)
ODF_FORMATS = {
    ".odt": ("odt", False, "text"),
    ".ott": ("ott", True, "text"),
    ".ods": ("ods", False, "spreadsheet"),
    ".ots": ("ots", True, "spreadsheet"),
}
ODF_NAMESPACES = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
}
ODF_SAFE_PARTS = frozenset(
    ("content.xml", "meta.xml", "styles.xml", "META-INF/manifest.xml")
)
ODF_INTERNAL_REFERENCE_TARGET = unknown_key(
    "document.reference", "odf-internal-package-part"
)
DEFAULT_MAX_PACKAGE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_FILE_COUNT = 128
DEFAULT_MAX_PART_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


@dataclass(frozen=True)
class _Reference:
    source_key: str
    raw_value: str
    target_key: str
    reference_kind: str
    resolution_reason: str
    line_number: int
    command: str | None = None


def extract_document_file_observations(
    relative_path: str,
    content: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    suffix = PurePosixPath(relative_path).suffix.lower()
    if suffix == ".txt":
        return _extract_text(relative_path, content, repository_paths=repository_paths)
    if suffix == ".csv":
        return _extract_table(
            relative_path,
            content,
            delimiter=",",
            document_format="csv",
            repository_paths=repository_paths,
        )
    if suffix == ".tsv":
        return _extract_table(
            relative_path,
            content,
            delimiter="\t",
            document_format="tsv",
            repository_paths=repository_paths,
        )
    if suffix in (".tex", ".latex"):
        return _extract_latex(relative_path, content, repository_paths=repository_paths)
    return ()


def extract_odf_file_observations(
    relative_path: str,
    package_bytes: bytes,
    *,
    repository_paths: frozenset[str] | None = None,
    max_package_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,
    max_total_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_file_count: int = DEFAULT_MAX_FILE_COUNT,
    max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
) -> tuple[RawObservation, ...]:
    suffix = PurePosixPath(relative_path).suffix.lower()
    format_info = ODF_FORMATS.get(suffix)
    if format_info is None:
        return ()
    document_format, template, document_family = format_info
    if len(package_bytes) > max_package_bytes:
        return (
            _parse_error(
                relative_path,
                document_format,
                "zip-package-size-limit",
                "ODF package exceeds configured compressed byte limit",
                line_number=None,
            ),
        )
    try:
        with zipfile.ZipFile(io.BytesIO(package_bytes)) as package:
            members = package.infolist()
            safety_error = _odf_package_safety_error(
                relative_path,
                document_format,
                members,
                max_total_uncompressed_bytes=max_total_uncompressed_bytes,
                max_file_count=max_file_count,
                max_part_bytes=max_part_bytes,
            )
            if safety_error is not None:
                return (safety_error,)
            parts: dict[str, bytes] = {}
            for member in members:
                if member.filename in ODF_SAFE_PARTS:
                    parts[member.filename] = package.read(member)
    except (OSError, zipfile.BadZipFile):
        return (
            _parse_error(
                relative_path,
                document_format,
                "malformed-zip",
                "ODF package is not a valid ZIP archive",
                line_number=None,
            ),
        )
    parsed_parts: dict[str, ElementTree.Element] = {}
    for part_name, part_bytes in parts.items():
        if _xml_bytes_are_dangerous(part_bytes):
            return (
                _parse_error(
                    relative_path,
                    document_format,
                    "dangerous-xml",
                    f"ODF part {part_name} contains disallowed XML constructs",
                    line_number=None,
                ),
            )
        try:
            parsed_parts[part_name] = ElementTree.fromstring(part_bytes)
        except ElementTree.ParseError as error:
            return (
                _parse_error(
                    relative_path,
                    document_format,
                    "malformed-xml",
                    f"ODF part {part_name} is malformed: {error}",
                    line_number=None,
                ),
            )

    content_root = parsed_parts.get("content.xml")
    if content_root is None:
        return (
            _parse_error(
                relative_path,
                document_format,
                "missing-content-xml",
                "ODF package does not contain content.xml",
                line_number=None,
            ),
        )
    package_metadata = _odf_package_metadata(
        package_bytes,
        members,
        parsed_parts,
        document_format=document_format,
        template=template,
    )
    if document_family == "spreadsheet":
        return _extract_odf_spreadsheet(
            relative_path,
            content_root,
            parsed_parts,
            document_format=document_format,
            template=template,
            package_metadata=package_metadata,
            repository_paths=repository_paths,
        )
    return _extract_odf_text_document(
        relative_path,
        content_root,
        parsed_parts,
        document_format=document_format,
        template=template,
        package_metadata=package_metadata,
        repository_paths=repository_paths,
    )


def _odf_package_safety_error(
    relative_path: str,
    document_format: str,
    members: list[zipfile.ZipInfo],
    *,
    max_total_uncompressed_bytes: int,
    max_file_count: int,
    max_part_bytes: int,
) -> RawObservation | None:
    if len(members) > max_file_count:
        return _parse_error(
            relative_path,
            document_format,
            "zip-file-count-limit",
            "ODF package exceeds configured file-count limit",
            line_number=None,
        )
    total_uncompressed = 0
    for member in members:
        name = member.filename
        normalized = posixpath.normpath(name)
        if (
            name.startswith("/")
            or "\\" in name
            or normalized == ".."
            or normalized.startswith("../")
        ):
            return _parse_error(
                relative_path,
                document_format,
                "zip-path-traversal",
                "ODF package contains a path traversal or absolute entry",
                line_number=None,
            )
        total_uncompressed += member.file_size
        if total_uncompressed > max_total_uncompressed_bytes:
            return _parse_error(
                relative_path,
                document_format,
                "zip-uncompressed-limit",
                "ODF package exceeds configured uncompressed byte limit",
                line_number=None,
            )
        if member.file_size > max_part_bytes:
            return _parse_error(
                relative_path,
                document_format,
                "zip-part-size-limit",
                "ODF package part exceeds configured per-part byte limit",
                line_number=None,
            )
        if (
            member.compress_size > 0
            and member.file_size > 1024 * 1024
            and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO
        ):
            return _parse_error(
                relative_path,
                document_format,
                "zip-compression-ratio-limit",
                "ODF package has a suspicious compression ratio",
                line_number=None,
            )
    return None


def _xml_bytes_are_dangerous(part_bytes: bytes) -> bool:
    lowered = part_bytes[:2048].lower()
    return b"<!doctype" in lowered or b"<!entity" in lowered


def _odf_package_metadata(
    package_bytes: bytes,
    members: list[zipfile.ZipInfo],
    parsed_parts: dict[str, ElementTree.Element],
    *,
    document_format: str,
    template: bool,
) -> dict[str, Any]:
    total_uncompressed = sum(member.file_size for member in members)
    skipped_parts = [
        member.filename for member in members if member.filename not in ODF_SAFE_PARTS
    ]
    metadata: dict[str, Any] = {
        "format": document_format,
        "parser": PARSER_NAME,
        "package_parser": "stdlib-zipfile",
        "document_kind": document_format,
        "template": template,
        "package_byte_count": len(package_bytes),
        "package_part_count": len(members),
        "parsed_part_count": len(parsed_parts),
        "skipped_part_count": len(skipped_parts),
        "total_uncompressed_bytes": total_uncompressed,
        "macro_script_ignored": True,
    }
    title = _odf_meta_title(parsed_parts.get("meta.xml"))
    if title is not None:
        metadata["title_summary"] = title
    style_count = _odf_style_count(parsed_parts.get("styles.xml"))
    if style_count:
        metadata["style_count"] = style_count
    return metadata


def _extract_odf_text_document(
    relative_path: str,
    content_root: ElementTree.Element,
    parsed_parts: dict[str, ElementTree.Element],
    *,
    document_format: str,
    template: bool,
    package_metadata: dict[str, Any],
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    document_key = document_file_key(relative_path)
    parent_map = _parent_map(content_root)
    headings = list(content_root.iter(_q("text", "h")))
    paragraphs = [
        paragraph
        for paragraph in content_root.iter(_q("text", "p"))
        if not _has_ancestor(paragraph, parent_map, _q("table", "table"))
    ]
    tables = list(content_root.iter(_q("table", "table")))
    references: list[_Reference] = []
    observations: list[RawObservation] = []
    current_source_key = document_key
    heading_count = 0
    for element in content_root.iter():
        if element.tag == _q("text", "h"):
            heading_count += 1
            heading = _element_text(element)
            pointer = _pointer_for_slug("sections", _slugify(heading))
            current_source_key = document_section_key(relative_path, pointer)
            observations.append(
                RawObservation(
                    kind="document.odf_text",
                    source_id=f"{relative_path}#odf-heading:{heading_count}",
                    path=relative_path,
                    name=pointer,
                    target=current_source_key,
                    confidence="extracted",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata={
                        "format": document_format,
                        "parser": PARSER_NAME,
                        "document_key": document_key,
                        "source_part": "content.xml",
                        "pointer": pointer,
                        "heading_level": _odf_heading_level(element),
                        "heading_summary": _redacted_or_summary(heading),
                        "redacted": _contains_secret_marker(heading),
                    },
                )
            )
        elif element.tag == _q("text", "p"):
            for href in _odf_href_values(element):
                references.append(
                    _odf_reference(
                        relative_path,
                        href,
                        source_key=current_source_key,
                        repository_paths=repository_paths,
                        reference_kind="url",
                        resolution_reason="odf-xlink-href",
                    )
                )

    table_observations, table_references = _odf_table_observations(
        relative_path,
        tables,
        document_format=document_format,
        document_key=document_key,
        table_prefix="tables",
        parent_kind="table",
        repository_paths=repository_paths,
    )
    references.extend(table_references)
    references.extend(
        _odf_manifest_references(
            relative_path,
            parsed_parts.get("META-INF/manifest.xml"),
            source_key=document_key,
            repository_paths=repository_paths,
        )
    )
    metadata = {
        **package_metadata,
        "paragraph_count": len(paragraphs),
        "heading_count": len(headings),
        "table_count": len(tables),
        "sheet_count": 0,
        "reference_count": len(references),
        "formulas_evaluated": False,
        "formula_count": 0,
    }
    return (
        RawObservation(
            kind="document.odf_document",
            source_id=f"{relative_path}#odf-document",
            path=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            target=document_key,
            metadata=metadata,
        ),
        *observations,
        *table_observations,
        *_reference_observations(relative_path, references, document_format),
    )


def _extract_odf_spreadsheet(
    relative_path: str,
    content_root: ElementTree.Element,
    parsed_parts: dict[str, ElementTree.Element],
    *,
    document_format: str,
    template: bool,
    package_metadata: dict[str, Any],
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    document_key = document_file_key(relative_path)
    tables = list(content_root.iter(_q("table", "table")))
    references = _odf_manifest_references(
        relative_path,
        parsed_parts.get("META-INF/manifest.xml"),
        source_key=document_key,
        repository_paths=repository_paths,
    )
    table_observations, table_references = _odf_table_observations(
        relative_path,
        tables,
        document_format=document_format,
        document_key=document_key,
        table_prefix="sheets",
        parent_kind="sheet",
        repository_paths=repository_paths,
    )
    references.extend(table_references)
    row_counts = [
        observation.metadata.get("row_count", 0)
        for observation in table_observations
        if observation.kind == "document.odf_sheet"
    ]
    column_counts = [
        observation.metadata.get("column_count", 0)
        for observation in table_observations
        if observation.kind == "document.odf_sheet"
    ]
    formula_count = sum(_odf_formula_count(table) for table in tables)
    metadata = {
        **package_metadata,
        "paragraph_count": 0,
        "heading_count": 0,
        "table_count": len(tables),
        "sheet_count": len(tables),
        "row_count_summary": max(row_counts) if row_counts else 0,
        "column_count_summary": max(column_counts) if column_counts else 0,
        "reference_count": len(references),
        "formulas_evaluated": False,
        "formula_count": formula_count,
    }
    return (
        RawObservation(
            kind="document.odf_document",
            source_id=f"{relative_path}#odf-document",
            path=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            target=document_key,
            metadata=metadata,
        ),
        *table_observations,
        *_reference_observations(relative_path, references, document_format),
    )


def _odf_table_observations(
    relative_path: str,
    tables: list[ElementTree.Element],
    *,
    document_format: str,
    document_key: str,
    table_prefix: str,
    parent_kind: str,
    repository_paths: frozenset[str] | None,
) -> tuple[list[RawObservation], list[_Reference]]:
    observations: list[RawObservation] = []
    references: list[_Reference] = []
    for table_index, table in enumerate(tables, start=1):
        table_name = _odf_table_name(table) or f"{parent_kind}-{table_index}"
        pointer = _pointer_for_slug(table_prefix, _slugify(table_name))
        rows = _odf_table_rows(table)
        header = rows[0] if rows else []
        data_rows = rows[1:] if rows else []
        column_count = max((len(row) for row in rows), default=0)
        parent_key = (
            document_sheet_key(relative_path, pointer)
            if parent_kind == "sheet"
            else document_table_key(relative_path, pointer)
        )
        kind = "document.odf_sheet" if parent_kind == "sheet" else "document.odf_table"
        observations.append(
            RawObservation(
                kind=kind,
                source_id=f"{relative_path}#odf-{parent_kind}:{table_index}",
                path=relative_path,
                name=pointer,
                target=parent_key,
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata={
                    "format": document_format,
                    "parser": PARSER_NAME,
                    "document_key": document_key,
                    "source_part": "content.xml",
                    "pointer": pointer,
                    "display_name": _redacted_or_summary(table_name),
                    "row_count": len(data_rows),
                    "column_count": column_count,
                    "header_present": bool(header),
                    "redacted": _contains_secret_marker(table_name),
                    "formula_count": _odf_formula_count(table),
                    "formulas_evaluated": False,
                },
            )
        )
        for column_index in range(column_count):
            values = [row[column_index] for row in data_rows if column_index < len(row)]
            raw_column_name = (
                header[column_index] if column_index < len(header) else f"column-{column_index + 1}"
            )
            redacted = _contains_secret_marker(raw_column_name) or any(
                _contains_secret_marker(value) for value in values
            )
            column_pointer = f"{pointer}/columns/{_slugify(raw_column_name) or f'column-{column_index + 1}'}"
            observations.append(
                RawObservation(
                    kind="document.odf_column",
                    source_id=f"{relative_path}#odf-{parent_kind}:{table_index}:column:{column_index + 1}",
                    path=relative_path,
                    name=column_pointer,
                    target=document_column_key(relative_path, column_pointer),
                    confidence="extracted",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata={
                        "format": document_format,
                        "parser": PARSER_NAME,
                        "source_part": "content.xml",
                        "pointer": column_pointer,
                        "parent_key": parent_key,
                        "column_index": column_index + 1,
                        "column_name_summary": "[redacted]"
                        if redacted
                        else _safe_value_summary(raw_column_name),
                        "type_summary": "redacted"
                        if redacted
                        else _column_type_summary(values),
                        "non_empty_count": len([value for value in values if value.strip()]),
                        "redacted": redacted,
                        "redaction_reason": "secret-prone-column-or-value"
                        if redacted
                        else None,
                    },
                )
            )
        for href in _odf_href_values(table):
            references.append(
                _odf_reference(
                    relative_path,
                    href,
                    source_key=parent_key,
                    repository_paths=repository_paths,
                    reference_kind="url",
                    resolution_reason="odf-table-href",
                )
            )
    return observations, references


def _extract_text(
    relative_path: str,
    content: str,
    *,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    lines = content.splitlines()
    sections: list[tuple[str, str, int, int]] = []
    current_section_key = document_file_key(relative_path)
    references: list[_Reference] = []
    for index, line in enumerate(lines, start=1):
        match = TXT_HEADING_PATTERN.match(line)
        if match:
            pointer = _pointer_for_slug("sections", _slugify(match.group(2)))
            current_section_key = document_section_key(relative_path, pointer)
            sections.append((pointer, match.group(2), len(match.group(1)), index))
            continue
        references.extend(
            _references_from_text(
                relative_path,
                line,
                index,
                source_key=current_section_key,
                repository_paths=repository_paths,
            )
        )

    paragraph_count = len([block for block in re.split(r"\n\s*\n", content.strip()) if block])
    metadata: dict[str, Any] = {
        "format": "txt",
        "parser": PARSER_NAME,
        "byte_count": len(content.encode("utf-8")),
        "line_count": len(lines),
        "paragraph_count": paragraph_count,
        "section_count": len(sections),
        "reference_count": len(references),
        "summary_redacted": _contains_secret_marker(content),
    }
    summary = _safe_summary(content)
    if summary is not None:
        metadata["text_summary"] = summary

    observations = [
        RawObservation(
            kind="document.text_document",
            source_id=f"{relative_path}#document-text",
            path=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            target=document_file_key(relative_path),
            metadata=metadata,
        )
    ]
    for pointer, heading, level, line_number in sections:
        observations.append(
            RawObservation(
                kind="document.text_section",
                source_id=f"{relative_path}#document-section:{pointer}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=pointer,
                confidence="heuristic",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                target=document_section_key(relative_path, pointer),
                metadata={
                    "format": "txt",
                    "pointer": pointer,
                    "heading_level": level,
                    "heading_summary": _redacted_or_summary(heading),
                    "document_key": document_file_key(relative_path),
                    "redacted": _contains_secret_marker(heading),
                },
            )
        )
    observations.extend(_reference_observations(relative_path, references, "txt"))
    return tuple(observations)


def _extract_table(
    relative_path: str,
    content: str,
    *,
    delimiter: str,
    document_format: str,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    rows: list[list[str]]
    try:
        rows = list(csv.reader(io.StringIO(content), delimiter=delimiter))
    except csv.Error as error:
        return (
            _parse_error(
                relative_path,
                document_format,
                "csv-parser-error",
                str(error),
                line_number=None,
            ),
        )
    if len(rows) > MAX_ROWS:
        rows = rows[:MAX_ROWS]
    non_empty_rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not non_empty_rows:
        return (
            RawObservation(
                kind="document.table_document",
                source_id=f"{relative_path}#document-table",
                path=relative_path,
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                target=document_table_key(relative_path, "/table"),
                metadata={
                    "format": document_format,
                    "parser": "stdlib-csv",
                    "document_key": document_file_key(relative_path),
                    "pointer": "/table",
                    "row_count": 0,
                    "column_count": 0,
                    "header_present": False,
                    "delimiter": "\\t" if delimiter == "\t" else delimiter,
                },
            ),
        )

    expected_width = max(len(row) for row in non_empty_rows)
    if any(len(row) not in (0, expected_width) for row in non_empty_rows):
        return (
            _parse_error(
                relative_path,
                document_format,
                "ragged-row",
                "rows have inconsistent column counts",
                line_number=None,
            ),
        )

    header_present = _looks_like_header(non_empty_rows[0], non_empty_rows[1:])
    headers = non_empty_rows[0] if header_present else []
    data_rows = non_empty_rows[1:] if header_present else non_empty_rows
    table_key = document_table_key(relative_path, "/table")
    references: list[_Reference] = []
    observations: list[RawObservation] = [
        RawObservation(
            kind="document.table_document",
            source_id=f"{relative_path}#document-table",
            path=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            target=table_key,
            metadata={
                "format": document_format,
                "parser": "stdlib-csv",
                "document_key": document_file_key(relative_path),
                "pointer": "/table",
                "row_count": len(data_rows),
                "column_count": expected_width,
                "header_present": header_present,
                "delimiter": "\\t" if delimiter == "\t" else delimiter,
            },
        )
    ]
    for column_index in range(expected_width):
        column_name = headers[column_index] if column_index < len(headers) else f"column-{column_index + 1}"
        values = [row[column_index] for row in data_rows if column_index < len(row)]
        redacted = _contains_secret_marker(column_name)
        pointer = _pointer_for_slug("table/columns", _slugify(column_name or f"column-{column_index + 1}"))
        type_summary = "redacted" if redacted else _column_type_summary(values)
        metadata: dict[str, Any] = {
            "format": document_format,
            "pointer": pointer,
            "table_key": table_key,
            "column_index": column_index,
            "type_summary": type_summary,
            "non_empty_count": sum(1 for value in values if value.strip()),
            "redacted": redacted,
        }
        if redacted:
            metadata["redaction_reason"] = "secret-prone-column-name"
            metadata["column_name_summary"] = "[redacted]"
        else:
            metadata["column_name_summary"] = column_name
            for row_index, value in enumerate(values, start=2 if header_present else 1):
                references.extend(
                    _references_from_text(
                        relative_path,
                        value,
                        row_index,
                        source_key=table_key,
                        repository_paths=repository_paths,
                    )
                )
        observations.append(
            RawObservation(
                kind="document.table_column",
                source_id=f"{relative_path}#document-column:{pointer}",
                path=relative_path,
                name=pointer,
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                target=document_column_key(relative_path, pointer),
                metadata=metadata,
            )
        )
    observations.extend(_reference_observations(relative_path, references, document_format))
    return tuple(observations)


def _extract_latex(
    relative_path: str,
    content: str,
    *,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    lines = _strip_latex_comments(content).splitlines()
    observations: list[RawObservation] = []
    references: list[_Reference] = []
    section_count = 0
    command_count = 0
    for line_number, line in enumerate(lines, start=1):
        for match in LATEX_COMMAND_PATTERN.finditer(line):
            command = match.group(1)
            argument = (match.group(2) or "").strip()
            if command in LATEX_SECTION_LEVELS and argument:
                section_count += 1
                pointer = _pointer_for_slug("sections", f"{section_count}-{_slugify(argument)}")
                observations.append(
                    RawObservation(
                        kind="document.latex_section",
                        source_id=f"{relative_path}#latex-section:{pointer}",
                        path=relative_path,
                        start_line=line_number,
                        end_line=line_number,
                        name=pointer,
                        confidence="heuristic",
                        extractor=EXTRACTOR_NAME,
                        extractor_version=__version__,
                        target=document_section_key(relative_path, pointer),
                        metadata={
                            "format": "latex",
                            "pointer": pointer,
                            "command": command,
                            "heading_level": LATEX_SECTION_LEVELS[command],
                            "heading_summary": _redacted_or_summary(argument),
                            "document_key": document_file_key(relative_path),
                            "redacted": _contains_secret_marker(argument),
                        },
                    )
                )
                continue
            if command not in LATEX_COMMANDS:
                continue
            command_count += 1
            pointer = f"/commands/{command}:{command_count}"
            command_key = document_latex_command_key(relative_path, pointer)
            observations.append(
                RawObservation(
                    kind="document.latex_command",
                    source_id=f"{relative_path}#latex-command:{pointer}",
                    path=relative_path,
                    start_line=line_number,
                    end_line=line_number,
                    name=pointer,
                    confidence="heuristic",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    target=command_key,
                    metadata={
                        "format": "latex",
                        "pointer": pointer,
                        "command": command,
                        "argument_summary": _redacted_or_summary(argument),
                        "document_key": document_file_key(relative_path),
                        "redacted": _contains_secret_marker(argument),
                    },
                )
            )
            reference = _latex_reference(
                relative_path,
                command,
                argument,
                line_number,
                command_key,
                repository_paths=repository_paths,
            )
            if reference is not None:
                references.append(reference)

    observations.insert(
        0,
        RawObservation(
            kind="document.latex_document",
            source_id=f"{relative_path}#latex-document",
            path=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            target=document_file_key(relative_path),
            metadata={
                "format": "latex",
                "parser": PARSER_NAME,
                "line_count": len(lines),
                "section_count": section_count,
                "command_count": command_count,
                "reference_count": len(references),
                "compiled": False,
            },
        ),
    )
    observations.extend(_reference_observations(relative_path, references, "latex"))
    return tuple(observations)


def _reference_observations(
    relative_path: str, references: list[_Reference], document_format: str
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for index, reference in enumerate(references):
        metadata: dict[str, Any] = {
            "format": document_format,
            "source_key": reference.source_key,
            "reference_kind": reference.reference_kind,
            "raw_value_summary": _safe_value_summary(reference.raw_value),
            "resolution_reason": reference.resolution_reason,
            "not_fetched": True,
            "redacted": False,
        }
        if reference.command is not None:
            metadata["command"] = reference.command
        observations.append(
            RawObservation(
                kind="document.reference",
                source_id=f"{relative_path}#document-reference:{reference.line_number}:{index}",
                path=relative_path,
                start_line=reference.line_number,
                end_line=reference.line_number,
                confidence="heuristic",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                target=reference.target_key,
                metadata=metadata,
            )
        )
    return observations


def _references_from_text(
    relative_path: str,
    text: str,
    line_number: int,
    *,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> list[_Reference]:
    if _contains_secret_marker(text):
        return []
    references: list[_Reference] = []
    consumed: list[tuple[int, int]] = []
    for match in URL_PATTERN.finditer(text):
        raw_value = match.group(0).rstrip(".,;")
        references.append(
            _reference_for_value(
                relative_path,
                raw_value,
                line_number,
                source_key=source_key,
                reference_kind="url",
                resolution_reason="url-literal",
                repository_paths=repository_paths,
            )
        )
        consumed.append(match.span())
    for match in PATH_PATTERN.finditer(text):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        raw_value = match.group(0).rstrip(".,;")
        references.append(
            _reference_for_value(
                relative_path,
                raw_value,
                line_number,
                source_key=source_key,
                reference_kind="file",
                resolution_reason="path-like-string",
                repository_paths=repository_paths,
            )
        )
    return references


def _latex_reference(
    relative_path: str,
    command: str,
    argument: str,
    line_number: int,
    source_key: str,
    *,
    repository_paths: frozenset[str] | None,
) -> _Reference | None:
    if not argument or _contains_secret_marker(argument):
        return None
    if command in ("input", "include"):
        value = argument if PurePosixPath(argument).suffix else f"{argument}.tex"
        return _reference_for_value(
            relative_path,
            value,
            line_number,
            source_key=source_key,
            reference_kind="file",
            resolution_reason=f"latex-{command}",
            repository_paths=repository_paths,
            command=command,
        )
    if command in ("includegraphics", "bibliography", "addbibresource"):
        value = argument
        if command in ("bibliography", "addbibresource") and not PurePosixPath(value).suffix:
            value = f"{value}.bib"
        return _reference_for_value(
            relative_path,
            value,
            line_number,
            source_key=source_key,
            reference_kind="file",
            resolution_reason=f"latex-{command}",
            repository_paths=repository_paths,
            command=command,
        )
    if command in ("url", "href"):
        return _reference_for_value(
            relative_path,
            argument,
            line_number,
            source_key=source_key,
            reference_kind="url",
            resolution_reason=f"latex-{command}",
            repository_paths=repository_paths,
            command=command,
        )
    return None


def _reference_for_value(
    relative_path: str,
    raw_value: str,
    line_number: int,
    *,
    source_key: str,
    reference_kind: str,
    resolution_reason: str,
    repository_paths: frozenset[str] | None,
    command: str | None = None,
) -> _Reference:
    target_key = _target_key_for_reference(relative_path, raw_value, repository_paths)
    return _Reference(
        source_key=source_key,
        raw_value=raw_value,
        target_key=target_key,
        reference_kind=reference_kind,
        resolution_reason=resolution_reason,
        line_number=line_number,
        command=command,
    )


def _target_key_for_reference(
    relative_path: str, raw_value: str, repository_paths: frozenset[str] | None
) -> str:
    split = urlsplit(raw_value)
    if split.scheme in ("http", "https", "mailto"):
        return external_url_key(raw_value)
    if split.scheme and split.scheme not in ("",):
        return unknown_key("document.reference", "unsupported-scheme")
    if raw_value.startswith("/"):
        return external_key("file", "absolute-document-reference")
    if any(marker in raw_value for marker in ("$", "${", "{{", "}}", "~", "*", "?")):
        return dynamic_key("file", "dynamic-document-reference")
    base_dir = PurePosixPath(relative_path).parent
    candidate = posixpath.normpath((base_dir / raw_value).as_posix())
    if candidate.startswith("../") or candidate == "..":
        return unknown_key("file", "repo-escaping-document-reference")
    if repository_paths is not None and candidate not in repository_paths:
        # The value is still a syntactic local reference; keep a stable file target
        # so missing local artifacts are explainable without fabricating evidence.
        return file_key(candidate)
    return file_key(candidate)


def _q(prefix: str, local_name: str) -> str:
    return f"{{{ODF_NAMESPACES[prefix]}}}{local_name}"


def _parent_map(root: ElementTree.Element) -> dict[ElementTree.Element, ElementTree.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _has_ancestor(
    element: ElementTree.Element,
    parent_map: dict[ElementTree.Element, ElementTree.Element],
    tag: str,
) -> bool:
    parent = parent_map.get(element)
    while parent is not None:
        if parent.tag == tag:
            return True
        parent = parent_map.get(parent)
    return False


def _element_text(element: ElementTree.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _odf_heading_level(element: ElementTree.Element) -> int:
    value = element.attrib.get(_q("text", "outline-level"))
    if value is None:
        return 1
    try:
        return max(1, int(value))
    except ValueError:
        return 1


def _odf_href_values(element: ElementTree.Element) -> list[str]:
    values: list[str] = []
    for child in element.iter():
        href = child.attrib.get(_q("xlink", "href"))
        if isinstance(href, str) and href.strip() and not _contains_secret_marker(href):
            values.append(href.strip())
    return values


def _odf_reference(
    relative_path: str,
    raw_value: str,
    *,
    source_key: str,
    repository_paths: frozenset[str] | None,
    reference_kind: str,
    resolution_reason: str,
) -> _Reference:
    return _Reference(
        source_key=source_key,
        raw_value=raw_value,
        target_key=_target_key_for_reference(relative_path, raw_value, repository_paths),
        reference_kind=reference_kind,
        resolution_reason=resolution_reason,
        line_number=1,
    )


def _odf_manifest_references(
    relative_path: str,
    manifest_root: ElementTree.Element | None,
    *,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> list[_Reference]:
    if manifest_root is None:
        return []
    references: list[_Reference] = []
    for entry in manifest_root.iter(_q("manifest", "file-entry")):
        full_path = entry.attrib.get(_q("manifest", "full-path"))
        if not isinstance(full_path, str) or not full_path or full_path in ("/", "."):
            continue
        if full_path in ODF_SAFE_PARTS or full_path.endswith("/"):
            continue
        if _contains_secret_marker(full_path):
            continue
        split = urlsplit(full_path)
        target_key = (
            _target_key_for_reference(relative_path, full_path, repository_paths)
            if split.scheme in ("http", "https", "mailto")
            else ODF_INTERNAL_REFERENCE_TARGET
        )
        references.append(
            _Reference(
                source_key=source_key,
                raw_value=full_path,
                target_key=target_key,
                reference_kind="package-part",
                resolution_reason="odf-manifest-entry",
                line_number=1,
            )
        )
    return references


def _odf_table_name(table: ElementTree.Element) -> str | None:
    name = table.attrib.get(_q("table", "name"))
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _odf_table_rows(table: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.findall(_q("table", "table-row")):
        row_values: list[str] = []
        for cell in row.findall(_q("table", "table-cell")):
            repeat = _odf_repeat_count(cell)
            cell_text = _element_text(cell)
            row_values.extend([cell_text] * repeat)
        rows.append(row_values)
    return rows


def _odf_repeat_count(cell: ElementTree.Element) -> int:
    value = cell.attrib.get(_q("table", "number-columns-repeated"))
    if value is None:
        return 1
    try:
        return min(100, max(1, int(value)))
    except ValueError:
        return 1


def _odf_formula_count(table: ElementTree.Element) -> int:
    return sum(
        1
        for element in table.iter()
        if any(key.endswith("}formula") for key in element.attrib)
    )


def _odf_meta_title(root: ElementTree.Element | None) -> str | None:
    if root is None:
        return None
    title = root.find(f".//{_q('dc', 'title')}")
    if title is None:
        return None
    text = _element_text(title)
    if not text or _contains_secret_marker(text):
        return None
    return _safe_value_summary(text)


def _odf_style_count(root: ElementTree.Element | None) -> int:
    if root is None:
        return 0
    return len(list(root.iter(_q("style", "style"))))


def _parse_error(
    relative_path: str,
    document_format: str,
    error_kind: str,
    message: str,
    *,
    line_number: int | None,
) -> RawObservation:
    return RawObservation(
        kind="document.parse_error",
        source_id=f"{relative_path}#document-parse-error:{error_kind}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "format": document_format,
            "parser": PARSER_NAME,
            "error_kind": error_kind,
            "message_summary": message[:120],
            "recovered": False,
        },
    )


def _looks_like_header(header: list[str], data_rows: list[list[str]]) -> bool:
    if not header or any(not cell.strip() for cell in header):
        return False
    normalized = [cell.strip().lower() for cell in header]
    if len(set(normalized)) != len(normalized):
        return False
    if not data_rows:
        return True
    header_textish = sum(1 for cell in header if _scalar_type(cell) == "text")
    first_data = data_rows[0]
    data_non_text = sum(1 for cell in first_data if _scalar_type(cell) != "text")
    return header_textish >= max(1, len(header) // 2) and data_non_text > 0


def _column_type_summary(values: list[str]) -> str:
    non_empty = [value.strip() for value in values if value.strip()]
    if not non_empty:
        return "empty"
    counts = Counter(_scalar_type(value) for value in non_empty)
    if len(counts) == 1:
        return next(iter(counts))
    if len(counts) == 2 and "empty" in counts:
        del counts["empty"]
        if len(counts) == 1:
            return next(iter(counts))
    return "mixed"


def _scalar_type(value: str) -> str:
    text = value.strip()
    if not text:
        return "empty"
    lowered = text.lower()
    if lowered in ("true", "false", "yes", "no"):
        return "boolean"
    if re.fullmatch(r"[+-]?\d+", text):
        return "integer"
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", text):
        return "decimal"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.-]+Z?)?", text):
        return "date-like"
    if URL_PATTERN.fullmatch(text):
        return "url-like"
    return "text"


def _strip_latex_comments(content: str) -> str:
    stripped_lines = []
    for line in content.splitlines():
        index = 0
        comment_at: int | None = None
        while True:
            index = line.find("%", index)
            if index == -1:
                break
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                comment_at = index
                break
            index += 1
        stripped_lines.append(line[:comment_at] if comment_at is not None else line)
    return "\n".join(stripped_lines)


def _pointer_for_slug(prefix: str, slug: str) -> str:
    return "/" + "/".join(part for part in (prefix, slug or "untitled") if part)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug[:64] or "untitled"


def _safe_summary(content: str) -> str | None:
    if _contains_secret_marker(content):
        return None
    collapsed = " ".join(content.split())
    if not collapsed:
        return None
    return collapsed[:MAX_TEXT_SUMMARY_CHARS]


def _redacted_or_summary(value: str) -> str:
    if _contains_secret_marker(value):
        return "[redacted]"
    return _safe_value_summary(value)


def _safe_value_summary(value: str) -> str:
    if _contains_secret_marker(value):
        return "[redacted]"
    return " ".join(value.split())[:120]


def _contains_secret_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SECRET_PRONE_MARKERS)
