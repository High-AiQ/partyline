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
from collections.abc import Callable
from pathlib import Path

from scripts.cockpit_venv import probe_server, replacement_python
from scripts.cockpit_arm import (
    preflight_server_config,
    resolve_server_config,
    with_server_config,
)

EXIT_ALREADY_GONE = 20
EXIT_WRONG_GENERATION = 21
EXIT_BAD_ARGUMENTS = 22
EXIT_WOULD_NOT_EXIT = 23
EXIT_LAUNCH_FAILED = 24
EXIT_SIGNAL_FAILED = 25
EXIT_ENVIRONMENT_UNREADABLE = 26
EXIT_COMMAND_LINE_UNREADABLE = 27
EXIT_REPLACEMENT_UNIMPORTABLE = 28
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


def process_cmdline(pid: int, proc_root: Path = Path("/proc")) -> list[str] | None:
    """Return the exact argument vector from ``/proc/<pid>/cmdline``."""
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    arguments = [
        entry.decode(errors="surrogateescape")
        for entry in raw.split(b"\0")
        if entry
    ]
    return arguments or None


def post_failure(base_url: str, report_token: str, message: str) -> None:
    """Post a visible warning through the old server while it is still live.

    The watchdog is neither an attachment nor a user, so it never impersonates
    one: it presents the plan's own ``report_token`` to the failure-report
    route, which posts a *system* notice to the planned line. A missing token
    is refused here, loudly, before any network call.
    """
    from urllib.request import Request, urlopen

    if not report_token:
        raise RuntimeError(
            "no failure report token was provided; the report cannot authenticate"
        )
    request = Request(
        base_url.rstrip("/") + "/api/restart-plan/failure",
        data=json.dumps({"token": report_token, "message": message}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        response.read()


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


def launch_server(
    server: Path,
    logfile: Path,
    cwd: Path,
    env: dict[str, str],
    arguments: list[str],
) -> None:
    """Make the deployed server the systemd service's main process."""
    os.chdir(cwd)
    with logfile.open("a") as stream:
        stream.write(f"--- cockpit restarted {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n")
        stream.flush()
        os.dup2(stream.fileno(), sys.stdout.fileno())
        os.dup2(stream.fileno(), sys.stderr.fileno())
        os.execve(str(server), [str(server), *arguments], env)


def run_restart(
    pid: int,
    expected_start: str,
    server: Path,
    logfile: Path,
    cwd: Path,
    *,
    server_config: Path | None = None,
    generation: Callable[[int], str | None] = process_generation,
    environment: Callable[[int], dict[str, str] | None] = process_environment,
    command_line: Callable[[int], list[str] | None] = process_cmdline,
    signal_process: Callable[[int, int], None] = os.kill,
    wait: Callable[[int, str], None] = wait_for_generation_exit,
    launch: Callable[[Path, Path, Path, dict[str, str], list[str]], None] = launch_server,
    probe: Callable[[Path, Path], str | None] | None = None,
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
    command = command_line(pid)
    if command is None or str(server) not in command:
        raise RestartRefused(
            f"could not read the command line of pid {pid}",
            EXIT_COMMAND_LINE_UNREADABLE,
        )
    arguments = command[command.index(str(server)) + 1 :]
    if server_config is not None:
        try:
            arguments = with_server_config(arguments, server_config)
            expected = preflight_server_config(server_config)
            effective = resolve_server_config(server_config, arguments, env)
        except (RuntimeError, ValueError) as exc:
            raise RestartRefused(
                f"explicit server config is unusable: {exc}", EXIT_BAD_ARGUMENTS
            ) from exc
        if effective != expected:
            raise RestartRefused(
                "outgoing server argv or environment overrides the explicit config",
                EXIT_BAD_ARGUMENTS,
            )

    # Prove the replacement can import *before* killing the live server.
    # A fast-forwarded tree with a stale venv is how v0.32.0 left the room
    # down: timer fired, old pid exited, new process died on `import PIL`.
    check = probe or (
        lambda _cwd, _server: probe_server(replacement_python(_server), _cwd)
    )
    if refused := check(cwd, server):
        raise RestartRefused(
            f"replacement cannot import partyline.server: {refused}",
            EXIT_REPLACEMENT_UNIMPORTABLE,
        )

    try:
        signal_process(pid, signal.SIGTERM)
    except OSError as exc:
        raise RestartRefused(f"could not signal pid {pid}: {exc}", EXIT_SIGNAL_FAILED) from exc
    wait(pid, expected_start)
    launch(server, logfile, cwd, env, arguments)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("old_pid", type=int)
    parser.add_argument("old_start")
    parser.add_argument("server", type=Path)
    parser.add_argument("logfile", type=Path)
    parser.add_argument("cwd", type=Path)
    parser.add_argument("--failure-url")
    parser.add_argument("--report-token")
    parser.add_argument("--server-config", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_BAD_ARGUMENTS if exc.code else 0

    try:
        run_restart(
            args.old_pid, args.old_start, args.server, args.logfile, args.cwd,
            server_config=args.server_config,
        )
    except RestartRefused as exc:
        print(exc, file=sys.stderr)
        if args.failure_url:
            try:
                post_failure(
                    args.failure_url,
                    args.report_token or "",
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
