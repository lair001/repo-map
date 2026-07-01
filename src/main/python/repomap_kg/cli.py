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
from repomap_kg.graph_keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    file_key,
    host_category_key,
    validate_key,
)
from repomap_kg.host_mutators import (
    filter_host_mutator_records,
    format_host_mutator_summary_table,
    format_host_mutator_table,
    host_mutator_records_from_observations,
    host_mutator_summaries_to_jsonable,
    host_mutators_to_jsonable,
    summarize_host_mutator_records,
)
from repomap_kg.normalization import normalize_observations
from repomap_kg.observations import ObservationValidationError, read_observations_jsonl
from repomap_kg.profiles import ProfileValidationError, load_profile
from repomap_kg.project_identity import PROJECT_IDENTITY
from repomap_kg.source_ingestion import (
    SourceAcquisitionError,
    SourcePolicyError,
    import_archive_source,
    import_warc_source,
    ingest_feed_source,
)
from repomap_kg.storage import (
    StorageSchemaError,
    canonical_edge_explanation_to_jsonable,
    canonical_edge_records_to_jsonable,
    canonical_neighborhood_to_jsonable,
    canonical_node_records_to_jsonable,
    canonical_storage_summary_to_jsonable,
    edge_records_to_jsonable,
    file_neighborhood_to_jsonable,
    file_node_records_to_jsonable,
    format_canonical_edge_explanation_table,
    format_canonical_edge_table,
    format_canonical_neighborhood_table,
    format_canonical_node_table,
    format_canonical_storage_summary_table,
    format_edge_table,
    format_file_neighborhood_table,
    format_file_node_table,
    format_neighborhood_table,
    format_node_table,
    format_storage_summary_table,
    identity_metadata_hash,
    load_canonical_observations,
    load_file_observations,
    neighborhood_to_jsonable,
    node_records_to_jsonable,
    query_canonical_edge_explanation,
    query_canonical_neighborhood,
    query_canonical_node_records,
    query_canonical_edge_records,
    query_canonical_storage_summary,
    query_edge_records,
    query_file_neighborhood,
    query_file_node_records,
    query_file_records,
    query_host_mutator_records,
    query_neighborhood,
    query_node_records,
    query_storage_summary,
    storage_summary_to_jsonable,
)

