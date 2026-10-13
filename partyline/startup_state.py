"""Explain an unplanned interruption at startup (finding 5.14 item 6).

Partyline's approved restarts come down gracefully through
``request_exit``; a host reboot or a crash does not. On the way out of an
orderly stop a small marker records the boot id and the time; the next
startup reads it:

- marker present, same host boot → the stop was an orderly approved
  restart; nothing is posted.
- marker present, different boot → the host rebooted since the marker was
  written: partyline died with the host, which is unplanned.
- marker absent → the process stopped without reaching its orderly path:
  unplanned.

After an unplanned stop, every line that had live processes is told so —
which processes were mid-turn, whether the host rebooted — and that
resumed processes must not replay interrupted heavy work (GPU or Docker
batches) without a person's go-ahead. The marker itself lives under
``~/.partyline``; both paths are injectable, so tests use temp files and
never the real ``/proc`` or home.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

LIVE = ("starting", "running")
DEFAULT_MARKER = Path.home() / ".partyline" / "last-stop.json"
DEFAULT_BOOT_ID = "/proc/sys/kernel/random/boot_id"


def boot_id(path: str | Path = DEFAULT_BOOT_ID) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_orderly_marker(marker_path: str | Path | None = None,
                         boot_id_path: str | Path = DEFAULT_BOOT_ID) -> None:
    """Record an orderly stop, for the next startup to recognise."""
    path = Path(marker_path) if marker_path else DEFAULT_MARKER
    payload = {"boot": boot_id(boot_id_path), "at": time.time()}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_marker(marker_path: str | Path | None) -> dict | None:
    path = Path(marker_path) if marker_path else DEFAULT_MARKER
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def interruption_state(marker_path: str | Path | None = None,
                       boot_id_path: str | Path = DEFAULT_BOOT_ID) -> dict:
    """Classify the previous stop: ``orderly``, ``rebooted``, and whether a
    marker existed at all."""
    marker = _read_marker(marker_path)
    current = boot_id(boot_id_path)
    if marker is None:
        return {"orderly": False, "rebooted": False, "marker": False}
    rebooted = bool(current) and marker.get("boot") != current
    return {"orderly": not rebooted, "rebooted": rebooted, "marker": True}


def stale_live_rows(db) -> list[dict]:
    """Rows still marked live from before the stop, per line.

    Called before ``mark_stale_attachments`` flips them to exited.
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
            f"Mid-turn at the time: {', '.join(names)}. "
            "Do not replay interrupted heavy work (GPU or Docker batches) "
            "without a person's go-ahead."
        )
        for conv_id, names in per_line.items()
    }


async def post_interruption_notices(runtime, *, marker_path: str | Path | None = None,
                                    boot_id_path: str | Path = DEFAULT_BOOT_ID) -> bool:
    """Post the notices for an unplanned stop; True when one was posted."""
    from .system_notice import post_system_notice

    state = interruption_state(marker_path, boot_id_path)
    rows = stale_live_rows(runtime.db)
    posted = False
    for conv_id, body in interruption_notice(state, rows).items():
        await post_system_notice(runtime, conv_id, body)
        posted = True
    return posted
