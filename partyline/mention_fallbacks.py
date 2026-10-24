"""Mentions on a task line that would otherwise reach nobody, and where they go instead.

Two silent drops, both reported from a live tree. A task process that still
said ``@astra`` after the captaincy moved to ``@opus`` rang a detached row on
the root line; and one that mentioned its task's detached reviewer got
"nothing was delivered" although the message sits in the line and is read as
backlog on resume. Here the first is relayed to the current root captain and
the second is told the truth, with the one revive a waiting verdict needs.
"""

import logging

from fastapi import HTTPException

from .mentions import mentioned_names
from .mention_relay import (
    is_foreign,
    post_private,
    speaker_attachment,
    task_root_captain,
)
from .orchestrator_store import task

logger = logging.getLogger(__name__)
GONE = ("detached", "exited")
RESTART = {"reviewer": "restart_reviewer", "implementer": "restart_implementer"}


async def route_fallbacks(runtime, conv_id: str, message: dict, names: set[str]) -> set[str]:
    """Handle ``names`` that reached nobody on a task line; return those handled."""
    row = task(runtime.db, conv_id)
    if row is None or message.get("sender_type") == "system" or not names:
        return set()
    handled = await _own_staff(runtime, conv_id, row, names)
    if message.get("sender_type") == "agent" and not is_foreign(message):
        handled |= await _former_captain(runtime, conv_id, row, message, names - handled)
    return handled


async def _own_staff(runtime, conv_id: str, row: dict, names: set[str]) -> set[str]:
    handled: set[str] = set()
    for role in ("reviewer", "implementer"):
        att = runtime.db.get_attachment(row[f"{role}_id"]) if row[f"{role}_id"] else None
        if att is None or att["conv_id"] != conv_id or att["name"].lower() not in names:
            continue
        if att["status"] not in GONE:
            continue
        handled.add(att["name"].lower())
        revived = role == "reviewer" and await _revive_in_review(runtime, conv_id)
        tail = ("it is being revived for this review round and will read this"
                if revived else
                f"it will read this when revived — the root captain revives it with {RESTART[role]}")
        await runtime.post_message(
            conv_id, "system", "system", f"⚠ @{att['name']} is {att['status']}; {tail}")
    return handled


async def _revive_in_review(runtime, conv_id: str) -> bool:
    """Restart a gone reviewer of an in-review task so a verdict is not left waiting."""
    from . import orchestrator_revive as revive  # it imports the routes that import this module

    async with revive.task_lock(runtime, conv_id):
        row = task(runtime.db, conv_id)
        # reviewer_exited owns the restart counter; at its cap it has reported, so do not loop here.
        if (row["status"] != "in_review" or not revive.staffed_by_preset(row)
                or row["reviewer_restarts"] >= 2 or revive.reviewer_is_live(runtime.db, row)):
            return False
        try:
            await revive.revive_reviewer(runtime, row)
        except (HTTPException, ValueError):
            logger.exception("reviewer revive for task %s failed", conv_id)
            return False
    return True


async def _former_captain(runtime, conv_id: str, row: dict, message: dict, names: set[str]) -> set[str]:
    db = runtime.db
    speaker = speaker_attachment(db, conv_id, message)
    root = task_root_captain(db, conv_id)
    if speaker is None or root is None or speaker["id"] == root["id"]:
        return set()
    handled: set[str] = set()
    for att in db.list_attachments(row["root_id"]):
        name = att["name"].lower()
        if name not in names or name == root["name"].lower() or att["status"] not in GONE:
            continue
        handled.add(name)
        if root["name"].lower() not in mentioned_names(message["body"]):  # else it is already rung
            await post_private(
                runtime, row["root_id"], message["sender"], message["sender_type"],
                f"↪ @{att['name']} is no longer attached on the root line; "
                f"delivered to the current captain @{root['name']}:\n" + message["body"],
                audience=root["id"], source=(speaker["id"], conv_id), private=True)
        await post_private(
            runtime, conv_id, "system", "system",
            f"⚠ @{att['name']} is not attached; the root captain is @{root['name']}",
            audience=speaker["id"], route=False)
    return handled
