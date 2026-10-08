"""Durable failures and a single escalation to the nearest available captain."""

import json
import time

from .contracts import MessageEvent, MessageResponse
from .hierarchy import ancestors
from .mention_relay import live_manager, post_private
from .process_exit import exit_notice
from .process_memory import format_memory_bytes, suggested_memory_limit
from .resource_budget import cap_bytes, memory_ceiling, settings


def exit_callback(runtime, att):
    async def report(evidence):
        await record_exit(runtime, att, evidence)
    return report


async def record_exit(runtime, att, evidence):
    """Reject stale activations and duplicate callbacks before posting any notices."""
    db = runtime.db
    ident, owner = att["id"], att["runtime_owner"]
    if evidence.code == 0 and evidence.reason == "exit":
        current = db.get_attachment(ident)
        if current is not None and current.get("runtime_owner") == owner:
            runtime.memory_usage.pop(ident, None)
        await runtime.post_callback(ident, att["conv_id"], owner)(
            "system", "system", exit_notice(att["name"], evidence))
        return
    async with db._runtime_serialized_async():
        current = db.get_attachment(ident)
        if current is None or current.get("runtime_owner") != owner:
            return
        runtime.memory_usage.pop(ident, None)
        saved = db._exec(
            "INSERT OR IGNORE INTO process_incidents "
            "(attachment_id,runtime_owner,evidence,created_at) VALUES(?,?,?,?)",
            (ident, owner, evidence.model_dump_json(), time.time()),
        )
        if not saved.rowcount:
            return
        detail = exit_notice(att["name"], evidence)
        budget_bytes = cap_bytes(current, settings(db))
        requested = suggested_memory_limit(budget_bytes, memory_ceiling())
        if evidence.reason == "oom":
            peak = format_memory_bytes(evidence.peak_bytes)
            # The kill happened at the scope's backstop; a request raises the budget.
            backstop = format_memory_bytes(evidence.limit_bytes)
            budget = format_memory_bytes(budget_bytes)
            hint = (
                f'POST /api/attachments/{ident}/memory-requests with '
                f'{{"requested_limit":"{requested}","reason":"…"}}.'
                if requested else "No larger budget fits under the host ceiling."
            )
            detail += (f" Incident {saved.lastrowid}; recorded peak {peak} at the {backstop} "
                       f"emergency backstop (budget {budget}). {hint}")
        detail += (f" Inspect GET /api/attachments/{ident}/memory. "
                   "Review the failed workload before resuming; the process remains stopped.")
        message = db.add_owned_message(ident, owner, att["conv_id"], "system", "system", detail)
    if message is None:
        return
    await runtime.broadcast(att["conv_id"], MessageEvent(message=MessageResponse.model_validate(message)))
    # System-authored, private, and identity-addressed: no accidental room-wide
    # mentions and no return-path debt. If a captain died, skip to its parent.
    for line in [att["conv_id"], *ancestors(db, att["conv_id"])]:
        captain = live_manager(runtime, line)
        if captain is None or captain["id"] == ident:
            continue
        check = ("Check the last tool/test for unbounded allocations or huge error output; "
                 if evidence.reason == "oom" else
                 "The exit cause is unconfirmed. Inspect the terminal and structured transcript; ")
        increase = (
            "Reduce its memory use or explicitly grant a larger budget if justified. "
            f'PUT the memory endpoint with {{"limit":"{requested}"}} '
            "(or null for the default), then use the normal resume endpoint. "
            if requested else
            "No larger budget fits under the host ceiling. Reduce the workload's memory use "
            "before using the normal resume endpoint. "
        )
        advice = check + increase + "Do not blindly restart the same failing command."
        await post_private(runtime, line, "system", "system", f"{detail} Captain action: {advice}",
                           audience=captain["id"], source=(ident, att["conv_id"]))
        break


def last_incident(db, ident):
    row = db._exec("SELECT id,evidence,created_at FROM process_incidents "
                   "WHERE attachment_id=? ORDER BY id DESC LIMIT 1", (ident,)).fetchone()
    return {**json.loads(row["evidence"]), "id": row["id"], "created_at": row["created_at"]} if row else None
