"""Startup sweep: stop process memory scopes whose processes are already gone.

A server restart kills its attachments' processes and starts fresh ones in new
scopes, so the old scopes must not pile up. The sweep is deliberately narrow: a
scope is stopped only when systemd still lists it active, it is not the scope of
a live attachment, and its cgroup reports ``populated 0`` (no process, no
descendant) when read immediately before the stop. A scope with a live process,
or one whose cgroup cannot be read, is never touched.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from .process_exit import SCOPE, stop_scope

logger = logging.getLogger(__name__)
CGROUP_ROOT = Path("/sys/fs/cgroup")


def _systemctl(run: Callable, *args: str) -> str:
    done = run(["systemctl", "--user", *args, "--no-pager"], capture_output=True,
               text=True, timeout=5, check=False)
    return "" if done.returncode else done.stdout


def _active_units(run: Callable, keep: set[str]) -> list[str]:
    listing = _systemctl(run, "list-units", "partyline-process-*.scope", "--all",
                         "--state=active", "--plain", "--no-legend")
    units = (line.split(None, 1)[0] for line in listing.splitlines() if line.strip())
    return [unit for unit in units if SCOPE.fullmatch(unit) and unit not in keep]


def _control_groups(run: Callable, units: list[str]) -> dict[str, str]:
    shown = _systemctl(run, "show", *units, "--property=Id", "--property=ControlGroup")
    groups: dict[str, str] = {}
    for block in shown.split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if fields.get("Id") in units and fields.get("ControlGroup", "").startswith("/"):
            groups[fields["Id"]] = fields["ControlGroup"]
    return groups


def cgroup_empty(group: str, root: Path = CGROUP_ROOT) -> bool:
    """Only an explicit ``populated 0`` counts; unreadable means occupied."""
    try:
        events = (root / group.lstrip("/") / "cgroup.events").read_text(encoding="ascii")
    except FileNotFoundError:
        return True  # systemd still lists the unit but its cgroup is already gone
    except (OSError, ValueError):
        return False
    return "populated 0" in events.split("\n")


def sweep_empty_scopes(keep: Iterable[str | None] = (), *, run: Callable = subprocess.run,
                       root: Path = CGROUP_ROOT, platform: str | None = None) -> int:
    """Stop empty, unowned partyline process scopes; return how many were stopped."""
    if not (sys.platform if platform is None else platform).startswith("linux"):
        return 0
    stopped = 0
    try:
        owned = {unit for unit in keep if unit}
        units = _active_units(run, owned)
        groups = _control_groups(run, units) if units else {}
        for unit in units:
            group = groups.get(unit)
            if group and cgroup_empty(group, root):
                stop_scope(unit)
                stopped += 1
    except (OSError, subprocess.SubprocessError):
        logger.warning("process scope sweep could not finish", exc_info=True)
    logger.info("process scope sweep stopped %d empty scope(s)", stopped)
    return stopped
