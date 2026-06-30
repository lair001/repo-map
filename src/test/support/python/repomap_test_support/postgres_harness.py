from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO


POSTGRES_BOOTSTRAP_SHM_SIZES = frozenset({56})


@dataclass(frozen=True)
class SharedMemorySegment:
    shmid: str
    owner: str
    creator: str | None
    nattch: int | None
    size: int | None


@dataclass(frozen=True)
class IpcCleanupReport:
    removed_shmids: tuple[str, ...]
    skipped_shmids: tuple[str, ...] = ()
    unavailable: bool = False


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


class PostgresIpcGuard:
    def __init__(
        self,
        *,
        current_user: str | None = None,
        runner: SubprocessRunner = subprocess.run,
        stderr: TextIO | None = None,
    ):
        self.current_user = current_user or getpass.getuser()
        self.runner = runner
        self.stderr = stderr if stderr is not None else sys.stderr
        self.baseline: tuple[SharedMemorySegment, ...] | None = None

    def capture_baseline(self) -> bool:
        self.baseline = capture_shared_memory_segments(self.runner)
        if self.baseline is None:
            print(
                "temporary_postgres: ipcs unavailable before initdb; "
                "refusing to start disposable Postgres because safe IPC "
                "cleanup cannot be guaranteed",
                file=self.stderr,
            )
            return False
        return True

    def cleanup(self, *, live_test_processes: bool) -> IpcCleanupReport:
        return cleanup_postgres_shared_memory_leaks(
            baseline=self.baseline,
            current_user=self.current_user,
            live_test_processes=live_test_processes,
            runner=self.runner,
            stderr=self.stderr,
        )


def parse_ipcs_shared_memory(output: str) -> tuple[SharedMemorySegment, ...]:
    header: list[str] | None = None
    segments: list[SharedMemorySegment] = []
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        if "ID" in fields and "NATTCH" in fields:
            header = fields
            continue
        if fields[0] != "m" or header is None:
            continue
        values = dict(zip(header, fields, strict=False))
        shmid = values.get("ID")
        owner = values.get("OWNER")
        if shmid is None or owner is None:
            continue
        segments.append(
            SharedMemorySegment(
                shmid=shmid,
                owner=owner,
                creator=values.get("CREATOR"),
                nattch=parse_optional_int(values.get("NATTCH")),
                size=parse_optional_int(values.get("SEGSZ")),
            )
        )
    return tuple(segments)


def parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def capture_shared_memory_segments(
    runner: SubprocessRunner = subprocess.run,
) -> tuple[SharedMemorySegment, ...] | None:
    try:
        result = runner(
            ["ipcs", "-m", "-a"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_ipcs_shared_memory(result.stdout)


def shared_memory_cleanup_candidates(
    *,
    baseline: tuple[SharedMemorySegment, ...],
    current: tuple[SharedMemorySegment, ...],
    current_user: str,
    live_test_processes: bool = False,
) -> tuple[SharedMemorySegment, ...]:
    if live_test_processes:
        return ()
    baseline_ids = {segment.shmid for segment in baseline}
    return tuple(
        segment
        for segment in current
        if is_cleanup_candidate(segment, baseline_ids, current_user)
    )


def ambiguous_shared_memory_segments(
    *,
    baseline: tuple[SharedMemorySegment, ...],
    current: tuple[SharedMemorySegment, ...],
    current_user: str,
) -> tuple[SharedMemorySegment, ...]:
    baseline_ids = {segment.shmid for segment in baseline}
    return tuple(
        segment
        for segment in current
        if segment.shmid not in baseline_ids
        and (segment.owner == current_user or segment.creator == current_user)
        and not is_cleanup_candidate(segment, baseline_ids, current_user)
    )


def is_cleanup_candidate(
    segment: SharedMemorySegment,
    baseline_ids: set[str],
    current_user: str,
) -> bool:
    if segment.shmid in baseline_ids:
        return False
    if segment.owner != current_user:
        return False
    if segment.creator not in (None, current_user):
        return False
    if segment.nattch != 0:
        return False
    return segment.size in POSTGRES_BOOTSTRAP_SHM_SIZES


def cleanup_postgres_shared_memory_leaks(
    *,
    baseline: tuple[SharedMemorySegment, ...] | None,
    current_user: str,
    live_test_processes: bool = False,
    runner: SubprocessRunner = subprocess.run,
    stderr: TextIO | None = None,
) -> IpcCleanupReport:
    output = stderr if stderr is not None else sys.stderr
    if baseline is None:
        print(
            "temporary_postgres: baseline unavailable; skipped IPC leak cleanup",
            file=output,
        )
        return IpcCleanupReport(removed_shmids=(), unavailable=True)
    current = capture_shared_memory_segments(runner)
    if current is None:
        print(
            "temporary_postgres: ipcs unavailable; skipped IPC leak cleanup",
            file=output,
        )
        return IpcCleanupReport(removed_shmids=(), unavailable=True)
    candidates = shared_memory_cleanup_candidates(
        baseline=baseline,
        current=current,
        current_user=current_user,
    )
    ambiguous = ambiguous_shared_memory_segments(
        baseline=baseline,
        current=current,
        current_user=current_user,
    )
    if live_test_processes and (candidates or ambiguous):
        skipped = tuple(
            segment.shmid for segment in (*candidates, *ambiguous)
        )
        print(
            "temporary_postgres: skipped IPC leak cleanup because test "
            f"cluster still appears live: {', '.join(skipped)}",
            file=output,
        )
        return IpcCleanupReport(
            removed_shmids=(),
            skipped_shmids=skipped,
        )
    if ambiguous:
        skipped = tuple(segment.shmid for segment in ambiguous)
        print(
            "temporary_postgres: skipped ambiguous shared-memory segments: "
            f"{', '.join(skipped)}",
            file=output,
        )
    removed: list[str] = []
    for segment in candidates:
        try:
            result = runner(
                ["ipcrm", "-m", segment.shmid],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            print(
                "temporary_postgres: ipcrm unavailable; skipped IPC leak cleanup",
                file=output,
            )
            return IpcCleanupReport(
                removed_shmids=tuple(removed),
                skipped_shmids=tuple(
                    candidate.shmid
                    for candidate in candidates
                    if candidate.shmid not in removed
                ),
                unavailable=True,
            )
        if result.returncode == 0:
            removed.append(segment.shmid)
        else:
            print(
                "temporary_postgres: failed to remove leaked "
                f"shared-memory segment {segment.shmid}: {result.stderr.strip()}",
                file=output,
            )
    if removed:
        print(
            "temporary_postgres: removed leaked current-user Postgres "
            f"shared-memory segments: {', '.join(removed)}",
            file=output,
        )
    return IpcCleanupReport(
        removed_shmids=tuple(removed),
        skipped_shmids=tuple(segment.shmid for segment in ambiguous),
    )


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
            if not self.is_running():
                return
            try:
                self._stop_with_mode("fast")
            except AssertionError:
                if self.is_running():
                    self._stop_with_mode("immediate")

    def _stop_with_mode(self, mode: str):
        run(
            [
                str(self.bin_dir / "pg_ctl"),
                "-D",
                str(self.data),
                "-m",
                mode,
                "-w",
                "stop",
            ]
        )

    def is_running(self) -> bool:
        if not self.data.exists():
            return False
        try:
            result = subprocess.run(
                [
                    str(self.bin_dir / "pg_ctl"),
                    "-D",
                    str(self.data),
                    "status",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return True
        return result.returncode == 0

    def psql_scalar(self, sql: str) -> str:
        command = [
            self.psql_command,
            *self.psql_args,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        result = run(command, sql)
        lines = [line for line in result.stdout.splitlines() if line]
        return lines[-1] if lines else ""


class temporary_postgres:
    def __init__(
        self,
        *,
        ipc_guard_factory=PostgresIpcGuard,
        cluster_class=PostgresCluster,
    ):
        self._ipc_guard_factory = ipc_guard_factory
        self._cluster_class = cluster_class

    def __enter__(self):
        self.ipc_guard = self._ipc_guard_factory()
        if not self.ipc_guard.capture_baseline():
            raise unittest.SkipTest(
                "temporary Postgres requires host System V shared-memory "
                "inspection via ipcs -m -a; rerun integration tests with host "
                "IPC access"
            )
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cluster = self._cluster_class(Path(self.tmpdir.name))
        try:
            return self.cluster.start()
        except BaseException:
            self._teardown()
            raise

    def __exit__(self, exc_type, exc, tb):
        self._teardown()

    def _teardown(self):
        cluster = getattr(self, "cluster", None)
        stop_error = None
        live_test_processes = False
        if cluster is not None:
            try:
                cluster.stop()
            except BaseException as error:
                stop_error = error
            finally:
                live_test_processes = cluster.is_running()
                self.ipc_guard.cleanup(
                    live_test_processes=live_test_processes,
                )
        try:
            if stop_error is not None:
                raise stop_error
        finally:
            tmpdir = getattr(self, "tmpdir", None)
            if tmpdir is not None and not live_test_processes:
                tmpdir.cleanup()


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
