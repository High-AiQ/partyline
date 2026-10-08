"""Fleet-wide admission and visibility for attached-process resources."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import HTTPException

from .process_memory import DEFAULT_PROCESS_MEMORY_LIMIT, parse_size, process_memory_limit
from .server_memory import host_memory_bytes

GIB = 1024**3
MIN_LEASE = 256 * 1024**2
MIN_RESERVATION = 256 * 1024**2
DEFAULT_RESERVATION = GIB
MAX_PROCESSES = 32
LIVE = ("starting", "running")


@dataclass(frozen=True)
class Host:
    cpus: int
    ram_bytes: int


def host_resources() -> Host:
    """Return portable host totals; injectable host values keep policy testable."""
    return Host(max(1, os.cpu_count() or 1), host_memory_bytes())


def defaults(host: Host | None = None) -> dict[str, int]:
    host = host or host_resources()
    ceiling_default = min(parse_size(DEFAULT_PROCESS_MEMORY_LIMIT), max(2 * GIB, host.ram_bytes // 8))
    lease = min(ceiling_default, memory_ceiling(host))
    reserve = max(2 * GIB, host.ram_bytes // 10)
    reserve = min(reserve, max(0, host.ram_bytes - lease))
    return {
        "max_live_processes": max(4, min(MAX_PROCESSES, host.cpus * 2)),
        "memory_reserve_bytes": reserve,
        "default_process_memory_bytes": lease,
        "memory_reservation_bytes": min(lease, DEFAULT_RESERVATION),
        "memory_warn_percent": 80,
        "memory_captain_ceiling_bytes": min(lease * 2, memory_ceiling(host)),
    }


def settings(db, host: Host | None = None) -> dict[str, int]:
    result = defaults(host)
    for key in result:
        value = db.get_setting(key)
        if value is not None:
            result[key] = int(value)
    result["memory_captain_ceiling_bytes"] = min(
        result["memory_captain_ceiling_bytes"], memory_ceiling(host)
    )
    return result


def memory_ceiling(host: Host | None = None) -> int:
    host = host or host_resources()
    configured = process_memory_limit({
        "PARTYLINE_PROCESS_MEMORY_LIMIT": os.environ.get(
            "PARTYLINE_MAX_PROCESS_MEMORY_LIMIT", "8G"
        )
    })
    return min(parse_size(configured), host.ram_bytes * 3 // 4)


def format_limit(amount: int) -> str:
    """Encode whole MiB leases in the format accepted by process_memory."""
    mib = max(1, (amount + 1024**2 - 1) // 1024**2)
    if mib % 1024 == 0:
        return f"{mib // 1024}G"
    return f"{mib}M"


def validate_settings(values: dict[str, int], host: Host | None = None) -> None:
    host = host or host_resources()
    if not 4 <= values["max_live_processes"] <= MAX_PROCESSES:
        raise ValueError(f"max_live_processes must be between 4 and {MAX_PROCESSES}")
    reserve = values["memory_reserve_bytes"]
    if reserve < 0 or reserve > host.ram_bytes * 9 // 10:
        raise ValueError("memory reserve must be nonnegative and at most 90% of host RAM")
    lease = values["default_process_memory_bytes"]
    if lease < MIN_LEASE or lease > memory_ceiling(host):
        raise ValueError("default process lease must be between 256 MB and the process ceiling")
    reservation = values["memory_reservation_bytes"]
    if reservation < MIN_RESERVATION or reservation > lease:
        raise ValueError("memory reservation must be between 256 MB and the default process lease")
    if host.ram_bytes - reserve < reservation:
        raise ValueError("memory budget must leave at least one default process reservation")
    if not 50 <= values.get("memory_warn_percent", 80) <= 95:
        raise ValueError("memory warning threshold must be between 50 and 95 percent")
    captain_ceiling = values.get("memory_captain_ceiling_bytes", min(lease * 2, memory_ceiling(host)))
    if not lease <= captain_ceiling <= memory_ceiling(host):
        raise ValueError("captain memory ceiling must be between the default cap and host ceiling")


def live_rows(db) -> list[dict]:
    with db.lock:
        rows = db.conn.execute(
            "SELECT a.*,c.name AS line_name FROM attachments a "
            "JOIN conversations c ON c.id=a.conv_id "
            "WHERE a.status IN ('starting','running') ORDER BY a.created_at,a.id"
        ).fetchall()
    return [dict(row) for row in rows]


def family_roots(db) -> dict[str, tuple[str, str]]:
    """Map every line id to its top-level line as ``(id, name)``."""
    with db.lock:
        rows = db.conn.execute("SELECT id,name,parent_id FROM conversations").fetchall()
    lines = {row["id"]: (row["name"], row["parent_id"]) for row in rows}
    roots: dict[str, tuple[str, str]] = {}
    for line_id in lines:
        current, seen = line_id, {line_id}
        while (parent := lines[current][1]) in lines and parent not in seen:
            seen.add(parent)
            current = parent
        roots[line_id] = (current, lines[current][0])
    return roots


def busiest_family(db, rows: list[dict]) -> str | None:
    """Name the top-level line whose whole family runs the most processes."""
    roots = family_roots(db)
    families: dict[str, list] = {}
    for row in rows:
        root_id, name = roots.get(row["conv_id"], (row["conv_id"], row["line_name"]))
        families.setdefault(root_id, [name, 0])[1] += 1
    return max(families.values(), key=lambda pair: pair[1], default=(None, 0))[0]


def cap_bytes(row: dict, config: dict[str, int]) -> int:
    if row.get("memory_limit"):
        try:
            return parse_size(row["memory_limit"])
        except (ValueError, KeyError, IndexError):
            pass
    return config["default_process_memory_bytes"]


def lease_bytes(row: dict, config: dict[str, int]) -> int:
    """Return the admission reservation, bounded by the process memory cap."""
    return min(cap_bytes(row, config), config["memory_reservation_bytes"])


def snapshot(db, host: Host | None = None) -> dict:
    host = host or host_resources()
    config = settings(db, host)
    rows = live_rows(db)
    budget = max(0, host.ram_bytes - config["memory_reserve_bytes"])
    busiest = busiest_family(db, rows)
    reserved = sum(lease_bytes(row, config) for row in rows)
    capped = sum(cap_bytes(row, config) for row in rows)
    return {
        **config,
        "host_ram_bytes": host.ram_bytes,
        "memory_budget_bytes": budget,
        "live_processes": len(rows),
        "memory_reserved_bytes": reserved,
        "memory_cap_bytes": capped,
        "remaining_processes": max(0, config["max_live_processes"] - len(rows)),
        "remaining_memory_bytes": max(0, budget - reserved),
        "busiest_line": busiest,
    }


def refusal(db, requested_lease: int, *, exclude_id: str | None = None,
            host: Host | None = None) -> str | None:
    view = snapshot(db, host)
    rows = live_rows(db)
    if exclude_id:
        rows = [row for row in rows if row["id"] != exclude_id]
        view["live_processes"] = len(rows)
        view["memory_reserved_bytes"] = sum(lease_bytes(row, view) for row in rows)
        view["memory_cap_bytes"] = sum(cap_bytes(row, view) for row in rows)
    count = view["live_processes"]
    maximum = view["max_live_processes"]
    if count >= maximum:
        return f"{count} of {maximum} live processes in use; stop one or raise the limit in settings"
    leased = view["memory_reserved_bytes"]
    budget = view["memory_budget_bytes"]
    reservation = min(requested_lease, view["memory_reservation_bytes"])
    if leased + reservation > budget:
        gib = GIB
        used_gb = (leased + reservation + gib - 1) // gib
        budget_gb = budget // gib
        return (f"memory budget full: {used_gb} of {budget_gb} GB would be reserved "
                f"({format_limit(reservation)} reservation per process); "
                "stop a process or raise the budget in settings")
    return None


def reject_if_full(db, requested_lease: int, *, exclude_id: str | None = None) -> None:
    if reason := refusal(db, requested_lease, exclude_id=exclude_id):
        raise HTTPException(409, reason)


async def reserve_new_attachment(db, *, att_id, conv_id, name, adapter, command,
                                cwd, runtime_owner, start_after_history=False):
    """Atomically admit and persist a starting row before any spawn work."""
    async with db._runtime_serialized_async():
        lease = settings(db)["default_process_memory_bytes"]
        reject_if_full(db, lease)
        return db.add_attachment(
            att_id, conv_id, name, adapter, command, cwd, runtime_owner,
            start_after_history=start_after_history, memory_limit=format_limit(lease),
        )


async def claim_resume(db, att_id: str, owner: str, requested_lease: int,
                       *, grandfathered: bool = False) -> bool:
    """Admit and flip a stopped row to starting in one shared critical section.

    Only restart-plan members that were live at restart may skip the capacity
    check; the caller derives this server-side from the coordinator's plan set.
    """
    async with db._runtime_serialized_async():
        with db.lock:
            claimable = db.conn.execute(
                "SELECT 1 FROM attachments a WHERE a.id=? "
                "AND a.status NOT IN ('starting','running') "
                "AND NOT EXISTS (SELECT 1 FROM attachments other "
                "WHERE other.conv_id=a.conv_id AND lower(other.name)=lower(a.name) "
                "AND other.id!=a.id AND other.status IN ('starting','running'))",
                (att_id,),
            ).fetchone()
        if claimable is None:
            return False
        if not grandfathered:
            reject_if_full(db, requested_lease)
        claimed = db._claim_attachment(att_id, owner)
        if claimed:
            db._exec(
                "UPDATE attachments SET memory_limit=? WHERE id=? AND runtime_owner=? "
                "AND memory_limit IS NULL",
                (format_limit(requested_lease), att_id, owner),
            )
        return claimed


async def clear_stale_restart_rows(runtime, attachment_ids: list[str]) -> None:
    """Exclude dead pre-restart rows before the coordinator admits its first CLI."""
    stopped: list[tuple[str, str]] = []
    async with runtime.db._runtime_serialized_async():
        with runtime.db.lock, runtime.db.conn:
            for ident in attachment_ids:
                if ident in runtime.live:
                    continue
                row = runtime.db.conn.execute(
                    "SELECT conv_id,runtime_owner FROM attachments WHERE id=? "
                    "AND status IN ('starting','running')", (ident,),
                ).fetchone()
                if row is None:
                    continue
                runtime.db.conn.execute(
                    "UPDATE attachments SET status='exited',runtime_started_at=NULL "
                    "WHERE id=? AND runtime_owner IS ?", (ident, row["runtime_owner"]),
                )
                stopped.append((row["conv_id"], ident))
    for conv_id, ident in stopped:
        await runtime.broadcast_attachment(conv_id, ident)
