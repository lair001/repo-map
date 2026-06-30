import subprocess
import unittest
from io import StringIO

from repomap_test_support.postgres_harness import (
    PostgresIpcGuard,
    SharedMemorySegment,
    cleanup_postgres_shared_memory_leaks,
    parse_ipcs_shared_memory,
    shared_memory_cleanup_candidates,
    temporary_postgres,
)


class PostgresHarnessUnitTests(unittest.TestCase):
    def test_baseline_segment_is_never_removed(self):
        baseline = (
            SharedMemorySegment(
                shmid="100",
                owner="slair",
                creator="slair",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=baseline,
            current=baseline,
            current_user="slair",
        )

        self.assertEqual(candidates, ())

    def test_non_current_user_segment_is_never_removed(self):
        current = (
            SharedMemorySegment(
                shmid="101",
                owner="postgres",
                creator="postgres",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
        )

        self.assertEqual(candidates, ())

    def test_attached_segment_is_never_removed(self):
        current = (
            SharedMemorySegment(
                shmid="102",
                owner="slair",
                creator="slair",
                nattch=1,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
        )

        self.assertEqual(candidates, ())

    def test_new_current_user_unattached_postgres_segment_is_selected(self):
        current = (
            SharedMemorySegment(
                shmid="103",
                owner="slair",
                creator="slair",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
        )

        self.assertEqual(candidates, current)

    def test_live_test_processes_skip_cleanup_candidates(self):
        current = (
            SharedMemorySegment(
                shmid="104",
                owner="slair",
                creator="slair",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
            live_test_processes=True,
        )

        self.assertEqual(candidates, ())

    def test_parse_ipcs_shared_memory_reads_macos_a_output(self):
        output = """\
IPC status from <running system> as of Mon Jun 29 23:45:50 EDT 2026
T     ID     KEY        MODE       OWNER    GROUP  CREATOR   CGROUP NATTCH  SEGSZ  CPID  LPID   ATIME    DTIME    CTIME
Shared Memory:
m 196609 0x00000000 --rw------- slair staff slair staff 0 56 100 0 no-entry no-entry 23:40
"""

        segments = parse_ipcs_shared_memory(output)

        self.assertEqual(
            segments,
            (
                SharedMemorySegment(
                    shmid="196609",
                    owner="slair",
                    creator="slair",
                    nattch=0,
                    size=56,
                ),
            ),
        )

    def test_cleanup_skips_when_ipcs_is_unavailable(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            raise FileNotFoundError("ipcs")

        report = cleanup_postgres_shared_memory_leaks(
            baseline=(),
            current_user="slair",
            runner=runner,
        )

        self.assertEqual(report.removed_shmids, ())
        self.assertEqual(calls, [["ipcs", "-m", "-a"]])

    def test_capture_baseline_reports_unavailable_ipcs_before_initdb(self):
        stderr = StringIO()

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="ipcs: sysctlbyname: Operation not permitted",
            )

        guard = PostgresIpcGuard(
            current_user="slair",
            runner=runner,
            stderr=stderr,
        )

        self.assertFalse(guard.capture_baseline())
        self.assertIsNone(guard.baseline)
        self.assertIn("refusing to start", stderr.getvalue())

    def test_cleanup_reports_when_baseline_is_unavailable(self):
        stderr = StringIO()

        report = cleanup_postgres_shared_memory_leaks(
            baseline=None,
            current_user="slair",
            stderr=stderr,
        )

        self.assertTrue(report.unavailable)
        self.assertEqual(report.removed_shmids, ())
        self.assertIn("baseline unavailable", stderr.getvalue())

    def test_temporary_postgres_skips_before_initdb_without_ipc_baseline(self):
        clusters = []

        class Guard:
            def capture_baseline(self):
                return False

            def cleanup(self, *, live_test_processes):
                raise AssertionError("cleanup should not run")

        class Cluster:
            def __init__(self, root):
                clusters.append(root)

        with self.assertRaisesRegex(unittest.SkipTest, "host IPC access"):
            with temporary_postgres(
                ipc_guard_factory=Guard,
                cluster_class=Cluster,
            ):
                pass

        self.assertEqual(clusters, [])

    def test_temporary_postgres_cleanup_runs_after_start_failure(self):
        clusters = []
        cleanup_calls = []

        class Guard:
            def capture_baseline(self):
                return True

            def cleanup(self, *, live_test_processes):
                cleanup_calls.append(live_test_processes)

        class FailingCluster:
            def __init__(self, root):
                self.root = root
                self.stopped = False
                clusters.append(self)

            def start(self):
                raise RuntimeError("bootstrap failed")

            def stop(self):
                self.stopped = True

            def is_running(self):
                return False

        with self.assertRaisesRegex(RuntimeError, "bootstrap failed"):
            with temporary_postgres(
                ipc_guard_factory=Guard,
                cluster_class=FailingCluster,
            ):
                pass

        self.assertEqual(len(clusters), 1)
        self.assertTrue(clusters[0].stopped)
        self.assertEqual(cleanup_calls, [False])

    def test_cleanup_command_receives_only_selected_shmids(self):
        calls = []
        ipcs_output = """\
T     ID     KEY        MODE       OWNER    GROUP  CREATOR   CGROUP NATTCH  SEGSZ  CPID  LPID   ATIME    DTIME    CTIME
Shared Memory:
m 201 0x00000000 --rw------- slair staff slair staff 0 56 100 0 no-entry no-entry 23:40
m 202 0x00000000 --rw------- other staff other staff 0 56 100 0 no-entry no-entry 23:40
m 203 0x00000000 --rw------- slair staff slair staff 2 56 100 0 no-entry no-entry 23:40
"""

        def runner(command, **kwargs):
            calls.append(command)
            if command == ["ipcs", "-m", "-a"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=ipcs_output,
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        report = cleanup_postgres_shared_memory_leaks(
            baseline=(),
            current_user="slair",
            runner=runner,
        )

        self.assertEqual(report.removed_shmids, ("201",))
        self.assertEqual(calls, [["ipcs", "-m", "-a"], ["ipcrm", "-m", "201"]])

    def test_cleanup_reports_ambiguous_new_current_user_segments(self):
        calls = []
        stderr = StringIO()
        ipcs_output = """\
T     ID     KEY        MODE       OWNER    GROUP  CREATOR   CGROUP NATTCH  SEGSZ  CPID  LPID   ATIME    DTIME    CTIME
Shared Memory:
m 301 0x00000000 --rw------- slair staff slair staff 0 4096 100 0 no-entry no-entry 23:40
"""

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=ipcs_output,
                stderr="",
            )

        report = cleanup_postgres_shared_memory_leaks(
            baseline=(),
            current_user="slair",
            runner=runner,
            stderr=stderr,
        )

        self.assertEqual(report.removed_shmids, ())
        self.assertEqual(report.skipped_shmids, ("301",))
        self.assertEqual(calls, [["ipcs", "-m", "-a"]])
        self.assertIn("ambiguous", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
