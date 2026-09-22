"""A line's goal: what its manager is seeing through, said once, carried on every wake.

Three fleet trials in, the only state a root manager ever had to hold in its
head was the goal — and the heartbeat's whole failure was that it reminded
the manager of the clock instead. The goal is recorded once, by the person
or by the manager when the person states it, and rides the manager's digest
rider until it is cleared. Ordinary participants do
not receive it: the line's topic is the standing context for everyone, the
goal is the manager's charge.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .auth_guard import request_principal
from .contracts import ConversationEvent, ConversationResponse
from .line_depth import may_create_children, staffed_split_reason
from .machine_scope import deny_unless
from .system_notice import post_system_notice

MAX_GOAL = 3000


class GoalIn(BaseModel):
    goal: str = ""


def set_goal(db, conv_id: str, goal: str) -> dict:
    db._exec("UPDATE conversations SET goal=? WHERE id=?", (goal, conv_id))
    return db.get_conversation(conv_id)


# Rides every manager wake next to the goal, because the pack scrolls away and
# the one rule a manager drifts from mid-project is this one.
MANAGER_REMINDER = "you are the captain — delegate to a sub-captain, review, decide; you do not implement"
LEAF_REMINDER = ("you are the leaf captain — staff workers on this line, review, decide; "
                 "no sub-captains; you do not implement")
STAFFED_REMINDER = ("you are the captain — the workers on this line are yours: assign them, "
                    "review, decide; no sub-captains while they are here; you do not implement")


def captain_rule(db, conv_id: str) -> str:
    if staffed_split_reason(db, conv_id):
        return STAFFED_REMINDER
    return MANAGER_REMINDER if may_create_children(db, conv_id) else LEAF_REMINDER


def goal_rider(db, conv_id: str) -> str:
    """The goal line of a manager's wake digest."""
    conv = db.get_conversation(conv_id) or {}
    goal = " ".join(str(conv.get("goal") or "").split())
    if not goal:
        return ""
    rule = captain_rule(db, conv_id)
    return f"(goal you are seeing through: {goal}; {rule})"


def register_goal_route(app: FastAPI, runtime) -> None:
    @app.put("/api/conversations/{conv_id}/goal", response_model=ConversationResponse)
    async def put_goal(request: Request, conv_id: str, body: GoalIn):
        db = runtime.db
        principal = request_principal(request)
        # The line's captain, a captain above it, or a person. Not create_child:
        # a leaf captain has no children to create and still owns its goal.
        deny_unless(db, principal, conv_id, "assign")
        conv = db.get_conversation(conv_id)
        if conv is None:
            raise HTTPException(404)
        goal = body.goal.strip()
        if len(goal) > MAX_GOAL:
            raise HTTPException(400, f"goal is capped at {MAX_GOAL} characters")
        if goal == (conv.get("goal") or ""):
            return conv
        conv = set_goal(db, conv_id, goal)
        who = f" by @{principal.name}"
        notice = f"☏ goal set{who}: {goal}" if goal else f"☏ goal cleared{who}"
        await post_system_notice(runtime, conv_id, notice, actor=principal)
        await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
        return conv
