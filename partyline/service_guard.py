"""Check that systemd will contain a Partyline service OOM locally."""

from __future__ import annotations

import os
import subprocess
import sys


def unit_from_cgroup(path: str | None = None) -> str | None:
    """Return the most specific service, excluding the user manager itself."""
    if path is None:
        try:
            with open("/proc/self/cgroup", encoding="ascii") as cgroups:
                path = next(line.split(":", 2)[2].strip() for line in cgroups
                            if line.startswith("0::"))
        except (OSError, StopIteration):
            return None
    return next((part for part in reversed(path.split("/"))
                 if part.endswith(".service") and not part.startswith("user@")), None)


def _listed_partyline_unit() -> tuple[str | None, str]:
    """Find the active Partyline service when doctor runs from a shell."""
    try:
        done = subprocess.run(
            ["systemctl", "--user", "list-units", "--type=service", "--state=running",
             "--no-legend", "--plain"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not list running user services: {exc}"
    if done.returncode:
        detail = " ".join((done.stderr or done.stdout).split()) or "systemctl failed"
        return None, f"could not list running user services: {detail}"
    matches = []
    for line in done.stdout.splitlines():
        fields = line.split(maxsplit=4)
        if not fields or not fields[0].endswith(".service"):
            continue
        description = fields[4] if len(fields) > 4 else ""
        if "partyline" in fields[0].lower() or "partyline" in description.lower():
            matches.append(fields[0])
    if len(matches) == 1:
        return matches[0], ""
    if matches:
        return None, f"multiple running Partyline units found: {', '.join(matches)}"
    return None, "no running Partyline user service found"


def _host_memory_bytes() -> int:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def _memory_bytes(value: str) -> int | None:
    raw = value.strip().lower()
    if raw in ("", "infinity", "max"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    suffixes = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    suffix = raw[-1:]
    if suffix not in suffixes or not raw[:-1].isdigit():
        return None
    return int(raw[:-1]) * suffixes[suffix]


def _display_limit(amount: int) -> str:
    gib = 1024**3
    if amount >= gib and amount % gib == 0:
        return f"{amount // gib}G"
    return f"{amount}B"


def remedy(unit: str, host_bytes: int) -> str:
    """Exact user-unit drop-in and reload command for the detected service."""
    # Keep the service limit below host RAM with room for the OS and siblings.
    limit = host_bytes * 5 // 8
    if limit >= 1024**3:
        limit = limit // (1024**3) * 1024**3
    return (
        f"Person: create ~/.config/systemd/user/{unit}.d/oom.conf with exactly:\n"
        "[Service]\n"
        "OOMPolicy=continue\n"
        f"MemoryMax={_display_limit(limit)}\n"
        "Then run: systemctl --user daemon-reload\n"
        "After reload, file a Partyline restart request and have a person approve it."
    )


def check_properties(properties: dict[str, str], host_bytes: int,
                     unit: str) -> tuple[bool, str, str]:
    """Check effective unit values and return a copyable repair when unsafe."""
    failures = []
    if properties.get("OOMPolicy", "").lower() != "continue":
        failures.append("OOMPolicy=continue is not effective")
    maximum = _memory_bytes(properties.get("MemoryMax", ""))
    if maximum is None or maximum <= 0 or maximum >= host_bytes:
        failures.append("MemoryMax is not finite and below host RAM")
    if not failures:
        return True, "", ""
    return False, "; ".join(failures), remedy(unit, host_bytes)


def probe(unit: str | None = None, *, discover: bool = True) -> tuple[bool, str, str]:
    """Read the Partyline unit's effective limits, including from a shell doctor."""
    if not sys.platform.startswith("linux"):
        return True, "", ""
    if unit is None and discover:
        unit = os.environ.get("PARTYLINE_SYSTEMD_UNIT", "").strip() or None
    if unit is None and discover:
        current = unit_from_cgroup()
        unit = current if current and "partyline" in current.lower() else None
    lookup_reason = ""
    if unit is None and discover:
        unit, lookup_reason = _listed_partyline_unit()
    elif unit is None:
        lookup_reason = "Partyline's service unit is not in this process cgroup"
    actual_unit = unit or "partyline.service"
    host_bytes = _host_memory_bytes()
    install = remedy(actual_unit, host_bytes)
    if unit is None:
        from . import server_memory

        scope_ok, scope_reason = server_memory.verify()
        if scope_ok:
            return True, "", ""
        return (
            False,
            f"could not identify Partyline's systemd service unit: {lookup_reason}; "
            f"{scope_reason}",
            "Start Partyline with uv run partyline to create its memory scope automatically. "
            + install,
        )
    try:
        done = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=OOMPolicy,MemoryMax"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not inspect Partyline unit {unit}: {exc}", install
    if done.returncode:
        detail = " ".join((done.stderr or done.stdout).split()) or "systemctl failed"
        return False, f"could not inspect Partyline unit {unit}: {detail}", install
    properties = dict(line.partition("=")[::2] for line in done.stdout.splitlines()
                      if "=" in line)
    return check_properties(properties, host_bytes, unit)
