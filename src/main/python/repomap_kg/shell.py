"""Conservative shell-family raw observation extraction."""

from __future__ import annotations

import posixpath
import re
import shlex

from repomap_kg import __version__
from repomap_kg.observations import RawObservation


ASSIGNMENT_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
ENV_READ_PATTERN = re.compile(
    r"\$(?:"
    r"{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?:[^}]*)}"
    r"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*)"
    r")"
)
SLUG_PATTERN = re.compile(r"[^0-9A-Za-z]+")
CONTROL_WORDS = frozenset(
    {
        "!",
        "[[",
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "function",
        "if",
        "select",
        "then",
        "until",
        "while",
        "{",
        "}",
    }
)
SOURCE_COMMANDS = frozenset({"source", "."})
DYNAMIC_SOURCE_CHARS = frozenset("$`*?[")


def extract_shell_command_observations(
    path: str, content: str
) -> tuple[RawObservation, ...]:
    return tuple(
        observation
        for observation in extract_shell_observations(path, content)
        if observation.kind == "shell.command"
    )


def extract_shell_observations(path: str, content: str) -> tuple[RawObservation, ...]:
    observations = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = command_line(raw_line)
        if not line:
            continue
        words = command_words(line)
        if not words:
            continue
        observations.extend(
            shell_env_observations(path, line_number, raw_line, line, words)
        )
        argv = command_argv_from_words(words)
        if not argv:
            continue
        if argv[0] in SOURCE_COMMANDS:
            source = shell_source_observation(path, line_number, raw_line, argv)
            if source is not None:
                observations.append(source)
        else:
            observations.append(
                shell_command_observation(path, line_number, raw_line, argv)
            )
    return tuple(observations)


def shell_command_observation(
    path: str, line_number: int, raw_line: str, argv: tuple[str, ...]
) -> RawObservation:
    command = argv[0]
    tool = tool_name(command)
    name = command_display_name(tool, argv)
    return RawObservation(
        kind="shell.command",
        source_id=f"{path}#call:{line_number}:{slug(name)}",
        path=path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        target=f"tool:{tool}",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version=__version__,
        metadata={
            "argv": list(argv),
            "command": command,
            "raw": raw_line.strip(),
        },
    )


def shell_source_observation(
    path: str, line_number: int, raw_line: str, argv: tuple[str, ...]
) -> RawObservation | None:
    if len(argv) < 2:
        return None
    source_path = argv[1]
    resolved_path = resolve_source_path(path, source_path)
    if resolved_path is None:
        return None
    return RawObservation(
        kind="shell.source",
        source_id=f"{path}#source:{line_number}:{slug(resolved_path)}",
        path=path,
        start_line=line_number,
        end_line=line_number,
        name=source_path,
        target=f"file:{resolved_path}",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version=__version__,
        metadata={
            "argv": list(argv),
            "source": source_path,
            "resolved_path": resolved_path,
            "raw": raw_line.strip(),
        },
    )


def shell_env_observations(
    path: str,
    line_number: int,
    raw_line: str,
    line: str,
    words: list[str],
) -> tuple[RawObservation, ...]:
    observations = []
    for variable, value, scope in assignment_writes(words):
        observations.append(
            shell_env_observation(
                path,
                line_number,
                raw_line,
                operation="write",
                variable=variable,
                value=value,
                scope=scope,
            )
        )
    for variable in variable_reads(line):
        observations.append(
            shell_env_observation(
                path,
                line_number,
                raw_line,
                operation="read",
                variable=variable,
            )
        )
    return tuple(observations)


def shell_env_observation(
    path: str,
    line_number: int,
    raw_line: str,
    *,
    operation: str,
    variable: str,
    value: str | None = None,
    scope: str | None = None,
) -> RawObservation:
    metadata = {
        "operation": operation,
        "variable": variable,
        "raw": raw_line.strip(),
    }
    if operation == "write":
        metadata["value"] = value or ""
        metadata["scope"] = scope or "shell"
    return RawObservation(
        kind="shell.env",
        source_id=f"{path}#env-{operation}:{line_number}:{slug(variable)}",
        path=path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        target=f"env:{variable}",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version=__version__,
        metadata=metadata,
    )


def command_argv(raw_line: str) -> tuple[str, ...]:
    line = command_line(raw_line)
    if not line:
        return ()
    words = command_words(line)
    if not words:
        return ()
    return command_argv_from_words(words)


def command_words(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=False, posix=True)
    except ValueError:
        return []


def command_argv_from_words(words: list[str]) -> tuple[str, ...]:
    index = first_command_index(words)
    if index is None:
        return ()
    argv = tuple(words[index:])
    if not argv or argv[0] in CONTROL_WORDS:
        return ()
    return argv


def command_line(raw_line: str) -> str:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return ""
    return re.sub(r"\s+#.*$", "", line).strip()


def first_command_index(words: list[str]) -> int | None:
    for index, word in enumerate(words):
        if ASSIGNMENT_PATTERN.match(word):
            continue
        if word in CONTROL_WORDS:
            return None
        return index
    return None


def assignment_writes(words: list[str]) -> tuple[tuple[str, str, str], ...]:
    writes = []
    for word in words:
        match = ASSIGNMENT_PATTERN.match(word)
        if match is None:
            break
        writes.append((match.group(1), match.group(2)))
    scope = "shell" if len(writes) == len(words) else "command"
    return tuple((variable, value, scope) for variable, value in writes)


def variable_reads(line: str) -> tuple[str, ...]:
    variables = []
    seen = set()
    for match in ENV_READ_PATTERN.finditer(line):
        variable = match.group("braced") or match.group("bare")
        if variable not in seen:
            variables.append(variable)
            seen.add(variable)
    return tuple(variables)


def tool_name(command: str) -> str:
    return command.rsplit("/", maxsplit=1)[-1]


def command_display_name(tool: str, argv: tuple[str, ...]) -> str:
    if len(argv) > 1 and not argv[1].startswith("-"):
        return f"{tool} {argv[1]}"
    return tool


def resolve_source_path(path: str, source_path: str) -> str | None:
    if (
        not source_path
        or source_path.startswith("/")
        or any(character in source_path for character in DYNAMIC_SOURCE_CHARS)
    ):
        return None
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), source_path))
    if resolved == "." or resolved.startswith("../"):
        return None
    return resolved


def slug(value: str) -> str:
    return SLUG_PATTERN.sub("-", value).strip("-").lower() or "command"
