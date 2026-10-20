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
from pydantic import ValidationError

from .bind import BindConfig
from .adapter_capabilities import compaction_hooks
from .contracts import AttentionEvent, OkResponse
from .hook_contracts import hook_validation_detail, parse_hook_payload

ATTENTION_RE = re.compile(r"permission|approv|trust|login|auth", re.IGNORECASE)


async def surface_attention(runtime, att: dict, message: str) -> None:
    """Post and broadcast the shared human-attention signal for an attachment."""
    await runtime.post_message(
        att["conv_id"], "system", "system",
        f"⏸ @{att['name']} needs attention: {message} — use peek to view/answer the dialog",
    )
    await runtime.broadcast(att["conv_id"], AttentionEvent(attachment_id=att["id"]))


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
        raise HTTPException(422, "hook payload is not JSON") from None
    try:
        payload = parse_hook_payload(body)
    except ValidationError as exc:
        raise HTTPException(422, hook_validation_detail(exc)) from exc
    boundary = payload.turn_boundary()
    if boundary == "began":
        from .compaction_events import bump_turn

        bump_turn(runtime.db, att_id, token)
        await presence.began(att["conv_id"], att_id, owner=token)
        from .orchestrator_stall import began as task_began

        await task_began(runtime, att)
        adapter = getattr(runtime, "live", {}).get(att_id)
        mark_began = getattr(adapter, "mark_startup_prompt_began", None)
        if mark_began is not None:
            mark_began()
    elif boundary == "ended":
        await presence.ended(att["conv_id"], att_id, owner=token)
    if payload.event == "precompact":
        # Compaction is an adapter capability: only a harness whose metadata
        # declares compaction_hooks is counted, so a stray hook from another
        # CLI posting this URL never invents an event.
        from .compaction_events import note_hook_compaction

        if compaction_hooks(att):
            await note_hook_compaction(runtime, att, payload.trigger or "manual")
        return {"ok": True}
    message = (payload.message or payload.title or "").strip()
    # Only surface events that mean "a human must look at me" — idle chatter
    # from an agent waiting between mentions would spam the line.
    if message and ATTENTION_RE.search(message):
        await surface_attention(runtime, att, message)
    return {"ok": True}


def hooks_router(runtime, presence) -> APIRouter:
    router = APIRouter()

    @router.post("/api/hooks/{att_id}/{token}", response_model=OkResponse)
    async def hook_event(att_id: str, token: str, request: Request):
        return await handle_hook(runtime, presence, att_id, token, request)

    @router.get("/api/hooks/{att_id}/{token}/rebrief")
    async def rebrief(att_id: str, token: str):
        # SessionStart(compact) prints this to stdout, and Claude folds hook
        # stdout into the model's context: the body IS the feature, so it is
        # plain text and never JSON.
        from fastapi.responses import PlainTextResponse

        from .rebrief import render_rebrief

        att = authorize(runtime, att_id, token)
        if not compaction_hooks(att):
            raise HTTPException(
                403, "this adapter does not expose compaction hooks")
        return PlainTextResponse(render_rebrief(runtime.db, att), media_type="text/plain")

    return router