CANONICAL_EDGE_KINDS = frozenset(
    (
        "defines",
        "executes",
        "sources",
        "reads_env",
        "writes_env",
        "mutates_host",
        "imports",
        "exposes_script",
        "links_to",
        "references",
        "styles",
        "depends_on",
        "wraps",
        "tests",
    )
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

    host_mutators = subparsers.add_parser(
        "host-mutators",
        help="list host-mutating commands from raw observation JSONL",
    )
    host_mutators.add_argument(
        "jsonl_path",
        help="raw observation JSONL path, or - for stdin",
    )
    host_mutators.add_argument(
        "--json",
        action="store_true",
        help="emit host-mutator records as JSON",
    )
    host_mutators.add_argument("--category", help="include only this category")
    host_mutators.add_argument("--tool", help="include only this tool")

    host_mutators_summary = subparsers.add_parser(
        "host-mutators-summary",
        help="summarize host-mutating commands from raw observation JSONL",
    )
    host_mutators_summary.add_argument(
        "jsonl_path",
        help="raw observation JSONL path, or - for stdin",
    )
    host_mutators_summary.add_argument(
        "--json",
        action="store_true",
        help="emit host-mutator summary records as JSON",
    )
    host_mutators_summary.add_argument(
        "--category",
        help="include only this category",
    )
    host_mutators_summary.add_argument("--tool", help="include only this tool")

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

    sources = subparsers.add_parser(
        "sources",
        help="work with explicitly configured source ingestion",
    )
    source_subcommands = sources.add_subparsers(dest="source_command")
    ingest_feed = source_subcommands.add_parser(
        "ingest-feed",
        help="fetch one configured policy-approved feed source",
    )
    ingest_feed.add_argument(
        "--config",
        required=True,
        help="path to a configured feed source TOML file",
    )
    ingest_feed.add_argument("--repository-name", required=True)
    add_storage_root_argument(ingest_feed)
    ingest_feed.add_argument("--git-commit")
    ingest_feed.add_argument(
        "--artifact-dir",
        help="artifact retention directory inside --root-path",
    )
    add_storage_connection_arguments(ingest_feed)
    ingest_feed.add_argument(
        "--json",
        action="store_true",
        help="emit feed ingestion summary as JSON",
    )
    import_archive = source_subcommands.add_parser(
        "import-archive",
        help="import one configured local saved-page/static artifact source",
    )
    import_archive.add_argument(
        "--config",
        required=True,
        help="path to a configured local artifact source TOML file",
    )
    import_archive.add_argument("--repository-name", required=True)
    add_storage_root_argument(import_archive)
    import_archive.add_argument("--git-commit")
    add_storage_connection_arguments(import_archive)
    import_archive.add_argument(
        "--json",
        action="store_true",
        help="emit local artifact import summary as JSON",
    )
    import_warc = source_subcommands.add_parser(
        "import-warc",
        help="import one configured local WARC artifact source",
    )
    import_warc.add_argument(
        "--config",
        required=True,
        help="path to a configured local WARC source TOML file",
    )
    import_warc.add_argument("--repository-name", required=True)
    add_storage_root_argument(import_warc)
    import_warc.add_argument("--git-commit")
    add_storage_connection_arguments(import_warc)
    import_warc.add_argument(
        "--json",
        action="store_true",
        help="emit local WARC import summary as JSON",
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
    load_canonical = storage_subcommands.add_parser(
        "load-canonical",
        help="load raw observations into canonical Postgres storage",
    )
    load_canonical.add_argument("jsonl_path", help="raw observation JSONL path")
    load_canonical.add_argument("--repository-name", required=True)
    add_storage_root_argument(load_canonical)
    load_canonical.add_argument("--git-commit")
    add_storage_connection_arguments(load_canonical)
    load_canonical.add_argument(
        "--json",
        action="store_true",
        help="emit canonical load summary as JSON",
    )
    storage_canonical_nodes = storage_subcommands.add_parser(
        "canonical-nodes",
        help="list stored canonical graph nodes from Postgres storage",
    )
    add_storage_root_argument(storage_canonical_nodes)
    storage_canonical_nodes.add_argument(
        "--kind",
        help="include only canonical nodes with this kind",
    )
    storage_canonical_nodes.add_argument(
        "--canonical-key",
        help="include only the canonical node with this key",
    )
    storage_canonical_nodes.add_argument(
        "--path-prefix",
        help="include only file canonical nodes under this path prefix",
    )
    storage_canonical_nodes.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_canonical_nodes)
    storage_canonical_nodes.add_argument(
        "--json",
        action="store_true",
        help="emit stored canonical node records as JSON",
    )
    storage_canonical_edges = storage_subcommands.add_parser(
        "canonical-edges",
        help="list stored canonical graph edges from Postgres storage",
    )
    add_storage_root_argument(storage_canonical_edges)
    storage_canonical_edges.add_argument(
        "--kind",
        help="include only canonical edges with this ADR 0002 edge kind",
    )
    storage_canonical_edges.add_argument(
        "--source-key",
        help="include only canonical edges from this source key",
    )
    storage_canonical_edges.add_argument(
        "--target-key",
        help="include only canonical edges to this target key",
    )
    storage_canonical_edges.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_canonical_edges)
    storage_canonical_edges.add_argument(
        "--json",
        action="store_true",
        help="emit stored canonical edge records as JSON",
    )
    storage_canonical_neighborhood = storage_subcommands.add_parser(
        "canonical-neighborhood",
        help="show a depth-1 stored canonical graph neighborhood",
    )
    add_storage_root_argument(storage_canonical_neighborhood)
    storage_canonical_neighborhood.add_argument(
        "--node",
        required=True,
        help="center canonical node key",
    )
    storage_canonical_neighborhood.add_argument(
        "--direction",
        choices=("both", "in", "out"),
        default="both",
        help="edge direction to traverse; default both",
    )
    storage_canonical_neighborhood.add_argument(
        "--depth",
        type=int,
        default=1,
        help="neighborhood depth; only 1 is currently supported",
    )
    storage_canonical_neighborhood.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_canonical_neighborhood)
    storage_canonical_neighborhood.add_argument(
        "--json",
        action="store_true",
        help="emit stored canonical neighborhood as JSON",
    )
    storage_explain_canonical_edge = storage_subcommands.add_parser(
        "explain-canonical-edge",
        help="explain one stored canonical graph edge from Postgres storage",
    )
    add_storage_root_argument(storage_explain_canonical_edge)
    storage_explain_canonical_edge.add_argument("--source-key", required=True)
    storage_explain_canonical_edge.add_argument("--kind", required=True)
    storage_explain_canonical_edge.add_argument("--target-key", required=True)
    storage_explain_canonical_edge.add_argument(
        "--identity-metadata-json",
        default="{}",
        help="canonical edge identity metadata JSON object; default {}",
    )
    storage_explain_canonical_edge.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_explain_canonical_edge)
    storage_explain_canonical_edge.add_argument(
        "--json",
        action="store_true",
        help="emit canonical edge explanation as JSON",
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
    storage_nodes.add_argument(
        "--canonical",
        action="store_true",
        help="read canonical graph nodes; this is the default",
    )
    storage_nodes.add_argument(
        "--legacy",
        action="store_true",
        help="read legacy observation-derived nodes",
    )
    storage_nodes.add_argument("--kind", help="include only nodes with this kind")
    storage_nodes.add_argument("--path", help="include only nodes from this file path")
    storage_nodes.add_argument(
        "--stable-key",
        help="include only the node with this stable key",
    )
    storage_nodes.add_argument(
        "--canonical-key",
        help="include only the canonical node with this key in canonical mode",
    )
    storage_nodes.add_argument(
        "--path-prefix",
        help="include only file canonical nodes under this path prefix",
    )
    storage_nodes.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
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
        "--canonical",
        action="store_true",
        help="read a canonical graph neighborhood instead of a legacy neighborhood",
    )
    storage_neighborhood.add_argument(
        "--node",
        required=True,
        help="center node stable key, or canonical key with --canonical",
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
    storage_neighborhood.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_neighborhood)
    storage_neighborhood.add_argument(
        "--json",
        action="store_true",
        help="emit stored graph neighborhood as JSON",
    )
    storage_file_neighborhood = storage_subcommands.add_parser(
        "file-neighborhood",
        help="list a depth-1 graph neighborhood for a stored file path",
    )
    add_storage_root_argument(storage_file_neighborhood)
    storage_file_neighborhood.add_argument(
        "--canonical",
        action="store_true",
        help="read a canonical file neighborhood instead of a legacy neighborhood",
    )
    storage_file_neighborhood.add_argument(
        "--path",
        required=True,
        help="center file path",
    )
    storage_file_neighborhood.add_argument(
        "--direction",
        choices=("both", "in", "out"),
        default="both",
        help="edge direction relative to nodes in the file",
    )
    storage_file_neighborhood.add_argument(
        "--depth",
        type=int,
        default=1,
        help="graph traversal depth; only 1 is currently supported",
    )
    storage_file_neighborhood.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_file_neighborhood)
    storage_file_neighborhood.add_argument(
        "--json",
        action="store_true",
        help="emit stored file graph neighborhood as JSON",
    )
    storage_edges = storage_subcommands.add_parser(
        "edges",
        help="list stored relationship edges from Postgres storage",
    )
    add_storage_root_argument(storage_edges)
    storage_edges.add_argument(
        "--canonical",
        action="store_true",
        help="read canonical graph edges; this is the default",
    )
    storage_edges.add_argument(
        "--legacy",
        action="store_true",
        help="read legacy observation-derived edges",
    )
    storage_edges.add_argument("--kind", help="include only edges with this kind")
    storage_edges.add_argument(
        "--source-node",
        help="include only edges with this source node stable key",
    )
    storage_edges.add_argument(
        "--target-node",
        help="include only edges with this target node stable key",
    )
    storage_edges.add_argument(
        "--source-key",
        help="include only canonical edges from this source key in canonical mode",
    )
    storage_edges.add_argument(
        "--target-key",
        help="include only canonical edges to this target key in canonical mode",
    )
    storage_edges.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_edges)
    storage_edges.add_argument(
        "--json",
        action="store_true",
        help="emit stored edge records as JSON",
    )
    storage_host_mutators = storage_subcommands.add_parser(
        "host-mutators",
        help="list stored host-mutating commands from Postgres storage",
    )
    add_storage_root_argument(storage_host_mutators)
    storage_host_mutators.add_argument(
        "--canonical",
        action="store_true",
        help=(
            "read canonical mutates_host edges instead of legacy "
            "observation-derived host mutation rows"
        ),
    )
    storage_host_mutators.add_argument(
        "--category",
        help="include only this host mutation category",
    )
    storage_host_mutators.add_argument(
        "--tool",
        help="include only this host mutation tool",
    )
    storage_host_mutators.add_argument(
        "--source-key",
        help="include only canonical host mutation edges from this source key",
    )
    storage_host_mutators.add_argument(
        "--target-key",
        help="include only canonical host mutation edges to this target key",
    )
    storage_host_mutators.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_host_mutators)
    storage_host_mutators.add_argument(
        "--json",
        action="store_true",
        help="emit stored host-mutator records as JSON",
    )
    storage_host_mutators_summary = storage_subcommands.add_parser(
        "host-mutators-summary",
        help="summarize stored host-mutating commands from Postgres storage",
    )
    add_storage_root_argument(storage_host_mutators_summary)
    storage_host_mutators_summary.add_argument(
        "--category",
        help="include only this host mutation category",
    )
    storage_host_mutators_summary.add_argument(
        "--tool",
        help="include only this host mutation tool",
    )
    add_storage_connection_arguments(storage_host_mutators_summary)
    storage_host_mutators_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored host-mutator summary records as JSON",
    )
    storage_summary = storage_subcommands.add_parser(
        "summary",
        help="summarize stored repository graph counts from Postgres storage",
    )
    add_storage_root_argument(storage_summary)
    add_storage_connection_arguments(storage_summary)
    storage_summary.add_argument(
        "--canonical",
        action="store_true",
        help="emit canonical graph storage counts; this is the default",
    )
    storage_summary.add_argument(
        "--legacy",
        action="store_true",
        help="emit the legacy observation-derived summary fields",
    )
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
            print(f"discovered {len(observations)} observations")
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

    if args.command == "host-mutators":
        try:
            observations = read_observations_argument(args.jsonl_path)
        except ObservationValidationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        records = host_mutator_records_from_observations(observations)
        records = filter_host_mutator_records(
            records,
            category=args.category,
            tool=args.tool,
        )
        if args.json:
            print(json.dumps(host_mutators_to_jsonable(records), sort_keys=True))
        else:
            print(format_host_mutator_table(records))
        return 0

    if args.command == "host-mutators-summary":
        try:
            observations = read_observations_argument(args.jsonl_path)
        except ObservationValidationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        records = host_mutator_records_from_observations(observations)
        records = filter_host_mutator_records(
            records,
            category=args.category,
            tool=args.tool,
        )
        summaries = summarize_host_mutator_records(records)
        if args.json:
            print(
                json.dumps(
                    host_mutator_summaries_to_jsonable(summaries),
                    sort_keys=True,
                )
            )
        else:
            print(format_host_mutator_summary_table(summaries))
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

    if args.command == "sources" and args.source_command == "ingest-feed":
        try:
            summary = ingest_feed_source(
                config_path=args.config,
                repository_name=args.repository_name,
                root_path=args.root_path,
                psql_args=psql_args_from_args(args),
                git_commit=args.git_commit,
                psql_command=args.psql_command,
                artifact_dir=args.artifact_dir,
            )
        except (SourcePolicyError, SourceAcquisitionError, StorageSchemaError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "ingested feed source "
                f"{summary.source_id} into repository "
                f"{summary.load_summary.repository_id} run "
                f"{summary.load_summary.run_id} "
                f"({summary.feed_observations} feed observations)"
            )
        return 0

    if args.command == "sources" and args.source_command == "import-archive":
        try:
            summary = import_archive_source(
                config_path=args.config,
                repository_name=args.repository_name,
                root_path=args.root_path,
                psql_args=psql_args_from_args(args),
                git_commit=args.git_commit,
                psql_command=args.psql_command,
            )
        except (SourcePolicyError, SourceAcquisitionError, StorageSchemaError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "imported local artifact source "
                f"{summary.source_id} into repository "
                f"{summary.load_summary.repository_id} run "
                f"{summary.load_summary.run_id} "
                f"({summary.observations} observations)"
            )
        return 0

    if args.command == "sources" and args.source_command == "import-warc":
        try:
            summary = import_warc_source(
                config_path=args.config,
                repository_name=args.repository_name,
                root_path=args.root_path,
                psql_args=psql_args_from_args(args),
                git_commit=args.git_commit,
                psql_command=args.psql_command,
            )
        except (SourcePolicyError, SourceAcquisitionError, StorageSchemaError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "imported local WARC source "
                f"{summary.source_id} into repository "
                f"{summary.load_summary.repository_id} run "
                f"{summary.load_summary.run_id} "
                f"({summary.observations} observations, "
                f"{summary.routed_payloads} routed payloads)"
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

    if args.command == "storage" and args.storage_command == "load-canonical":
        try:
            observations = read_observations_jsonl(args.jsonl_path)
            summary = load_canonical_observations(
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
            "raw_observations": summary.raw_observations,
            "canonical_nodes": summary.canonical_nodes,
            "canonical_edges": summary.canonical_edges,
            "canonical_evidence": summary.canonical_evidence,
            "canonical_node_evidence_links": (
                summary.canonical_node_evidence_links
            ),
            "canonical_edge_evidence_links": (
                summary.canonical_edge_evidence_links
            ),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                "loaded "
                f"{summary.raw_observations} raw observations into "
                f"{summary.canonical_nodes} canonical nodes, "
                f"{summary.canonical_edges} canonical edges, and "
                f"{summary.canonical_evidence} canonical evidence records "
                f"for repository {summary.repository_id} run {summary.run_id}"
            )
        return 0

    if args.command == "storage" and args.storage_command == "canonical-nodes":
        try:
            kind = canonical_node_kind_from_args(args)
            records = query_canonical_node_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                kind=kind,
                canonical_key=args.canonical_key,
                path_prefix=args.path_prefix,
                graph_key_version=args.graph_key_version,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    canonical_node_records_to_jsonable(records),
                    sort_keys=True,
                )
            )
        else:
            print(format_canonical_node_table(records))
        return 0

    if args.command == "storage" and args.storage_command == "canonical-edges":
        try:
            canonical_edge_filters_from_args(args)
            records = query_canonical_edge_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                kind=args.kind,
                source_key=args.source_key,
                target_key=args.target_key,
                graph_key_version=args.graph_key_version,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    canonical_edge_records_to_jsonable(records),
                    sort_keys=True,
                )
            )
        else:
            print(format_canonical_edge_table(records))
        return 0

    if (
        args.command == "storage"
        and args.storage_command == "canonical-neighborhood"
    ):
        try:
            canonical_neighborhood_filters_from_args(args)
            record = query_canonical_neighborhood(
                psql_args_from_args(args),
                root_path=args.root_path,
                node=args.node,
                direction=args.direction,
                depth=args.depth,
                graph_key_version=args.graph_key_version,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    canonical_neighborhood_to_jsonable(record),
                    sort_keys=True,
                )
            )
        else:
            print(format_canonical_neighborhood_table(record))
        return 0

    if (
        args.command == "storage"
        and args.storage_command == "explain-canonical-edge"
    ):
        try:
            canonical_edge_filters_from_args(args)
            identity_metadata = canonical_edge_identity_metadata_from_args(args)
            identity_hash = identity_metadata_hash(identity_metadata)
            record = query_canonical_edge_explanation(
                psql_args_from_args(args),
                root_path=args.root_path,
                source_key=args.source_key,
                kind=args.kind,
                target_key=args.target_key,
                identity_metadata_hash=identity_hash,
                graph_key_version=args.graph_key_version,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    canonical_edge_explanation_to_jsonable(record),
                    sort_keys=True,
                )
            )
        else:
            print(format_canonical_edge_explanation_table(record))
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
        if args.canonical and args.legacy:
            print("ERROR: cannot combine --canonical and --legacy", file=sys.stderr)
            return 1
        if not args.legacy:
            try:
                kind = canonical_node_kind_from_args(args)
                records = query_canonical_node_records(
                    psql_args_from_args(args),
                    root_path=args.root_path,
                    kind=kind,
                    canonical_key=args.canonical_key,
                    path_prefix=args.path_prefix,
                    graph_key_version=args.graph_key_version,
                    psql_command=args.psql_command,
                )
            except StorageSchemaError as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return 1
            if args.json:
                print(
                    json.dumps(
                        canonical_node_records_to_jsonable(records),
                        sort_keys=True,
                    )
                )
            else:
                print(format_canonical_node_table(records))
            return 0
        try:
            legacy_node_filters_from_args(args)
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
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
        if args.canonical:
            try:
                canonical_neighborhood_filters_from_args(args)
                record = query_canonical_neighborhood(
                    psql_args_from_args(args),
                    root_path=args.root_path,
                    node=args.node,
                    direction=args.direction,
                    depth=args.depth,
                    graph_key_version=args.graph_key_version,
                    psql_command=args.psql_command,
                )
            except StorageSchemaError as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return 1
            if args.json:
                print(
                    json.dumps(
                        canonical_neighborhood_to_jsonable(record),
                        sort_keys=True,
                    )
                )
            else:
                print(format_canonical_neighborhood_table(record))
            return 0
        try:
            legacy_neighborhood_filters_from_args(args)
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
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

    if args.command == "storage" and args.storage_command == "file-neighborhood":
        if args.canonical:
            try:
                node = canonical_file_neighborhood_node_from_args(args)
                record = query_canonical_neighborhood(
                    psql_args_from_args(args),
                    root_path=args.root_path,
                    node=node,
                    direction=args.direction,
                    depth=args.depth,
                    graph_key_version=args.graph_key_version,
                    psql_command=args.psql_command,
                )
            except StorageSchemaError as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return 1
            if args.json:
                print(
                    json.dumps(
                        canonical_neighborhood_to_jsonable(record),
                        sort_keys=True,
                    )
                )
            else:
                print(format_canonical_neighborhood_table(record))
            return 0
        try:
            legacy_file_neighborhood_filters_from_args(args)
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        try:
            record = query_file_neighborhood(
                psql_args_from_args(args),
                root_path=args.root_path,
                path=args.path,
                direction=args.direction,
                depth=args.depth,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(file_neighborhood_to_jsonable(record), sort_keys=True))
        else:
            print(format_file_neighborhood_table(record))
        return 0

    if args.command == "storage" and args.storage_command == "edges":
        if args.canonical and args.legacy:
            print("ERROR: cannot combine --canonical and --legacy", file=sys.stderr)
            return 1
        if not args.legacy:
            try:
                canonical_edge_filters_from_args(args)
                records = query_canonical_edge_records(
                    psql_args_from_args(args),
                    root_path=args.root_path,
                    kind=args.kind,
                    source_key=args.source_key,
                    target_key=args.target_key,
                    graph_key_version=args.graph_key_version,
                    psql_command=args.psql_command,
                )
            except StorageSchemaError as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return 1
            if args.json:
                print(
                    json.dumps(
                        canonical_edge_records_to_jsonable(records),
                        sort_keys=True,
                    )
                )
            else:
                print(format_canonical_edge_table(records))
            return 0
        try:
            legacy_edge_filters_from_args(args)
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
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

    if args.command == "storage" and args.storage_command == "host-mutators":
        if args.canonical:
            try:
                target_key = canonical_host_mutator_filters_from_args(args)
                records = query_canonical_edge_records(
                    psql_args_from_args(args),
                    root_path=args.root_path,
                    kind="mutates_host",
                    source_key=args.source_key,
                    target_key=target_key,
                    graph_key_version=args.graph_key_version,
                    psql_command=args.psql_command,
                )
            except StorageSchemaError as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return 1
            records = filter_canonical_host_mutator_records(
                records,
                tool=args.tool,
            )
            if args.json:
                print(
                    json.dumps(
                        canonical_edge_records_to_jsonable(records),
                        sort_keys=True,
                    )
                )
            else:
                print(format_canonical_edge_table(records))
            return 0
        try:
            legacy_host_mutator_filters_from_args(args)
            records = query_host_mutator_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                category=args.category,
                tool=args.tool,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(host_mutators_to_jsonable(records), sort_keys=True))
        else:
            print(format_host_mutator_table(records))
        return 0

    if args.command == "storage" and args.storage_command == "host-mutators-summary":
        try:
            records = query_host_mutator_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                category=args.category,
                tool=args.tool,
                psql_command=args.psql_command,
            )
        except StorageSchemaError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        summaries = summarize_host_mutator_records(records)
        if args.json:
            print(
                json.dumps(
                    host_mutator_summaries_to_jsonable(summaries),
                    sort_keys=True,
                )
            )
        else:
            print(format_host_mutator_summary_table(summaries))
        return 0

    if args.command == "storage" and args.storage_command == "summary":
        if args.canonical and args.legacy:
            print("ERROR: cannot combine --canonical and --legacy", file=sys.stderr)
            return 1
        if not args.legacy:
            try:
                summary = query_canonical_storage_summary(
                    psql_args_from_args(args),
                    root_path=args.root_path,
                    psql_command=args.psql_command,
                )
            except StorageSchemaError as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return 1
            if args.json:
                print(
                    json.dumps(
                        canonical_storage_summary_to_jsonable(summary),
                        sort_keys=True,
                    )
                )
            else:
                print(format_canonical_storage_summary_table(summary))
            return 0
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


