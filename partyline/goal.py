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
from .line_depth import may_create_children
from .machine_scope import deny_unless

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


def goal_rider(db, conv_id: str) -> str:
    """The goal line of a manager's wake digest, with the standing rule; the
    rule alone when no goal is recorded."""
    conv = db.get_conversation(conv_id) or {}
    goal = " ".join(str(conv.get("goal") or "").split())
    rule = MANAGER_REMINDER if may_create_children(db, conv_id) else LEAF_REMINDER
    if not goal:
        return f"({rule})"
    return f"(goal you are seeing through: {goal}; {rule})"


def register_goal_route(app: FastAPI, runtime) -> None:
    @app.put("/api/conversations/{conv_id}/goal", response_model=ConversationResponse)
    async def put_goal(request: Request, conv_id: str, body: GoalIn):
        db = runtime.db
        principal = request_principal(request)
        # Managers own the goal of their line; a person may set any line's.
        deny_unless(db, principal, conv_id, "create_child")
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
        await runtime.post_message(conv_id, "system", "system", notice)
        await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
        return conv
