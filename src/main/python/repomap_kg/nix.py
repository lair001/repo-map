"""Static Nix raw observation extraction without evaluating Nix code."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from repomap_kg import __version__
from repomap_kg.graph_keys import (
    file_key,
    nix_app_key,
    nix_check_key,
    nix_dev_shell_key,
    nix_package_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR_NAME = "repo-nix"
SLUG_PATTERN = re.compile(r"[^0-9A-Za-z_.]+")
IMPORT_PATTERN = re.compile(
    r"\bimport\s+(?P<path>(?:\./|\../)[0-9A-Za-z_./+-]+\.nix)\b"
)
NIX_PATH_PATTERN = re.compile(r"(?<![0-9A-Za-z_$])(?P<path>(?:\./|\../)[0-9A-Za-z_./+-]+)")
OUTPUT_ATTR_PATTERN = re.compile(
    r"(?m)^\s*"
    r"(?P<root>apps|packages|devShells|checks)"
    r"\."
    r"(?P<system>[0-9A-Za-z_.+-]+)"
    r"\."
    r"(?P<name>[0-9A-Za-z_.+-]+)"
    r"\s*="
)
PROGRAM_ASSIGNMENT_PATTERN = re.compile(r"\bprogram\s*=\s*(?P<expr>[^;\n]+)")
SELF_PROGRAM_PATTERN = re.compile(r'^"\$\{self\}/(?P<path>[^"]+)"$')
TO_STRING_PROGRAM_PATTERN = re.compile(r"^toString\s+(?P<path>(?:\./|\../)\S+)$")
LITERAL_PROGRAM_PATTERN = re.compile(r"^(?P<path>(?:\./|\../)\S+)$")


def extract_nix_file_observations(
    relative_path: str,
    content: str,
    *,
    flake_ref: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    consumed_paths: set[tuple[int, str]] = set()

    imports = _extract_import_observations(relative_path, content, consumed_paths)
    observations.extend(imports)

    if PurePosixPath(relative_path).name == "flake.nix":
        outputs, program_paths = _extract_flake_output_observations(
            relative_path,
            content,
            flake_ref=flake_ref,
        )
        observations.extend(outputs)
        consumed_paths.update(program_paths)

    observations.extend(
        _extract_path_ref_observations(relative_path, content, consumed_paths)
    )
    return tuple(observations)


def _extract_import_observations(
    relative_path: str,
    content: str,
    consumed_paths: set[tuple[int, str]],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    in_imports_list = False
    for line_number, line in enumerate(content.splitlines(), start=1):
        if "imports" in line and "=" in line and "[" in line:
            in_imports_list = True
        for match in IMPORT_PATTERN.finditer(line):
            import_path = match.group("path")
            consumed_paths.add((line_number, import_path))
            observations.append(
                _nix_import_observation(
                    relative_path,
                    import_path,
                    line_number,
                    syntax="import",
                )
            )
        if in_imports_list:
            for path_match in NIX_PATH_PATTERN.finditer(line):
                import_path = path_match.group("path")
                if not import_path.endswith(".nix"):
                    continue
                if (line_number, import_path) in consumed_paths:
                    continue
                consumed_paths.add((line_number, import_path))
                observations.append(
                    _nix_import_observation(
                        relative_path,
                        import_path,
                        line_number,
                        syntax="imports-list",
                    )
                )
        if in_imports_list and "]" in line:
            in_imports_list = False
    return tuple(observations)


def _nix_import_observation(
    relative_path: str,
    import_path: str,
    line_number: int,
    *,
    syntax: str,
) -> RawObservation:
    target, metadata = _path_target_metadata(
        relative_path,
        import_path,
        literal_field="import_path",
        repo_escaping_reason="repo-escaping-nix-import",
    )
    metadata["syntax"] = syntax
    return RawObservation(
        kind="nix.import",
        source_id=f"{relative_path}#nix-import:{line_number}:{slug(import_path)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        target=target,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _extract_flake_output_observations(
    relative_path: str,
    content: str,
    *,
    flake_ref: str,
) -> tuple[tuple[RawObservation, ...], set[tuple[int, str]]]:
    matches = list(OUTPUT_ATTR_PATTERN.finditer(content))
    observations: list[RawObservation] = []
    program_paths: set[tuple[int, str]] = set()
    for index, match in enumerate(matches):
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        block = content[match.start() : block_end]
        start_line = content.count("\n", 0, match.start()) + 1
        end_line = start_line + max(0, block.count("\n"))
        root = match.group("root")
        system = match.group("system")
        name = match.group("name")
        observation, consumed_program_path = _flake_output_observation(
            relative_path,
            root,
            system,
            name,
            start_line,
            end_line,
            block,
            flake_ref=flake_ref,
        )
        observations.append(observation)
        if consumed_program_path is not None:
            program_paths.add(consumed_program_path)
    return tuple(observations), program_paths


def _flake_output_observation(
    relative_path: str,
    root: str,
    system: str,
    name: str,
    start_line: int,
    end_line: int,
    block: str,
    *,
    flake_ref: str,
) -> tuple[RawObservation, tuple[int, str] | None]:
    kind, output_kind, source_slug, target = _output_kind_and_target(
        root,
        flake_ref,
        system,
        name,
    )
    attr_path = f"{root}.{system}.{name}"
    metadata: dict[str, Any] = {
        "flake_ref": flake_ref,
        "system": system,
        "name": name,
        "attr_path": attr_path,
        "output_kind": output_kind,
    }
    if kind == "nix.app":
        metadata["app"] = name
        program_metadata, consumed_program_path = _app_program_metadata(
            relative_path,
            block,
            start_line,
        )
        metadata.update(program_metadata)
    else:
        consumed_program_path = None
    return (
        RawObservation(
            kind=kind,
            source_id=f"{relative_path}#nix-{source_slug}:{system}:{name}",
            path=relative_path,
            start_line=start_line,
            end_line=end_line,
            name=name,
            target=target,
            confidence="heuristic",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata=metadata,
        ),
        consumed_program_path,
    )


def _output_kind_and_target(
    root: str, flake_ref: str, system: str, name: str
) -> tuple[str, str, str, str]:
    if root == "apps":
        return "nix.app", "app", "app", nix_app_key(flake_ref, system, name)
    if root == "packages":
        return (
            "nix.package",
            "package",
            "package",
            nix_package_key(flake_ref, system, name),
        )
    if root == "devShells":
        return (
            "nix.devShell",
            "devShell",
            "devShell",
            nix_dev_shell_key(flake_ref, system, name),
        )
    return "nix.check", "check", "check", nix_check_key(flake_ref, system, name)


def _app_program_metadata(
    relative_path: str, block: str, start_line: int
) -> tuple[dict[str, Any], tuple[int, str] | None]:
    for offset, line in enumerate(block.splitlines()):
        match = PROGRAM_ASSIGNMENT_PATTERN.search(line)
        if match is None:
            continue
        expression = _clean_expression(match.group("expr"))
        metadata: dict[str, Any] = {"program": expression}
        self_match = SELF_PROGRAM_PATTERN.match(expression)
        if self_match is not None:
            program_path = self_match.group("path")
            if "${" in program_path:
                metadata["program_resolution"] = "dynamic"
                metadata["dynamic_reason"] = "nix-app-program-interpolation"
                return metadata, None
            target_path = resolve_repo_path(relative_path, f"${{self}}/{program_path}")
            if target_path is None:
                metadata["program_resolution"] = "unknown"
                metadata["program_target"] = unknown_key(
                    "file",
                    "repo-escaping-nix-app-program",
                )
                return metadata, None
            metadata["program_path"] = target_path
            metadata["program_resolution"] = "local"
            return metadata, (start_line + offset, f"./{target_path}")
        path_match = TO_STRING_PROGRAM_PATTERN.match(expression)
        if path_match is None:
            path_match = LITERAL_PROGRAM_PATTERN.match(expression)
        if path_match is not None:
            program_literal = _clean_path_literal(path_match.group("path"))
            target, path_metadata = _path_target_metadata(
                relative_path,
                program_literal,
                literal_field="program_literal",
                repo_escaping_reason="repo-escaping-nix-app-program",
            )
            if path_metadata["resolution"] == "local":
                metadata["program_path"] = path_metadata["resolved_path"]
                metadata["program_resolution"] = "local"
                return metadata, (start_line + offset, program_literal)
            metadata["program_resolution"] = path_metadata["resolution"]
            metadata["program_target"] = target
            return metadata, None
        if "${" in expression:
            metadata["program_resolution"] = "dynamic"
            metadata["dynamic_reason"] = "nix-app-program-interpolation"
            return metadata, None
        metadata["program_resolution"] = "external"
        return metadata, None
    return {}, None


def _extract_path_ref_observations(
    relative_path: str,
    content: str,
    consumed_paths: set[tuple[int, str]],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for match in NIX_PATH_PATTERN.finditer(line):
            path_ref = _clean_path_literal(match.group("path"))
            if (line_number, path_ref) in consumed_paths:
                continue
            target, metadata = _path_target_metadata(
                relative_path,
                path_ref,
                literal_field="path_ref",
                repo_escaping_reason="repo-escaping-nix-path-ref",
            )
            observations.append(
                RawObservation(
                    kind="nix.path_ref",
                    source_id=f"{relative_path}#nix-path:{line_number}:{slug(path_ref)}",
                    path=relative_path,
                    start_line=line_number,
                    end_line=line_number,
                    target=target,
                    confidence="heuristic",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata=metadata,
                )
            )
    return tuple(observations)


def _path_target_metadata(
    relative_path: str,
    literal: str,
    *,
    literal_field: str,
    repo_escaping_reason: str,
) -> tuple[str, dict[str, Any]]:
    metadata = {literal_field: literal}
    resolved_path = resolve_repo_path(relative_path, literal)
    if resolved_path is None:
        metadata["resolution"] = "unknown"
        metadata["dynamic_reason"] = repo_escaping_reason
        return unknown_key("file", repo_escaping_reason), metadata
    metadata["resolved_path"] = resolved_path
    metadata["resolution"] = "local"
    return file_key(resolved_path), metadata


def resolve_repo_path(relative_path: str, literal: str) -> str | None:
    clean_literal = _clean_path_literal(literal)
    if clean_literal.startswith("${self}/"):
        return _normalize_path_components(clean_literal.removeprefix("${self}/"))
    if not (clean_literal.startswith("./") or clean_literal.startswith("../")):
        return None
    base = PurePosixPath(relative_path.replace("\\", "/")).parent
    joined = str(base / clean_literal)
    return _normalize_path_components(joined)


def _normalize_path_components(path: str) -> str | None:
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
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


def _clean_expression(expression: str) -> str:
    return expression.strip().rstrip(";").strip()


def _clean_path_literal(path: str) -> str:
    return path.strip().rstrip(";,)]}").strip()


def slug(value: str) -> str:
    slug_value = SLUG_PATTERN.sub("-", value).strip("-").lower()
    return slug_value or "path"
