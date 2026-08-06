"""Tests for the restart script itself.

Two dogfood restarts failed at the trigger while every gate, review and proof
was green. The second one is the reason this file exists: the logic lived
inline in a systemd unit, quoting collapsed through systemd → bash → awk, and
`awk '{print $22}'` arrived as `{print \\130014102}`. The generation read came
back empty, the guard read that as "not the process I meant", and refused —
correctly. Nobody was reading the journal, so a loud failure was silent to us
for ten hours.

The script is a file now so it can be run here, with a real process to signal
and no server involved. What is actually being tested is the *guard*: it must
refuse anything it cannot positively identify, and it must say which refusal it
made rather than merely failing.
"""

import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "restart_server.sh"

ALREADY_GONE = 20
WRONG_GENERATION = 21
BAD_ARGUMENTS = 22


def generation_of(pid: int) -> str:
    """Field 22 of /proc/<pid>/stat: the start time in clock ticks."""
    return Path(f"/proc/{pid}/stat").read_text().split()[21]


def run(*args, timeout=30):
    return subprocess.run([str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, timeout=timeout)


class SleeperProcess:
    """A real process to point the script at, owned by nobody in this test.

    Deliberately a *grandchild*, reparented to init. A direct `Popen` child
    becomes a zombie when the script kills it — `/proc/<pid>` survives until the
    test process reaps it, and the test process is blocked waiting for the
    script, which is in turn waiting for that `/proc` entry to vanish. The
    success case would deadlock for the full timeout and look like the script's
    fault. A real partyline server is not our child either, so this also happens
    to be the more faithful fixture.
    """

    def __enter__(self):
        started = subprocess.run(
            ["sh", "-c", "setsid sleep 120 >/dev/null 2>&1 & echo $!"],
            capture_output=True, text=True, check=True)
        self.pid = int(started.stdout.strip())
        return self

    def alive(self) -> bool:
        return Path(f"/proc/{self.pid}").exists()

    def __exit__(self, *exc):
        with contextlib.suppress(ProcessLookupError):
            os.kill(self.pid, signal.SIGKILL)


class ArgumentTest(unittest.TestCase):
    def test_the_script_is_executable(self):
        # A unit file that cannot exec its script fails in a way that looks
        # like the script being wrong.
        self.assertTrue(os.access(SCRIPT, os.X_OK), f"{SCRIPT} is not executable")

    def test_missing_arguments_are_refused_distinctly(self):
        self.assertEqual(run(1, 2).returncode, BAD_ARGUMENTS)


class GenerationGuardTest(unittest.TestCase):
    """The guard must identify a process, not merely find a pid."""

    def test_a_pid_that_is_gone_is_reported_as_gone(self):
        with SleeperProcess() as sleeper:
            pid, start = sleeper.pid, generation_of(sleeper.pid)
            os.kill(pid, signal.SIGKILL)
            while Path(f"/proc/{pid}").exists():
                pass
        result = run(pid, start, "/bin/true", "/dev/null")
        self.assertEqual(result.returncode, ALREADY_GONE, result.stderr)
        self.assertIn("disappeared", result.stderr)

    def test_a_different_generation_is_refused(self):
        """A pid is a name the kernel reuses; only pid + start time is an
        identity. Signalling on the name alone would eventually kill a stranger."""
        with SleeperProcess() as sleeper:
            wrong_start = str(int(generation_of(sleeper.pid)) + 1)
            result = run(sleeper.pid, wrong_start, "/bin/true", "/dev/null")
            self.assertEqual(result.returncode, WRONG_GENERATION, result.stderr)
            self.assertIn("expected", result.stderr)
            # And it must not have killed the process it declined to identify.
            self.assertTrue(sleeper.alive(), "the guard signalled anyway")

    def test_the_generation_read_survives_quoting(self):
        """The control for the failure that cost ten hours.

        `awk '{print $22}'` inside the script must read field 22, not have `$22`
        substituted by a shell. If quoting ever breaks again the read returns
        empty, and this test fails because a correct generation is refused.
        """
        with SleeperProcess() as sleeper:
            result = run(sleeper.pid, generation_of(sleeper.pid), "/bin/true", "/dev/null")
            self.assertNotEqual(
                result.returncode, WRONG_GENERATION,
                f"a correct generation was refused — the read is broken again: {result.stderr}")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_matching_generation_is_replaced(self):
        with tempfile.NamedTemporaryFile("r", suffix=".log", delete=False) as handle:
            logfile = Path(handle.name)
        try:
            with SleeperProcess() as sleeper:
                result = run(sleeper.pid, generation_of(sleeper.pid), "/bin/true", logfile)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(sleeper.alive(), "the old process was left running")
            self.assertIn("cockpit restarted", logfile.read_text())
        finally:
            logfile.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(unittest.main())
