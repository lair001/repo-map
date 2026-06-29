"""Conservative shell-family raw observation extraction."""

from __future__ import annotations

import re
import shlex

from repomap_kg import __version__
from repomap_kg.observations import RawObservation


ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
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


def extract_shell_command_observations(
    path: str, content: str
) -> tuple[RawObservation, ...]:
    observations = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        argv = command_argv(raw_line)
        if not argv:
            continue
        command = argv[0]
        tool = tool_name(command)
        name = command_display_name(tool, argv)
        observations.append(
            RawObservation(
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
        )
    return tuple(observations)


def command_argv(raw_line: str) -> tuple[str, ...]:
    line = command_line(raw_line)
    if not line:
        return ()
    try:
        words = shlex.split(line, comments=False, posix=True)
    except ValueError:
        return ()
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


def tool_name(command: str) -> str:
    return command.rsplit("/", maxsplit=1)[-1]


def command_display_name(tool: str, argv: tuple[str, ...]) -> str:
    if len(argv) > 1 and not argv[1].startswith("-"):
        return f"{tool} {argv[1]}"
    return tool


def slug(value: str) -> str:
    return SLUG_PATTERN.sub("-", value).strip("-").lower() or "command"
