import os
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from repomap_kg.cli import main
from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    load_file_observations,
)


class StorageIntegrationTests(unittest.TestCase):
    def test_apply_migrations_creates_core_graph_tables(self):
        require_postgres_binaries()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            tables = postgres.psql_scalar(
                """
SELECT string_agg(table_name, ',' ORDER BY table_name)
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'repositories',
    'runs',
    'files',
    'nodes',
    'edges',
    'evidence'
  );
"""
            )
            inserted_path = postgres.psql_scalar(
                """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', '/tmp/fixture')
RETURNING id
\\gset
INSERT INTO runs(repository_id, status)
VALUES (:id, 'complete')
RETURNING id
\\gset run_
INSERT INTO files(
  repository_id,
  path,
  language,
  role,
  content_hash,
  executable,
  generated
)
VALUES (:id, 'bin/tool', 'shell', 'entrypoint', repeat('0', 64), true, false)
RETURNING id
\\gset file_
INSERT INTO nodes(repository_id, file_id, kind, name, stable_key)
VALUES (:id, :file_id, 'file', 'bin/tool', 'file:bin/tool')
RETURNING id
\\gset node_
INSERT INTO evidence(repository_id, file_id, extractor, metadata_json)
VALUES (:id, :file_id, 'repo-discovery', '{"source":"test"}'::jsonb)
RETURNING id
\\gset evidence_
INSERT INTO edges(
  repository_id,
  src_node_id,
  dst_node_id,
  kind,
  confidence,
  evidence_id
)
VALUES (
  :id,
  :node_id,
  :node_id,
  'self',
  'manual',
  :evidence_id
);
SELECT path FROM files WHERE role = 'entrypoint';
"""
            )

        self.assertEqual(
            tables,
            "edges,evidence,files,nodes,repositories,runs",
        )
        self.assertEqual(inserted_path, "bin/tool")

    def test_load_file_observations_inserts_repository_run_and_files(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "f" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:echo",
                path="bin/tool",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                target="tool:echo",
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            summary = load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                git_commit="abc123",
                psql_command=postgres.psql_command,
            )
            row = postgres.psql_scalar(
                """
SELECT repositories.name
       || '|'
       || runs.git_commit
       || '|'
       || files.path
       || '|'
       || files.role
       || '|'
       || files.executable::text
       || '|'
       || (files.metadata_json->>'confidence')
FROM files
JOIN repositories ON repositories.id = files.repository_id
JOIN runs ON runs.id = files.last_seen_run_id;
"""
            )

        self.assertEqual(summary.files, 1)
        self.assertEqual(row, "fixture|abc123|bin/tool|entrypoint|true|manual")

    def test_storage_load_files_cli_loads_discovery_jsonl(self):
        require_postgres_binaries()
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "e" * 64,
                "generated": False,
                "executable": False,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            raw_jsonl.write_text(observation.to_json_line())
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "storage",
                    "load-files",
                    str(raw_jsonl),
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                text_exit_code, text_stdout, text_stderr = run_repo_map_in_process(
                    "storage",
                    "load-files",
                    str(raw_jsonl),
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    "/tmp/fixture",
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    "postgres",
                    "--psql-command",
                    postgres.psql_command,
                )
                stored_path = postgres.psql_scalar(
                    "SELECT path FROM files WHERE path = 'README.md';"
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["files"], 1)
        self.assertEqual(text_exit_code, 0, text_stderr)
        self.assertRegex(
            text_stdout,
            r"^loaded 1 files into repository [0-9a-f-]+ run [0-9a-f-]+\n$",
        )
        self.assertEqual(stored_path, "README.md")

    def test_storage_files_cli_reads_loaded_file_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="generated/report.json",
                path="generated/report.json",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "json",
                    "role": "generated",
                    "content_hash": "a" * 64,
                    "generated": True,
                    "executable": False,
                },
            ),
            RawObservation(
                kind="file",
                source_id="src/main/python/app.py",
                path="src/main/python/app.py",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "python",
                    "role": "source",
                    "content_hash": "b" * 64,
                    "generated": False,
                    "executable": False,
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "files",
                "--root-path",
                "/tmp/fixture",
                "--role",
                "source",
                "--language",
                "python",
                "--generated",
                "exclude",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            payload,
            [
                {
                    "path": "src/main/python/app.py",
                    "language": "python",
                    "role": "source",
                    "confidence": "manual",
                    "generated": False,
                    "executable": False,
                }
            ],
        )

    def test_storage_entrypoints_cli_reads_loaded_entrypoint_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="file",
                source_id="scripts/helper.sh",
                path="scripts/helper.sh",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "d" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "entrypoints",
                "--root-path",
                "/tmp/fixture",
                "--pg-host",
                str(postgres.socket_dir),
                "--pg-port",
                str(postgres.port),
                "--pg-user",
                postgres.user,
                "--pg-database",
                "postgres",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual([record["path"] for record in payload], ["bin/tool"])
        self.assertTrue(payload[0]["executable"])


