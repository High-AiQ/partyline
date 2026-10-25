"""Ghost mentions on a task line are caught before they are posted, and reported.

A task worker that ends its report with ``@review-<tag>`` when no reviewer is
staffed (captain-policy reviews have none until request_review) — or that names
its own task or line — writes words that reach nobody; the line learns it only
from a later warning. Here the mention is refused at the API instead: the
sender alone gets a short private correction naming the live root captain, and
that captain gets one private incident notice per (task, sender, handle) —
which task, who mentioned whom, whether the reviewer is missing or detached,
and the recovery ops — so repeats of one incident stay quiet. A mention of
this task's own detached staff still lands (``mention_fallbacks`` owns its
revive flow) but is reported to the captain the same way.
"""

from __future__ import annotations

import re
import time

from .hierarchy import tree_conversation_ids
from .mention_relay import LIVE, speaker_attachment, task_root_captain
from .mentions import mentioned_names
from .orchestrator_notices import tell
from .orchestrator_store import task

# Task handles are impl-<tag>/review-<tag>; pick_tag mints hex tags of six to
# twenty-five characters (orchestrator_handles.MAX_TAG).
TASK_HANDLE_RE = re.compile(r"(?:impl|review)-[0-9a-f]{6,25}")


def ghost_names(db, conv_id: str, row: dict, names: set[str]) -> set[str]:
    """Which ``names`` are task handles with no live process, or line names.

    A handle worn by any live process in the tree is routable and stays with
    the relay; this task's own staff and the root line's processes own their
    fallback flows in every status; people are readable without a wake.
    """
    if not names:
        return set()
    tree = tree_conversation_ids(db, conv_id)
    live = {att["name"].lower() for line in tree for att in db.list_attachments(line)
            if att["status"] in LIVE}
    known = {att["name"].lower() for line in (conv_id, row["root_id"])
             for att in db.list_attachments(line)}
    people = {str(person["handle"]).lower() for person in db._exec("SELECT handle FROM users")}
    lines = {(db.get_conversation(line) or {}).get("name", "").lower() for line in tree} - {""}
    return {name for name in names
            if name not in live and name not in known and name not in people
            and (TASK_HANDLE_RE.fullmatch(name) or name in lines)}


def correction_text(root_name: str, handles: list[str]) -> str:
    """The sender's short private correction, naming who is actually present."""
    named = ", ".join(f"@{name}" for name in handles)
    return (f"⚠ {named} reached nobody — task handles (impl-/review-) and line names are "
            f"not mentionable; request_review is the review hand-off, and to reach the "
            f"root captain, mention @{root_name}")


def reviewer_state(db, row: dict) -> str:
    att = db.get_attachment(row["reviewer_id"]) if row["reviewer_id"] else None
    if att is None:
        return "no reviewer is staffed"
    if att["status"] in LIVE:
        return "the reviewer is live"
    return f"the reviewer is {att['status']}"


def incident_text(db, row: dict, sender_name: str, handles: list[str]) -> str:
    line = db.get_conversation(row["conv_id"]) or {}
    named = ", ".join(f"@{name}" for name in handles)
    return (f"ghost mention on task «{line.get('name', '?')}» ({row['conv_id']}): "
            f"@{sender_name} mentioned {named}; {reviewer_state(db, row)}; recover with "
            "restart_reviewer / restart_implementer, then message_task the implementer "
            "to ask again")


async def report_incident(runtime, row: dict, speaker: dict, handles: list[str]) -> None:
    """Tell the root captain once per new (task, sender, handle); repeats stay quiet."""
    root = task_root_captain(runtime.db, row["conv_id"])
    if root is None or not handles:
        return
    db = runtime.db
    fresh: list[str] = []
    now = time.time()
    with db.lock:
        for name in handles:
            made = db.conn.execute(
                "INSERT OR IGNORE INTO task_ghost_mentions"
                "(conv_id,sender_id,name,created_at) VALUES(?,?,?,?)",
                (row["conv_id"], speaker["id"], name, now),
            ).rowcount
            db.conn.commit()
            if made:
                fresh.append(name)
    if fresh:
        await tell(runtime, root["id"], incident_text(db, row, speaker["name"], fresh))


async def report_detached(runtime, conv_id: str, message: dict, name: str) -> None:
    """A worker rang this task's own detached staff: the captain wants to know."""
    row = task(runtime.db, conv_id)
    speaker = speaker_attachment(runtime.db, conv_id, message)
    if row is None or speaker is None:
        return
    await report_incident(runtime, row, speaker, [name.lower()])


async def report_ghost_incidents(runtime, conv_id: str, speaker: dict,
                                 names: set[str]) -> None:
    """File captain notices for the ghost names a spoken (non-API) message used.

    Transcript speech cannot be refused, so the post-hoc hint keeps firing to
    the sender; the incident still reaches the root captain once per handle.
    """
    row = task(runtime.db, conv_id)
    if row is None:
        return
    ghosts = sorted(ghost_names(runtime.db, conv_id, row, names))
    if ghosts:
        await report_incident(runtime, row, speaker, ghosts)


async def ghost_mention_refusal(runtime, conv_id: str, principal, body: str) -> str | None:
    """The API correction for a machine's ghost mention on its own task line.

    Runs before the message is stored or anyone is woken, so the words that
    would reach nobody never land; the incident still reaches the root
    captain, once per handle. Without a live captain there is nobody to name,
    so the post-hoc hint keeps owning that case.
    """
    if getattr(principal, "kind", "") != "machine" or not principal.attachment_id:
        return None
    db = runtime.db
    row = task(db, conv_id)
    speaker = db.get_attachment(principal.attachment_id)
    if row is None or speaker is None or speaker["conv_id"] != conv_id:
        return None
    root = task_root_captain(db, conv_id)
    if root is None:
        return None
    names = mentioned_names(body) - {speaker["name"].lower()} - {"all"}
    ghosts = sorted(ghost_names(db, conv_id, row, names))
    if not ghosts:
        return None
    await report_incident(runtime, row, speaker, ghosts)
    return correction_text(root["name"], ghosts)
