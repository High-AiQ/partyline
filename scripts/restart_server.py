"""Replace one exact Partyline server generation with a deployed one.

This is an executable file rather than shell embedded in a systemd unit.  An
earlier restart put ``awk '{print $22}'`` through systemd, Bash, and awk; the
field reference was expanded into the expected start tick and the safety guard
refused the resulting nonsense.  Direct ``/proc`` parsing removes that quoting
boundary entirely.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

EXIT_ALREADY_GONE = 20
EXIT_WRONG_GENERATION = 21
EXIT_BAD_ARGUMENTS = 22
EXIT_WOULD_NOT_EXIT = 23
EXIT_LAUNCH_FAILED = 24
EXIT_SIGNAL_FAILED = 25
EXIT_ENVIRONMENT_UNREADABLE = 26
WAIT_SECONDS = 60.0


class RestartRefused(RuntimeError):
    """A safe refusal with a stable process exit code."""

    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


def process_generation(pid: int, proc_root: Path = Path("/proc")) -> str | None:
    """Return Linux ``/proc/<pid>/stat`` field 22 without a shell parser.

    The second field is a parenthesised command and may contain spaces, so a
    naive ``split()[21]`` is not correct.  Fields after the closing parenthesis
    begin at field 3; start time is therefore index 19 of that suffix.
    """
    try:
        stat = (proc_root / str(pid) / "stat").read_text()
        suffix = stat[stat.rindex(")") + 1 :].split()
        start = suffix[19]
    except (OSError, ValueError, IndexError):
        return None
    return start if start.isdigit() else None


def process_environment(pid: int, proc_root: Path = Path("/proc")) -> dict[str, str] | None:
    """Return ``/proc/<pid>/environ`` as a mapping, or None if unreadable.

    The trigger that runs this script lives in a transient systemd unit whose
    environment is systemd's minimal default — no user PATH, so a server
    exec'd from here could not find the CLIs it attaches. The replacement must
    inherit the outgoing server's environment, not the trigger's.
    """
    try:
        raw = (proc_root / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    environment = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        key, separator, value = entry.partition(b"=")
        if not separator or not key:
            continue
        environment[key.decode(errors="surrogateescape")] = value.decode(
            errors="surrogateescape")
    return environment or None


def post_failure(ws_url: str, message: str) -> None:
    """Post a visible warning through the old server while it is still live."""
    from websockets.sync.client import connect

    handle = f"restart-watchdog-{os.getpid()}"
    with connect(ws_url, open_timeout=5, close_timeout=1) as socket:
        socket.send(json.dumps({
            "type": "hello",
            "handle": handle,
            "client_id": str(uuid.uuid4()),
        }))
        response = json.loads(socket.recv(timeout=5))
        if response.get("type") != "hello":
            raise RuntimeError(f"restart watchdog could not claim a handle: {response}")
        socket.send(json.dumps({"sender": handle, "body": f"⚠ {message}"}))


def wait_for_generation_exit(
    pid: int,
    expected_start: str,
    *,
    generation: Callable[[int], str | None] = process_generation,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = WAIT_SECONDS,
) -> None:
    deadline = monotonic() + timeout
    while generation(pid) == expected_start:
        if monotonic() >= deadline:
            raise RestartRefused(
                f"pid {pid} did not exit within {timeout:g} seconds",
                EXIT_WOULD_NOT_EXIT,
            )
        sleep(0.2)


def launch_server(server: Path, logfile: Path, cwd: Path, env: dict[str, str]) -> None:
    """Make the deployed server the systemd service's main process."""
    os.chdir(cwd)
    with logfile.open("a") as stream:
        stream.write(f"--- cockpit restarted {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n")
        stream.flush()
        os.dup2(stream.fileno(), sys.stdout.fileno())
        os.dup2(stream.fileno(), sys.stderr.fileno())
        os.execve(str(server), [str(server)], env)


def run_restart(
    pid: int,
    expected_start: str,
    server: Path,
    logfile: Path,
    cwd: Path,
    *,
    generation: Callable[[int], str | None] = process_generation,
    environment: Callable[[int], dict[str, str] | None] = process_environment,
    signal_process: Callable[[int, int], None] = os.kill,
    wait: Callable[[int, str], None] = wait_for_generation_exit,
    launch: Callable[[Path, Path, Path, dict[str, str]], None] = launch_server,
) -> None:
    actual_start = generation(pid)
    if actual_start is None:
        raise RestartRefused(
            f"could not read the generation of pid {pid}; it may already be gone",
            EXIT_ALREADY_GONE,
        )
    if actual_start != expected_start:
        raise RestartRefused(
            f"pid {pid} is generation {actual_start}, expected {expected_start}",
            EXIT_WRONG_GENERATION,
        )
    if not server.is_file() or not os.access(server, os.X_OK):
        raise RestartRefused(f"server binary is not executable: {server}", EXIT_BAD_ARGUMENTS)
    # Snapshot while the old generation is still alive; after SIGTERM its
    # /proc entry is gone and only the trigger's stripped environment remains.
    env = environment(pid)
    if env is None:
        raise RestartRefused(
            f"could not read the environment of pid {pid}",
            EXIT_ENVIRONMENT_UNREADABLE,
        )

    try:
        signal_process(pid, signal.SIGTERM)
    except OSError as exc:
        raise RestartRefused(f"could not signal pid {pid}: {exc}", EXIT_SIGNAL_FAILED) from exc
    wait(pid, expected_start)
    launch(server, logfile, cwd, env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("old_pid", type=int)
    parser.add_argument("old_start")
    parser.add_argument("server", type=Path)
    parser.add_argument("logfile", type=Path)
    parser.add_argument("cwd", type=Path)
    parser.add_argument("--failure-ws")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_BAD_ARGUMENTS if exc.code else 0

    try:
        run_restart(args.old_pid, args.old_start, args.server, args.logfile, args.cwd)
    except RestartRefused as exc:
        print(exc, file=sys.stderr)
        if args.failure_ws:
            try:
                post_failure(
                    args.failure_ws,
                    f"automatic restart trigger refused: {exc}. The pending plan remains unclaimed.",
                )
            except Exception as report_error:
                print(f"could not report the restart failure to Partyline: {report_error}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"could not launch the deployed server: {exc}", file=sys.stderr)
        return EXIT_LAUNCH_FAILED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
