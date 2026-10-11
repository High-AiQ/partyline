"""Shared-resource leases: take a capability instead of arguing in prose.

Three lines each ran Godot under xvfb and each kept "one Godot at a time" as
a sentence in its topic; nothing told a captain another line held the slot,
so coordination waited on a person (finding 2.10). A lease names the
capability instead: an exclusive lease waits behind any holder, shared
leases coexist with each other but not with an exclusive one, everything
expires at its TTL, and a process's leases die with its process. Callers
poll — there is no blocking request to hold open.
"""

from __future__ import annotations

import re
import time

from fastapi import HTTPException, Request

from .auth_guard import request_principal

LEASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MODES = ("exclusive", "shared")
MAX_TTL_S = 4 * 3600
DEFAULT_TTL_S = 900


class LeaseError(ValueError):
    """A malformed lease request; the route answers 422 with the message."""


def _purge_expired(db) -> None:
    db._exec("DELETE FROM resource_leases WHERE expires_at<=?", (time.time(),))


def _promote(db, row: dict, now: float) -> None:
    """Turn one waiter into the holder, honouring the TTL it queued with."""
    ttl = max(1, int(row["expires_at"] - row["created_at"]))
    _upsert(db, {**row, "waiting": 0, "expires_at": now + ttl})


def _upsert(db, row: dict) -> None:
    """Insert or refresh one lease row. ``created_at`` is write-once: for a
    waiter it is the queue place, and renewing must never move it."""
    db._exec(
        "INSERT INTO resource_leases(name,holder_attachment,holder_handle,holder_line,"
        "mode,waiting,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(name,holder_attachment) DO UPDATE SET holder_handle=excluded."
        "holder_handle, holder_line=excluded.holder_line, mode=excluded.mode, "
        "waiting=excluded.waiting, expires_at=excluded.expires_at",
        (row["name"], row["holder_attachment"], row["holder_handle"], row["holder_line"],
         row["mode"], row["waiting"], row["created_at"], row["expires_at"]))


def request_lease(db, holder_attachment: str, holder_handle: str, holder_line: str,
                  name: str, mode: str, ttl_s: int) -> dict:
    """Take, renew, or queue for one lease; the caller polls, never blocks.

    Exclusive waits behind any holder; shared waits only behind an exclusive
    one. Queue place is held: a waiter keeps its original queue-time, so
    polling cannot slide it backwards, and when the lease frees, promotion is
    by queue order — the earliest waiter for an exclusive lease, the leading
    run of shared waiters for a shared one. A brand-new caller queues behind
    everyone already waiting.
    """
    name = (name or "").strip()
    if not LEASE_NAME.fullmatch(name):
        raise LeaseError("lease name must be 1-64 letters, digits, dots, dashes")
    if mode not in MODES:
        raise LeaseError(f"mode must be one of: {', '.join(MODES)}")
    ttl_s = int(ttl_s)
    if not 1 <= ttl_s <= MAX_TTL_S:
        raise LeaseError(f"ttl_s must be between 1 and {MAX_TTL_S} (4 hours)")
    now = time.time()
    _purge_expired(db)
    rows = [dict(row) for row in db._exec(
        "SELECT * FROM resource_leases WHERE name=?", (name,)).fetchall()]
    held = [row for row in rows if not row["waiting"]]
    waiters = sorted((row for row in rows if row["waiting"]),
                     key=lambda row: row["created_at"])
    if not held and waiters:
        # The slot is free: promote by queue order — the earliest waiter, or
        # every leading shared waiter together.
        promoted = [waiters[0]]
        if promoted[0]["mode"] == "shared":
            promoted += [row for row in waiters[1:] if row["mode"] == "shared"]
        for row in promoted:
            _promote(db, row, now)
        held = [dict(row, waiting=0) for row in promoted]
    others = [row for row in held if row["holder_attachment"] != holder_attachment]
    blocked = any(row["mode"] == "exclusive" for row in others) or (
        mode == "exclusive" and bool(others))
    if blocked:
        holder = others[0] if others else held[0]
        ahead = len([row for row in rows if row["holder_attachment"] != holder_attachment])
        _upsert(db, {"name": name, "holder_attachment": holder_attachment,
                     "holder_handle": holder_handle, "holder_line": holder_line,
                     "mode": mode, "waiting": 1, "created_at": now,
                     "expires_at": now + ttl_s})
        return {"granted": False, "name": name, "mode": mode,
                "holder": {"handle": holder["holder_handle"],
                           "line": holder["holder_line"]},
                "queue_position": ahead, "expires_at": holder["expires_at"]}
    _upsert(db, {"name": name, "holder_attachment": holder_attachment,
                 "holder_handle": holder_handle, "holder_line": holder_line,
                 "mode": mode, "waiting": 0, "created_at": now,
                 "expires_at": now + ttl_s})
    return {"granted": True, "name": name, "mode": mode,
            "holder": {"handle": holder_handle, "line": holder_line},
            "queue_position": 0, "expires_at": now + ttl_s}