def canonical_node_kind_from_args(args) -> str | None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if getattr(args, "stable_key", None) is not None:
        raise StorageSchemaError(
            "stable-key is a legacy node filter; use --canonical-key in canonical mode"
        )
    if getattr(args, "path", None) is not None:
        raise StorageSchemaError(
            "path is a legacy node filter; use --canonical-key or --path-prefix "
            "in canonical mode"
        )
    if args.canonical_key is not None:
        validation = validate_key(args.canonical_key)
        if not validation.valid:
            detail = f": {validation.error}" if validation.error else ""
            raise StorageSchemaError(f"invalid canonical key{detail}")
    kind = args.kind
    if args.path_prefix is not None:
        if kind is not None and kind != "file":
            raise StorageSchemaError("path-prefix only applies to file canonical nodes")
        kind = "file"
    return kind


def canonical_edge_filters_from_args(args) -> None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if getattr(args, "source_node", None) is not None:
        raise StorageSchemaError(
            "source-node is a legacy edge filter; use --source-key in canonical mode"
        )
    if getattr(args, "target_node", None) is not None:
        raise StorageSchemaError(
            "target-node is a legacy edge filter; use --target-key in canonical mode"
        )
    if args.kind is not None and args.kind not in CANONICAL_EDGE_KINDS:
        values = ", ".join(sorted(CANONICAL_EDGE_KINDS))
        raise StorageSchemaError(
            f"unsupported canonical edge kind: {args.kind}; expected one of {values}"
        )
    for option, value in (
        ("source", args.source_key),
        ("target", args.target_key),
    ):
        if value is None:
            continue
        validation = validate_key(value)
        if not validation.valid:
            detail = f": {validation.error}" if validation.error else ""
            raise StorageSchemaError(f"invalid {option} canonical key{detail}")


