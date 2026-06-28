"""Command-line entry point for RepoMap."""

from __future__ import annotations

import argparse
import json
import sys

from repomap_kg import __version__
from repomap_kg.discovery import discover_observations
from repomap_kg.normalization import normalize_observations
from repomap_kg.observations import ObservationValidationError, read_observations_jsonl
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

    discover = subparsers.add_parser(
        "discover",
        help="discover repository files as raw observations",
    )
    discover.add_argument("root", help="repository root to discover")
    discover.add_argument(
        "--jsonl",
        action="store_true",
        help="emit raw file observations as JSONL",
    )

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
    observations = subparsers.add_parser(
        "observations",
        help="work with raw observation JSONL",
    )
    observation_subcommands = observations.add_subparsers(dest="observation_command")
    normalize = observation_subcommands.add_parser(
        "normalize",
        help="normalize raw observation JSONL",
    )
    normalize.add_argument("jsonl_path", help="path to raw observation JSONL")
    normalize.add_argument(
        "--json",
        action="store_true",
        help="emit normalized records as JSON",
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

    if args.command == "discover":
        observations = discover_observations(args.root)
        if args.jsonl:
            for observation in observations:
                print(observation.to_json_line(), end="")
        else:
            print(f"discovered {len(observations)} files")
        return 0

    if args.command == "observations" and args.observation_command == "normalize":
        try:
            observations = read_observations_jsonl(args.jsonl_path)
        except ObservationValidationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        normalized = normalize_observations(observations)
        payload = normalized.to_dict()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            summary = payload["summary"]
            print(
                "normalized "
                f"{summary['raw_observations']} observations into "
                f"{summary['nodes']} nodes, "
                f"{summary['edges']} edges, and "
                f"{summary['evidence']} evidence records"
            )
        return 0

    parser.print_help()
    return 0