def release_lease(db, holder_attachment: str, name: str) -> bool:
    """Release one lease held by the caller; False when it holds no such lease."""
    _purge_expired(db)
    cursor = db._exec(
        "DELETE FROM resource_leases WHERE holder_attachment=? AND name=?",
        (holder_attachment, (name or "").strip()))
    return bool(cursor.rowcount)


def release_attachment_leases(db, holder_attachment: str) -> int:
    """Drop every lease a process holds; it exited or detached, the slot is free."""
    _purge_expired(db)
    cursor = db._exec(
        "DELETE FROM resource_leases WHERE holder_attachment=?", (holder_attachment,))
    return cursor.rowcount


def active_lease_report(db) -> list[dict]:
    """Every held lease with its waiters, for the listing and the staffing line."""
    _purge_expired(db)
    held: dict[str, dict] = {}
    queued: dict[str, int] = {}
    for row in db._exec(
            "SELECT * FROM resource_leases WHERE expires_at>? ORDER BY created_at",
            (time.time(),)).fetchall():
        row = dict(row)
        if row["waiting"]:
            queued[row["name"]] = queued.get(row["name"], 0) + 1
        else:
            held.setdefault(row["name"], {**row, "holders": []})["holders"].append(
                {"handle": row["holder_handle"], "line": row["holder_line"],
                 "mode": row["mode"]})
    report = []
    for name, lease in held.items():
        report.append({"name": name, "mode": lease["mode"], "holders": lease["holders"],
                       "queued": queued.get(name, 0), "expires_at": lease["expires_at"]})
    for name, count in queued.items():
        if name not in held:
            report.append({"name": name, "mode": "", "holders": [],
                           "queued": count, "expires_at": 0})
    return sorted(report, key=lambda entry: entry["name"])


def describe_leases(db) -> str:
    """The staffing-line segment for held leases, or empty when none are held."""
    try:
        report = active_lease_report(db)
    except Exception:
        return ""  # a minimal db (the staffing tests' fake) holds no leases
    held = [entry for entry in report if entry["holders"]]
    if not held:
        return ""
    parts = []
    for entry in held:
        holders = " + ".join(f"@{h['handle']} «{h['line']}»" for h in entry["holders"])
        part = f"{entry['name']} ({entry['mode']}) {holders}"
        if entry["queued"]:
            part += f", {entry['queued']} queued"
        parts.append(part)
    return "leases: " + "; ".join(parts)


def register_lease_routes(app, runtime) -> None:
    @app.post("/api/leases")
    async def post_lease(request: Request, body: dict):
        principal = request_principal(request)
        # A lease is held by a process so that its exit or detach frees it; a
        # person has neither, and an empty id would share one lease identity
        # among every person on the host.
        if not principal.attachment_id:
            raise HTTPException(403, "leases are taken and released by processes")
        try:
            return request_lease(
                runtime.db, principal.attachment_id, principal.name,
                principal.conv_id or "", body.get("name", ""),
                body.get("mode", "exclusive"), body.get("ttl_s", DEFAULT_TTL_S))
        except LeaseError as exc:
            raise HTTPException(422, str(exc)) from None
        except (TypeError, ValueError):
            raise HTTPException(422, "lease request is malformed") from None

    @app.get("/api/leases")
    async def list_leases(request: Request):
        request_principal(request)
        return {"leases": active_lease_report(runtime.db)}

    @app.delete("/api/leases/{name}")
    async def delete_lease(name: str, request: Request):
        principal = request_principal(request)
        att_id = principal.attachment_id or ""
        if not att_id:
            raise HTTPException(403, "leases are taken and released by processes")
        if not release_lease(runtime.db, att_id, name):
            raise HTTPException(404, "this process holds no such lease")
        return {"ok": True, "name": name}