class PostgresCluster:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.socket_dir = root / "socket"
        self.log = root / "postgres.log"
        self.port = 5432
        self.user = "repo_map_test"
        self.bin_dir = postgres_bin_dir()
        self.psql_command = str(self.bin_dir / "psql")
        self.socket_dir.mkdir()
        self.psql_args = [
            "-h",
            str(self.socket_dir),
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            "postgres",
        ]

    def start(self):
        run(
            [
                str(self.bin_dir / "initdb"),
                "-D",
                str(self.data),
                "-A",
                "trust",
                "-U",
                self.user,
                "-L",
                str(postgres_share_dir()),
            ]
        )
        run(
            [
                str(self.bin_dir / "pg_ctl"),
                "-D",
                str(self.data),
                "-l",
                str(self.log),
                "-o",
                f"-k {self.socket_dir} -h '' -p {self.port}",
                "-w",
                "start",
            ]
        )
        return self

    def stop(self):
        if self.data.exists():
            run(
                [
                    str(self.bin_dir / "pg_ctl"),
                    "-D",
                    str(self.data),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ]
            )

    def psql_scalar(self, sql: str) -> str:
        command = [self.psql_command, *self.psql_args, "-At", "-v", "ON_ERROR_STOP=1"]
        result = run(command, sql)
        lines = [line for line in result.stdout.splitlines() if line]
        return lines[-1] if lines else ""


class temporary_postgres:
    def __enter__(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cluster = PostgresCluster(Path(self.tmpdir.name)).start()
        return self.cluster

    def __exit__(self, exc_type, exc, tb):
        try:
            self.cluster.stop()
        finally:
            self.tmpdir.cleanup()


def require_postgres_binaries():
    bin_dir = postgres_bin_dir()
    missing = [
        command
        for command in ("initdb", "pg_ctl", "psql")
        if not (bin_dir / command).exists()
    ]
    if missing:
        raise unittest.SkipTest(
            f"missing Postgres binaries in {bin_dir}: {', '.join(missing)}"
        )
    postgres_share_dir()


def postgres_share_dir() -> Path:
    share = postgres_config_path("--sharedir")
    if share is None:
        share = postgres_bin_dir().parent / "share" / "postgresql"
    if not (share / "postgres.bki").exists():
        raise unittest.SkipTest(f"missing Postgres share directory: {share}")
    return share


def postgres_bin_dir() -> Path:
    bindir = postgres_config_path("--bindir")
    if bindir is not None:
        return bindir
    initdb = Path(shutil.which("initdb") or "initdb").resolve()
    return initdb.parent


def postgres_config_path(option: str) -> Path | None:
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    result = subprocess.run(
        [pg_config, option],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value:
        return None
    return Path(value).resolve()


def run(command, input_text=None):
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    try:
        return subprocess.run(
            command,
            check=True,
            env=env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as error:
        raise AssertionError(
            f"command failed: {command}\n"
            f"stdout:\n{error.stdout}\n"
            f"stderr:\n{error.stderr}"
        ) from error


def run_repo_map_in_process(*args):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(list(args))
    return exit_code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
