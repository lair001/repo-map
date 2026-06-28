"""Command-line entry point for RepoMap."""

from __future__ import annotations

import argparse
import json
import sys

from repomap_kg import __version__
from repomap_kg.discovery import discover_observations
from repomap_kg.entrypoints import (
    entrypoint_records_from_file_records,
    entrypoint_records_from_observations,
    entrypoints_to_jsonable,
    format_entrypoint_table,
)
from repomap_kg.files import (
    FileFilters,
    file_records_from_observations,
    filter_file_records,
    format_file_table,
    records_to_jsonable,
)
from repomap_kg.normalization import normalize_observations
from repomap_kg.observations import ObservationValidationError, read_observations_jsonl
from repomap_kg.profiles import ProfileValidationError, load_profile
from repomap_kg.project_identity import PROJECT_IDENTITY
from repomap_kg.storage import (
    StorageSchemaError,
    edge_records_to_jsonable,
    file_node_records_to_jsonable,
    format_edge_table,
    format_file_node_table,
    format_neighborhood_table,
    format_node_table,
    format_storage_summary_table,
    load_file_observations,
    neighborhood_to_jsonable,
    node_records_to_jsonable,
    query_edge_records,
    query_file_node_records,
    query_file_records,
    query_neighborhood,
    query_node_records,
    query_storage_summary,
    storage_summary_to_jsonable,
)


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
        "--profile",
        help="path to an optional RepoMap project profile",
    )
    discover.add_argument(
        "--jsonl",
        action="store_true",
        help="emit raw file observations as JSONL",
    )

    entrypoints = subparsers.add_parser(
        "entrypoints",
        help="list entrypoint files from raw observation JSONL",
    )
    entrypoints.add_argument(
        "jsonl_path",
        help="raw observation JSONL path, or - for stdin",
    )
    entrypoints.add_argument(
        "--json",
        action="store_true",
        help="emit entrypoint records as JSON",
    )

    files = subparsers.add_parser(
        "files",
        help="list discovered files from raw observation JSONL",
    )
    files.add_argument("jsonl_path", help="raw observation JSONL path, or - for stdin")
    files.add_argument("--role", help="include only files with this role")
    files.add_argument("--language", help="include only files with this language")
    files.add_argument(
        "--generated",
        choices=("include", "exclude", "only"),
        default="include",
        help="control generated-file rows",
    )
    files.add_argument(
        "--json",
        action="store_true",
        help="emit file records as JSON",
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

    storage = subparsers.add_parser(
        "storage",
        help="work with RepoMap storage backends",
    )
    storage_subcommands = storage.add_subparsers(dest="storage_command")
    load_files = storage_subcommands.add_parser(
        "load-files",
        help="load raw file observations into Postgres storage",
    )
    load_files.add_argument("jsonl_path", help="raw observation JSONL path")
    load_files.add_argument("--repository-name", required=True)
    add_storage_root_argument(load_files)
    load_files.add_argument("--git-commit")
    add_storage_connection_arguments(load_files)
    load_files.add_argument(
        "--json",
        action="store_true",
        help="emit load summary as JSON",
    )
    storage_files = storage_subcommands.add_parser(
        "files",
        help="list stored files from Postgres storage",
    )
    add_storage_root_argument(storage_files)
    storage_files.add_argument("--role", help="include only files with this role")
    storage_files.add_argument(
        "--language",
        help="include only files with this language",
    )
    storage_files.add_argument(
        "--generated",
        choices=("include", "exclude", "only"),
        default="include",
        help="control generated-file rows",
    )
    add_storage_connection_arguments(storage_files)
    storage_files.add_argument(
        "--json",
        action="store_true",
        help="emit stored file records as JSON",
    )
    storage_entrypoints = storage_subcommands.add_parser(
        "entrypoints",
        help="list stored entrypoint files from Postgres storage",
    )
    add_storage_root_argument(storage_entrypoints)
    add_storage_connection_arguments(storage_entrypoints)
    storage_entrypoints.add_argument(
        "--json",
        action="store_true",
        help="emit stored entrypoint records as JSON",
    )
    storage_file_nodes = storage_subcommands.add_parser(
        "file-nodes",
        help="list stored file nodes and evidence from Postgres storage",
    )
    add_storage_root_argument(storage_file_nodes)
    storage_file_nodes.add_argument("--path", help="include only this file path")
    add_storage_connection_arguments(storage_file_nodes)
    storage_file_nodes.add_argument(
        "--json",
        action="store_true",
        help="emit stored file node records as JSON",
    )
    storage_nodes = storage_subcommands.add_parser(
        "nodes",
        help="list stored graph nodes from Postgres storage",
    )
    add_storage_root_argument(storage_nodes)
    storage_nodes.add_argument("--kind", help="include only nodes with this kind")
    storage_nodes.add_argument("--path", help="include only nodes from this file path")
    storage_nodes.add_argument(
        "--stable-key",
        help="include only the node with this stable key",
    )
    add_storage_connection_arguments(storage_nodes)
    storage_nodes.add_argument(
        "--json",
        action="store_true",
        help="emit stored graph node records as JSON",
    )
    storage_neighborhood = storage_subcommands.add_parser(
        "neighborhood",
        help="list a depth-1 graph neighborhood from Postgres storage",
    )
    add_storage_root_argument(storage_neighborhood)
    storage_neighborhood.add_argument(
        "--node",
        required=True,
        help="center node stable key",
    )
    storage_neighborhood.add_argument(
        "--direction",
        choices=("both", "in", "out"),
        default="both",
        help="edge direction relative to the center node",
    )
    storage_neighborhood.add_argument(
        "--depth",
        type=int,
        default=1,
        help="graph traversal depth; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_neighborhood)
    storage_neighborhood.add_argument(
        "--json",
        action="store_true",
        help="emit stored graph neighborhood as JSON",
    )
    storage_edges = storage_subcommands.add_parser(
        "edges",
        help="list stored relationship edges from Postgres storage",
    )
    add_storage_root_argument(storage_edges)
    storage_edges.add_argument("--kind", help="include only edges with this kind")
    storage_edges.add_argument(
        "--source-node",
        help="include only edges with this source node stable key",
    )
    storage_edges.add_argument(
        "--target-node",
        help="include only edges with this target node stable key",
    )
    add_storage_connection_arguments(storage_edges)
    storage_edges.add_argument(
        "--json",
        action="store_true",
        help="emit stored edge records as JSON",
    )
    storage_summary = storage_subcommands.add_parser(
        "summary",
        help="summarize stored repository graph counts from Postgres storage",
    )
    add_storage_root_argument(storage_summary)
    add_storage_connection_arguments(storage_summary)
    storage_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored repository graph summary as JSON",
    )

    return parser


def add_storage_root_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument("--root-path", required=True)


def add_storage_connection_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--pg-host")
    command.add_argument("--pg-port")
    command.add_argument("--pg-user")
    command.add_argument("--pg-database")
    command.add_argument("--psql-command", default="psql")


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
        try:
            profile = load_profile(args.profile) if args.profile else None
        except ProfileValidationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        observations = discover_observations(args.root, profile=profile)
        if args.jsonl:
            for observation in observations:
                print(observation.to_json_line(), end="")
        else:
            print(f"discovered {len(observations)} files")
        return 0

    if args.command == "files":
        try:
            observations = read_observations_argument(args.jsonl_path)
        except ObservationValidationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        filters = FileFilters(
            role=args.role,
            language=args.language,
            generated=args.generated,
        )
        records = filter_file_records(
            file_records_from_observations(observations), filters
        )
        if args.json:
            print(json.dumps(records_to_jsonable(records), sort_keys=True))
        else:
            print(format_file_table(records))
        return 0

    if args.command == "entrypoints":
        try:
            observations = read_observations_argument(args.jsonl_path)
        except ObservationValidationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        records = entrypoint_records_from_observations(observations)
        if args.json:
            print(json.dumps(entrypoints_to_jsonable(records), sort_keys=True))
        else:
            print(format_entrypoint_table(records))
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

    if args.command == "storage" and args.storage_command == "load-files":
        try:
            observations = read_observations_jsonl(args.jsonl_path)
            summary = load_file_observations(
                psql_args_from_args(args),
                observations,
                repository_name=args.repository_name,
                root_path=args.root_path,
                git_commit=args.git_commit,
                psql_command=args.psql_command,
            )
        except (ObservationValidationError, StorageSchemaError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        payload = {
            "repository_id": summary.repository_id,
            "run_id": summary.run_id,
            "files": summary.files,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"loaded {summary.files} files into "
                f"repository {summary.repository_id} run {summary.run_id}"
            )
        return 0

    if args.command == "storage" and args.storage_command == "files":
        try:
            records = query_file_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        filters = FileFilters(
            role=args.role,
            language=args.language,
            generated=args.generated,
        )
        records = filter_file_records(records, filters)
        if args.json:
            print(json.dumps(records_to_jsonable(records), sort_keys=True))
        else:
            print(format_file_table(records))
        return 0

    if args.command == "storage" and args.storage_command == "entrypoints":
        try:
            records = query_file_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        records = entrypoint_records_from_file_records(records)
        if args.json:
            print(json.dumps(entrypoints_to_jsonable(records), sort_keys=True))
        else:
            print(format_entrypoint_table(records))
        return 0

    if args.command == "storage" and args.storage_command == "file-nodes":
        try:
            records = query_file_node_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                path=args.path,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(file_node_records_to_jsonable(records), sort_keys=True))
        else:
            print(format_file_node_table(records))
        return 0

    if args.command == "storage" and args.storage_command == "nodes":
        try:
            records = query_node_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                kind=args.kind,
                path=args.path,
                stable_key=args.stable_key,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(node_records_to_jsonable(records), sort_keys=True))
        else:
            print(format_node_table(records))
        return 0

    if args.command == "storage" and args.storage_command == "neighborhood":
        try:
            record = query_neighborhood(
                psql_args_from_args(args),
                root_path=args.root_path,
                node=args.node,
                direction=args.direction,
                depth=args.depth,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(neighborhood_to_jsonable(record), sort_keys=True))
        else:
            print(format_neighborhood_table(record))
        return 0

    if args.command == "storage" and args.storage_command == "edges":
        try:
            records = query_edge_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                kind=args.kind,
                source_node=args.source_node,
                target_node=args.target_node,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(edge_records_to_jsonable(records), sort_keys=True))
        else:
            print(format_edge_table(records))
        return 0

    if args.command == "storage" and args.storage_command == "summary":
        try:
            summary = query_storage_summary(
                psql_args_from_args(args),
                root_path=args.root_path,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(storage_summary_to_jsonable(summary), sort_keys=True))
        else:
            print(format_storage_summary_table(summary))
        return 0

    parser.print_help()
    return 0


def read_observations_argument(jsonl_path: str):
    if jsonl_path == "-":
        return read_observations_jsonl(sys.stdin)
    return read_observations_jsonl(jsonl_path)


def psql_args_from_args(args) -> list[str]:
    psql_args = []
    options = (
        ("pg_host", "-h"),
        ("pg_port", "-p"),
        ("pg_user", "-U"),
        ("pg_database", "-d"),
    )
    for attribute, flag in options:
        value = getattr(args, attribute)
        if value:
            psql_args.extend([flag, value])
    return psql_args
