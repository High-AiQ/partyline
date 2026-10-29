"""Refresh manager knowledge from live permissions without waking a process."""

import os
import time
from typing import NamedTuple

from .goal import goal_rider
from .accept_sha import handoff_rider
from .bridge_pack import pack_for
from .captain_docs import reminder_line
from .compaction_events import current_turns
from .line_depth import depth as line_depth, has_captain, staffed_split_reason
from .role_briefing import WORKER_REMINDER, role_instructions, worker_instructions
from .staffing import staffing_line

RESOURCE_RIDER_INTERVAL = 600


def host_resource_line() -> str:
    """One line of host facts for a captain: cores, free memory, 1-minute load.

    Empty when the host declines to answer (no load average on Windows, no
    meminfo): a rider that guesses is worse than a rider that skips.
    """
    try:
        bits = [f"{os.cpu_count() or 1} cores"]
        free = None
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    free = int(line.split()[1]) * 1024
                    break
        if free is not None:
            bits.append(f"{free / 2**30:.1f} GB free")
        bits.append(f"load {os.getloadavg()[0]:.2f}")
        return "(host: " + ", ".join(bits) + ")"
    except OSError:
        return ""


class RoleState(NamedTuple):
    role: str
    conv_id: str
    parent_id: str | None
    actions: tuple[str, ...]
    depth: int = 0
    staffed: bool = False
    captained: bool = False
    captain_mode: str = "manager_tree"


def current_role(db, attachment_id: str) -> RoleState:
    from .auth_guard import Principal
    from .hierarchy_contracts import CapabilityState
    from .machine_scope import capability_state

    att = db.get_attachment(attachment_id)
    if att is None:
        raise ValueError("attachment no longer exists")
    principal = Principal(kind="machine", name=att["name"], conv_id=att["conv_id"],
                          attachment_id=att["id"], is_lead=bool(att.get("is_lead")))
    state = CapabilityState.model_validate(capability_state(db, principal))
    return RoleState(state.role, att["conv_id"], state.parent_id, tuple(state.actions),
                     line_depth(db, att["conv_id"]),
                     staffed_split_reason(db, att["conv_id"]) is not None,
                     has_captain(db, att["conv_id"]),
                     db.get_conversation(att["conv_id"]).get("captain_mode", "manager_tree"))


def _instructions(state: RoleState, db=None) -> str:
    """The pack for a state: the captain's, else the worker's when a captain is live."""
    from .orchestrator_pack import task_pack
    pack = task_pack(db, state.conv_id, state.role) or role_instructions(
        state.actions, state.conv_id, state.parent_id, state.depth, state.staffed, state.captain_mode
    ) or worker_instructions(state.captained)
    if state.role == "lead" and state.parent_id is None and hasattr(db, "get_setting"):
        from .resource_budget import snapshot
        capacity = snapshot(db)
        reserved = capacity["memory_reserved_bytes"] / 1024**3
        capped = capacity["memory_cap_bytes"] / 1024**3
        budget = capacity["memory_budget_bytes"] / 1024**3
        pack += (f"\n\nInstance capacity: {capacity['live_processes']}/"
                 f"{capacity['max_live_processes']} processes, {reserved:.0f} of {budget:.0f} GB reserved "
                 f"({capped:.0f} GB cap).")
    return pack


def briefing_pointer(conv_id: str) -> str:
    return f"(captain pack: GET /api/conversations/{conv_id}/briefing)"


