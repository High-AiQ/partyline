"""Explain an unplanned interruption at startup (finding 5.14 item 6).

Partyline's approved restarts come down gracefully through
``request_exit``; a host reboot or a crash does not. On the way out of an
orderly stop a small marker records the boot id and the time; the next
startup reads it, then unlinks it:

- marker present, same host boot → the stop was an orderly approved
  restart; nothing is posted.
- marker present, different boot → the host rebooted since the marker was
  written: partyline died with the host, which is unplanned.
- marker absent → unplanned — but not on the very first start after this
  feature deploys: the previous server wrote no marker, so the first run
  only records that the watch exists. Every later marker-less start is an
  unplanned stop.

The marker is keyed per instance — it sits next to that instance's
database — so a dev instance's orderly restart can never mask the LAN
instance's crash. After an unplanned stop, every line that had live
processes is told so, which processes were running, and that resumed
processes must not replay interrupted heavy work (GPU or Docker batches)
without a person's go-ahead. Every path is injectable: tests use temp
files and never the real ``/proc`` or home.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from .legacy_tmp import reap_legacy_temp, reap_previous_tmp_root

logger = logging.getLogger(__name__)

LIVE = ("starting", "running")
WATCH_SETTING = "interruption_watch_seen"


def default_marker(db_path: str | None) -> str | None:
    """The marker sits next to the instance's database, keying it per instance."""
    return f"{db_path}.last-stop" if db_path else None


def boot_id(path: str | Path = "/proc/sys/kernel/random/boot_id") -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_orderly_marker(db_path: str | None, *,
                         marker_path: str | Path | None = None,
                         boot_id_path: str | Path = "/proc/sys/kernel/random/boot_id") -> None:
    """Record an orderly stop, for the next startup to recognise."""
    path = Path(marker_path) if marker_path else Path(default_marker(db_path) or "")
    if not str(path):
        return
    payload = {"boot": boot_id(boot_id_path), "at": time.time()}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def take_marker(marker_path: str | Path) -> dict | None:
    """Read the marker and unlink it: every start consumes it exactly once."""
    path = Path(marker_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
        return payload
    except (OSError, ValueError):
        return None


def interruption_state(marker: dict | None, *,
                       boot_id_path: str | Path = "/proc/sys/kernel/random/boot_id") -> dict:
    """Classify a consumed marker: ``orderly``, ``rebooted``, ``present``."""
    current = boot_id(boot_id_path)
    if marker is None:
        return {"orderly": False, "rebooted": False, "present": False}
    rebooted = bool(current) and marker.get("boot") != current
    return {"orderly": not rebooted, "rebooted": rebooted, "present": True}


def stale_live_rows(db) -> list[dict]:
    """Rows still marked live from before the stop, per line.

    Called before ``mark_stale_attachments`` flips them to exited. Partyline
    persists no mid-turn flag, so the notice says these processes *were
    running*, nothing stronger.
    """
    with db.lock:
        rows = db.conn.execute(
            "SELECT id,name,conv_id,status FROM attachments "
            "WHERE status IN ('starting','running') ORDER BY created_at,id"
        ).fetchall()
    return [dict(row) for row in rows]


def interruption_notice(state: dict, rows: list[dict]) -> dict[str, str]:
    """The per-line bodies for an unplanned stop; empty when it was orderly."""
    if state["orderly"] or not rows:
        return {}
    reason = "the host rebooted" if state["rebooted"] else \
        "partyline stopped without reaching its orderly shutdown"
    per_line: dict[str, list[str]] = {}
    for row in rows:
        per_line.setdefault(row["conv_id"], []).append(f"@{row['name']}")
    return {
        conv_id: (
            f"⚠ the last partyline stop was unplanned: {reason}. "
            f"Processes that were running: {', '.join(names)}. "
            "Do not replay interrupted heavy work (GPU or Docker batches) "
            "without a person's go-ahead."
        )
        for conv_id, names in per_line.items()
    }


async def post_interruption_notices(runtime, *,
                                    marker_path: str | Path | None = None,
                                    boot_id_path: str | Path = "/proc/sys/kernel/random/boot_id") -> bool:
    """Consume the marker and post the notices for an unplanned stop.

    Returns True when a notice was posted. The very first start after this
    feature deploys stays silent: the previous server wrote no marker, and
    posting "unplanned" to every line for that would be the bug finding
    5.14 item 6 warns about.
    """
    from .system_notice import post_system_notice

    db = runtime.db
    path = Path(marker_path) if marker_path else default_marker(db.path)
    if not str(path):
        return False
    seen = db.get_setting(WATCH_SETTING)
    marker = take_marker(path)
    state = interruption_state(marker, boot_id_path=boot_id_path)
    with db.lock, db.conn:
        db.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (WATCH_SETTING, "1"))
    if marker is None and not seen:
        # First start after this feature deploys: the old server wrote no
        # marker, and a crash-free history must not read as unplanned.
        return False
    bodies = interruption_notice(state, stale_live_rows(db))
    for conv_id, body in bodies.items():
        await post_system_notice(runtime, conv_id, body)
    return bool(bodies)


async def engage_startup(runtime) -> None:
    """The guarded startup housekeeping (findings 5.13, 5.14 item 6, 5.15).

    Posts the unplanned-stop notices, settles the stale rows, reaps the
    legacy temp locations, and reaps the previous tmpfs root once after the
    disk-backed switch. Every step is guarded: a failure logs and continues,
    and the blocking walks run in threads off the event loop.
    """
    try:
        await post_interruption_notices(runtime)
    except Exception:
        logger.exception("startup interruption notice failed; continuing")
    runtime.db.mark_stale_attachments()
    await asyncio.to_thread(sweep_orphaned_worktrees, runtime.db)
    try:
        await asyncio.to_thread(reap_legacy_temp, runtime.db)
    except Exception:
        logger.exception("legacy temp reap failed; continuing")
    try:
        await asyncio.to_thread(reap_previous_tmp_root, runtime.db)
    except Exception:
        logger.exception("previous tmp root reap failed; continuing")


def sweep_orphaned_worktrees(db):
    """Delegate to the worktree sweeper without importing the server here."""
    from .worktree_lifecycle import sweep_orphaned_worktrees as sweep

    return sweep(db)
