"""Verify a foreground server's kernel memory cap without requiring a service."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .process_memory import parse_size


def host_memory_bytes() -> int:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def limit_bytes() -> int:
    host = host_memory_bytes()
    value = os.environ.get("PARTYLINE_SERVER_MEMORY_LIMIT", "").strip().upper()
    if value:
        try:
            limit = parse_size(value)
        except (ValueError, KeyError, IndexError) as exc:
            raise ValueError("PARTYLINE_SERVER_MEMORY_LIMIT must be a size such as 2G") from exc
    else:
        limit = min(2 * 1024**3, host * 5 // 8)
    if not 0 < limit < host:
        raise ValueError("PARTYLINE_SERVER_MEMORY_LIMIT must be positive and below host RAM")
    return limit


def verify() -> tuple[bool, str]:
    try:
        relative = next(line.split(":", 2)[2] for line in
                        Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))
        directory = Path("/sys/fs/cgroup") / relative.lstrip("/")
        maximum = (directory / "memory.max").read_text().strip()
        group = (directory / "memory.oom.group").read_text().strip()
        if not maximum.isdigit() or not 0 < int(maximum) <= limit_bytes():
            return False, f"server memory.max is {maximum}; expected at most {limit_bytes()} bytes"
        if group != "0":
            return False, "server memory.oom.group must be 0"
        policy = subprocess.run(
            ["systemctl", "--user", "show", directory.name, "--property=OOMPolicy", "--value"],
            capture_output=True, text=True, timeout=10,
        )
        if policy.returncode or policy.stdout.strip() != "continue":
            return False, "server scope OOMPolicy=continue is not effective"
    except (OSError, StopIteration, subprocess.SubprocessError) as exc:
        return False, f"server cgroup memory controls are unavailable: {exc}"
    return True, ""