def bind_role_delivery(db, att: dict, runtime=None) -> None:
    from .captain_handover import state_text
    initial = current_role(db, att["id"])
    att["role_briefing"] = "\n\n".join(
        part for part in (_instructions(initial, db), pack_for(db, att["id"]),
                          state_text(db, att["id"])) if part)
    original_rider = att["digest_rider"]
    # The startup briefing already carries the pack for both fresh and resumed
    # attachments.  A resume therefore starts at the current role just like a
    # fresh attachment; a later role change still produces a new pack.
    previous = initial
    last_goal = last_staffing = last_handoff = None
    last_docs_id = None
    last_resource_at = 0.0
    worker_reminder_sent = False

    def rider() -> str:
        nonlocal previous, last_goal, last_staffing, last_handoff, worker_reminder_sent
        nonlocal last_docs_id, last_resource_at
        nonlocal last_docs_id
        current = current_role(db, att["id"])
        update = ""
        captain_transition = previous is None or (
            (previous.role == "lead") != (current.role == "lead")
        )
        worker_transition = previous is None or previous.captained != current.captained
        worker_now = current.role != "lead" and current.captained
        worker_was = previous is not None and previous.role != "lead" and previous.captained
        if current.role != "lead":
            last_goal = last_staffing = last_handoff = None
        mode_transition = current.captain_mode != previous.captain_mode
        if current != previous:
            demoted = previous is not None and previous.role == "lead" and current.role != "lead"
            previous = current
            if captain_transition or (worker_now and worker_transition) or mode_transition:
                update = _instructions(current, db)
            if demoted and update:
                update += ("\nYour current role is ordinary participant, not captain. "
                           "Use only your own line's tools.")
            elif not update and (demoted or (worker_was and not worker_now)):
                update = ("Your current role is ordinary participant, not captain. "
                          "Use only your own line's tools.")
        goal = staffing = handoff = worker = pointer = docs = resource = ""
        if current.role == "lead":
            current_goal = goal_rider(db, current.conv_id)
            current_staffing = staffing_line(db, current.conv_id, runtime=runtime)
            current_handoff = handoff_rider(db, current.conv_id)
            goal = _delta(current_goal, last_goal, "goal")
            staffing = _delta(current_staffing, last_staffing, "staffing")
            handoff = _delta(current_handoff, last_handoff, "hand-offs")
            last_goal, last_staffing, last_handoff = (
                current_goal, current_staffing, current_handoff)
            docs, last_docs_id = reminder_line(db, current.conv_id, last_docs_id)
            if time.time() - last_resource_at >= RESOURCE_RIDER_INTERVAL:
                last_resource_at = time.time()
                from .attachment_tmp import tmp_resource_line

                resource = "\n".join(
                    part for part in (host_resource_line(),
                                      tmp_resource_line(db, current.conv_id))
                    if part)
            if not captain_transition:
                pointer = briefing_pointer(current.conv_id)
        elif current.captained:
            if not worker_reminder_sent or (worker_now and not worker_was):
                worker = WORKER_REMINDER
            worker_reminder_sent = True
            from .line_notes import notes_nudge

            nudge = notes_nudge(db, current.conv_id, att["id"],
                                current_turns(db, att["id"]))
            if nudge:
                worker = f"{worker}\n{nudge}" if worker else nudge
        else:
            worker_reminder_sent = False
        return "\n".join(
            part for part in (original_rider(), state_text(db, att["id"]), goal, staffing, handoff,
                              update, worker,
                              pointer, docs, resource)
            if part)

    att["digest_rider"] = rider


def _delta(value: str, previous: str | None, label: str) -> str:
    if value == previous:
        return ""
    if value:
        return value
    return f"({label} cleared)" if previous else ""


async def announce_restored(runtime, att: dict, *, restart: bool = True) -> None:
    """Tell a resumed bridge ambassador its bridge survived the restart.

    Queued on its cursor, not forced: the reattachment's own continuation wake
    delivers the backlog, this notice and any bridge copy that was waiting.
    """
    from .bridge_store import open_bridge_for_attachment, side, side_view
    from .mention_relay import post_private

    bridge = open_bridge_for_attachment(runtime.db, att["id"])
    if bridge is None:
        return
    peer = side_view(runtime.db, bridge, side(bridge, att["id"])[1])
    after = " after the restart" if restart else ""
    await post_private(
        runtime, att["conv_id"], "system", "system",
        f"⇄ bridge restored{after}: you are still this line's ambassador to "
        f"@{peer['name']} on «{peer['conv_name']}»; the bridge pack is in your briefing; "
        f"address it by writing @[bridge]{peer['name']} in a normal chat message — "
        "there is no bridge tool",
        audience=att["id"], source=(None, att["conv_id"]), route=False)