def canonical_neighborhood_filters_from_args(args) -> None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if args.depth != 1:
        raise StorageSchemaError("storage canonical-neighborhood only supports depth 1")
    validation = validate_key(args.node)
    if not validation.valid:
        detail = f": {validation.error}" if validation.error else ""
        raise StorageSchemaError(f"invalid node canonical key{detail}")


def canonical_file_neighborhood_node_from_args(args) -> str:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if args.depth != 1:
        raise StorageSchemaError(
            "storage file-neighborhood --canonical only supports depth 1"
        )
    try:
        return file_key(args.path)
    except GraphKeyError as error:
        raise StorageSchemaError(f"invalid file path: {error}") from error


def legacy_node_filters_from_args(args) -> None:
    if args.canonical_key is not None:
        raise StorageSchemaError(
            "canonical-key is a canonical node filter; omit --legacy"
        )
    if args.path_prefix is not None:
        raise StorageSchemaError(
            "path-prefix is a canonical node filter; omit --legacy"
        )
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError(
            "graph-key-version is a canonical node filter; omit --legacy"
        )


def legacy_edge_filters_from_args(args) -> None:
    if args.source_key is not None:
        raise StorageSchemaError(
            "source-key is a canonical edge filter; omit --legacy"
        )
    if args.target_key is not None:
        raise StorageSchemaError(
            "target-key is a canonical edge filter; omit --legacy"
        )
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError(
            "graph-key-version is a canonical edge filter; omit --legacy"
        )


