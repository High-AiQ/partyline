"""Bound each attached CLI without putting the Partyline service at risk."""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import sys

DEFAULT_PROCESS_MEMORY_LIMIT = "4G"


class MemoryScopeUnavailable(RuntimeError):
    """A Linux process cannot start without an enforceable memory scope."""


def process_memory_limit(env: dict[str, str] | None = None) -> str:
    """Return and validate the configurable per-process memory cap."""
    value = (env if env is not None else os.environ).get(
        "PARTYLINE_PROCESS_MEMORY_LIMIT", DEFAULT_PROCESS_MEMORY_LIMIT,
    ).strip().upper()
    if not value or value[-1] not in "KMG" or not value[:-1].isdigit():
        raise ValueError("PARTYLINE_PROCESS_MEMORY_LIMIT must be a positive size such as 4G")
    if int(value[:-1]) <= 0:
        raise ValueError("PARTYLINE_PROCESS_MEMORY_LIMIT must be a positive size such as 4G")
    return value


def scope_argv(command: list[str], limit: str, platform: str | None = None) -> list[str]:
    """Place Linux CLI argv in a private systemd scope with swap disabled."""
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux"):
        return list(command)
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        raise MemoryScopeUnavailable(
            "systemd-run is required to launch a fenced process with a memory cap"
        )
    verifier = [sys.executable, "-m", "partyline.process_memory", "--verify-exec", limit,
                "--", *command]
    return [systemd_run, "--user", "--scope", "-q", "--collect", "-p",
            f"MemoryMax={limit}", "-p", "MemorySwapMax=0", "--expand-environment=no", "--", *verifier]


def read_memory_max() -> str | None:
    """Read this process's cgroup-v2 memory.max, if it is mounted and readable."""
    try:
        with open("/proc/self/cgroup", encoding="ascii") as cgroups:
            relative = next(line.split(":", 2)[2].strip() for line in cgroups
                            if line.startswith("0::"))
        with open(f"/sys/fs/cgroup{relative}/memory.max", encoding="ascii") as limit_file:
            return limit_file.read().strip()
    except (OSError, StopIteration):
        return None


def memory_max_enforced(value: str | None, limit: str) -> bool:
    """Whether the current scope's kernel limit is finite and within the request."""
    if value is None or value == "max":
        return False
    try:
        return 0 < int(value) <= parse_size(limit)
    except ValueError:
        return False


def parse_size(value: str) -> int:
    suffix = value[-1]
    multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3}[suffix]
    return int(value[:-1]) * multiplier


def verify_scope_and_exec(limit: str, command: list[str]) -> int:
    """Refuse to start the fenced CLI unless the enclosing scope enforces its cap."""
    current = read_memory_max()
    if not memory_max_enforced(current, limit):
        print(f"partyline: refusing to start: memory limit {limit} is not enforced "
              f"(memory.max={current or 'unavailable'})", file=sys.stderr, flush=True)
        return 125
    os.execvp(command[0], command)
    return 125  # pragma: no cover - execvp replaces this process


def apply_address_space_limit(limit: str) -> None:
    """Apply the non-Linux per-process fallback before exec."""
    unit = limit[-1]
    multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3}[unit]
    amount = int(limit[:-1]) * multiplier
    resource.setrlimit(resource.RLIMIT_AS, (amount, amount))


def exit_notice(code: int, limit: str, name: str) -> str | None:
    """Explain a SIGKILL as the configured OOM limit in the line."""
    if code in (-9, 137):
        return f"{name} exited (code {code}): killed, most likely by the {limit} memory limit"
    if code == 125:
        return f"{name} refused to start: memory limit {limit} could not be verified"
    return None


def probe_scope() -> tuple[bool, str]:
    """Verify the configured Linux scope cap by reading memory.max inside it."""
    if not sys.platform.startswith("linux"):
        return True, ""
    limit = process_memory_limit()
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return False, "per-process memory scope probe failed: systemd-run is unavailable"
    code = (
        'while IFS=: read -r hierarchy controllers path; do '
        '[ "$hierarchy" = 0 ] && [ -z "$controllers" ] && break; done '
        '< /proc/self/cgroup; '
        'value=$(cat "/sys/fs/cgroup${path}/memory.max") || exit 1; '
        'printf "%s\\n" "$value"; '
        'case "$value" in ""|max|*[!0-9]*) exit 1 ;; esac; '
        '[ "$value" -gt 0 ] && [ "$value" -le "$1" ]'
    )
    # The shell owns these variables; systemd-run must not expand ${path} first.
    argv = [systemd_run, "--user", "--scope", "-q", "--collect", "--expand-environment=no", "-p",
            f"MemoryMax={limit}", "-p", "MemorySwapMax=0", "--",
            "/bin/sh", "-c", code, "partyline-memory-probe", str(parse_size(limit))]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"per-process memory scope probe failed: {exc}"
    current = done.stdout.strip()
    if done.returncode or not memory_max_enforced(current, limit):
        detail = " ".join(done.stderr.split()) or f"memory.max={current or 'unavailable'}"
        return False, f"per-process memory scope is not enforced at {limit}: {detail}"
    return True, ""


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "--verify-exec" and sys.argv[3] == "--":
        raise SystemExit(verify_scope_and_exec(sys.argv[2], sys.argv[4:]))
    raise SystemExit("usage: python -m partyline.process_memory --verify-exec LIMIT -- COMMAND")
