"""Command-line entry point for RepoMap."""

from __future__ import annotations

import argparse
import json

from repomap_kg import __version__
from repomap_kg.project_identity import PROJECT_IDENTITY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repomap-kg",
        description="RepoMap deterministic knowledge graph CLI.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the repomap-kg version and exit",
    )
    subparsers = parser.add_subparsers(dest="command")

    identity = subparsers.add_parser(
        "identity",
        help="print stable project identity metadata",
        description="Print stable RepoMap project identity metadata.",
    )
    identity.add_argument(
        "--json",
        action="store_true",
        help="emit identity metadata as JSON",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"repomap-kg {__version__}")
        return 0

    if args.command == "identity":
        identity = PROJECT_IDENTITY.as_dict()
        if args.json:
            print(json.dumps(identity, sort_keys=True))
        else:
            for key, value in identity.items():
                print(f"{key}: {value}")
        return 0

    parser.print_help()
    return 0