def canonical_host_mutator_filters_from_args(args) -> str | None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    for option, value in (
        ("--source-key", args.source_key),
        ("--target-key", args.target_key),
    ):
        if value is None:
            continue
        validation = validate_key(value)
        if not validation.valid:
            detail = f": {validation.error}" if validation.error else ""
            raise StorageSchemaError(f"invalid {option} canonical key{detail}")
    target_key = args.target_key
    if args.category is not None:
        try:
            category_target_key = host_category_key(args.category)
        except GraphKeyError as error:
            raise StorageSchemaError(
                f"invalid host mutation category: {error}"
            ) from error
        if target_key is not None and target_key != category_target_key:
            raise StorageSchemaError(
                "category and target-key refer to different host categories"
            )
        target_key = category_target_key
    return target_key


def legacy_host_mutator_filters_from_args(args) -> None:
    if args.source_key is not None:
        raise StorageSchemaError("--source-key requires --canonical")
    if args.target_key is not None:
        raise StorageSchemaError("--target-key requires --canonical")
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("--graph-key-version requires --canonical")


def filter_canonical_host_mutator_records(records, *, tool: str | None):
    if tool is None:
        return records
    return tuple(
        record
        for record in records
        if canonical_host_mutator_record_has_tool(record, tool)
    )


def canonical_host_mutator_record_has_tool(record, tool: str) -> bool:
    tools = record.metadata.get("tools")
    if isinstance(tools, list) and tool in tools:
        return True
    return record.metadata.get("tool") == tool


def legacy_neighborhood_filters_from_args(args) -> None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("graph-key-version requires --canonical")


def legacy_file_neighborhood_filters_from_args(args) -> None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("graph-key-version requires --canonical")


def canonical_edge_identity_metadata_from_args(args) -> dict[str, object]:
    try:
        payload = json.loads(args.identity_metadata_json)
    except json.JSONDecodeError as error:
        raise StorageSchemaError(
            "identity-metadata-json must be a JSON object"
        ) from error
    if not isinstance(payload, dict):
        raise StorageSchemaError("identity-metadata-json must be a JSON object")
    return payload


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
