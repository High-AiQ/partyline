"""The endpoint a process's *harness* — never the process — posts to.

Split out of `server.py` when the URL gained a capability token: the reason
this route needs one is long enough to be worth writing down, and `server.py`
is over the file-size limit already.

The token is the attachment's ``runtime_owner``. An attachment id is not a
secret — it is printed in the join notice and used as the CLI session name —
so an untokened route here is writable by anything that can reach the server,
and the server now binds the LAN rather than loopback. Because the owner is
minted fresh per activation, a hook left over from a previous server
generation fails the check for free instead of acting on a pty this runtime
no longer drives.

That matters more than it looks. `presence.py` exists to keep liveness out of
the hands of the thing it describes; a forgeable receipt arriving here would
put it straight back.
"""

from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, HTTPException, Request

from .bind import BindConfig
from .contracts import AttentionEvent, HookEventRequest, OkResponse

ATTENTION_RE = re.compile(r"permission|approv|trust|login|auth", re.IGNORECASE)

# Canonical (lowercase, no underscores) harness event names that bound a
# turn. Config keys are PascalCase (`Stop`); Grok's stdin `hookEventName` is
# snake_case (`stop`). Matching only the Claude spelling left Grok badges
# lit after every wake — the POST arrived, then `turn_boundary` returned None.
# `SubagentStop` is deliberately absent: a child finishing is not the parent
# turn ending. Grok's `StopFailure` / `StopCancelled` replace `Stop` when a
# turn errors or is interrupted, so they must clear the badge too.
TURN_BOUNDARIES = {
    "userpromptsubmit": "began",
    "stop": "ended",
    "stopfailure": "ended",
    "stopcancelled": "ended",
}


def canonical_hook_event(name: str) -> str:
    """Fold Claude's PascalCase and Grok's snake_case onto one key."""
    return name.replace("_", "").lower()


def turn_boundary(payload: object) -> str | None:
    """Which end of a turn this hook payload reports, if either.

    Only the harness's own event name counts. Nothing an agent can write into
    a message reaches this function, and an unrecognised name is ignored
    rather than guessed at.
    """
    if not isinstance(payload, dict):
        return None
    name = payload.get("hookEventName") or payload.get("hook_event_name")
    if not isinstance(name, str):
        return None
    return TURN_BOUNDARIES.get(canonical_hook_event(name))


def hook_url(att_id: str, bind: BindConfig, token: str = "") -> str:
    """Where this attachment's harness should post, token included."""
    host = f"[{bind.host}]" if ":" in bind.host else bind.host
    return f"http://{host}:{bind.port}/api/hooks/{att_id}/{token}"


def authorize(runtime, att_id: str, token: str) -> dict:
    """The attachment this token is allowed to speak for.

    A mismatch is answered 404 rather than 403, so a caller working through
    guessed ids is not told which of them exist.
    """
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    owner = att.get("runtime_owner") or ""
    if not owner or not secrets.compare_digest(token, owner):
        raise HTTPException(404)
    return att


async def handle_hook(runtime, presence, att_id: str, token: str, request: Request) -> dict:
    """Receiver for process-side hooks: turn boundaries and attention.

    The token has already proved this is the current activation, so a receipt
    is passed to presence with that owner: a hook left over from a previous
    generation, or fired by another session of the same CLI on this machine,
    never reaches an open turn it does not own.
    """
    att = authorize(runtime, att_id, token)
    try:
        body = await request.json()
    except Exception:
        body = None
    boundary = turn_boundary(body)
    if boundary == "began":
        await presence.began(att["conv_id"], att_id, owner=token)
    elif boundary == "ended":
        await presence.ended(att["conv_id"], att_id, owner=token)
    try:
        payload = HookEventRequest.model_validate(body)
    except Exception:
        payload = HookEventRequest()
    message = (payload.message or payload.title or "").strip()
    # Only surface events that mean "a human must look at me" — idle chatter
    # from an agent waiting between mentions would spam the line.
    if message and ATTENTION_RE.search(message):
        await runtime.post_message(
            att["conv_id"], "system", "system",
            f"⏸ @{att['name']} needs attention: {message} — use peek to view/answer the dialog",
        )
        await runtime.broadcast(att["conv_id"], AttentionEvent(attachment_id=att_id))
    return {"ok": True}


def hooks_router(runtime, presence) -> APIRouter:
    router = APIRouter()

    @router.post("/api/hooks/{att_id}/{token}", response_model=OkResponse)
    async def hook_event(att_id: str, token: str, request: Request):
        return await handle_hook(runtime, presence, att_id, token, request)

    return router
