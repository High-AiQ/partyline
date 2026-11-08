"""Render checks over a local tools session: the route that holds the person's consent in place.

The decision model is a hosted service, so a render leaves this host only when every one of these is true; the
caller is told the first one that is not, in plain words:

* the session is live and held by the caller, and the person allowed render checks in it (the separate box in
  the dialog, or the later dialog that asks for only that), and has not withdrawn them since;
* each image is a render this very session produced (never a screenshot, another session's image or an upload)
  and was rendered while that permission existed (`checkable`).

The scope is checked again before every request to the model, so withdrawing it on the computer stops a run in
progress. The key never leaves `render_check.py`. Every check is written to the audit with the images sent.
"""
import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import render_check
from .auth_guard import request_principal
from .machine_scope import deny_unless

MAX_EVIDENCE = 16 * 1024
MAX_VARIANTS = 6
Text = Annotated[str, Field(min_length=1, max_length=500)]


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=12)
    questions: list[Text] = Field(default_factory=list, max_length=12)
    compare: Text | None = None
    reference: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    evidence: dict | None = None


def authorize(item, agent, ids):
    """Raise ValueError naming the reason when this session may not send these renders to the model."""
    if not item or item.status != "active":
        raise ValueError("local tools are not granted; ask the person with a request first")
    if item.agent != agent:
        raise ValueError(f"local tools were granted to {item.agent}")
    if not item.checker:
        raise ValueError("this session has no render-check permission: ask for it with checker=true, and the "
                         "person has to agree on their computer (renders never leave without it)")
    for file_id in ids:
        known = item.renders.get(file_id)
        if known is None:
            raise ValueError(f"{file_id} is not a render produced in this session; only this session's own "
                             "renders can be checked (not screenshots, uploads or earlier sessions)")
        if not known:
            raise ValueError(f"{file_id} was rendered before render checks were allowed; render it again")


def validate(body):
    if not body.questions and not body.compare:
        raise ValueError("ask at least one question, or a compare question over several images")
    if body.compare and not 2 <= len(body.media) <= MAX_VARIANTS:
        raise ValueError(f"compare picks among 2 to {MAX_VARIANTS} images")
    if body.evidence is not None and len(json.dumps(body.evidence)) > MAX_EVIDENCE:
        raise ValueError(f"evidence is larger than {MAX_EVIDENCE} bytes; send the relevant part")


def load(store, ids):
    """The stored bytes of each image id, in order."""
    out = []
    for file_id in ids:
        found = store.file_for(file_id, "original")
        if found is None:
            raise ValueError(f"{file_id} can no longer be read")
        out.append((file_id, found[0].read_bytes()))
    return out


def summary(result, body):
    """The audit line: counts of verdicts and exactly which images went to the model."""
    verdicts = {}
    for entry in result["frames"]:
        verdicts[entry["verdict"]] = verdicts.get(entry["verdict"], 0) + 1
    return (f"render_check {len(body.questions)} questions{' + compare' if body.compare else ''}: "
            f"{json.dumps(verdicts, sort_keys=True)} calls {result['calls']} "
            f"tokens {result['input_tokens']}; "
            f"images sent to the model: {', '.join(result['sent']) or 'none'} "
            "(recorded as each request left, even if it then failed)")[:900]


def render_check_router(runtime, hub, store, decisions=None) -> APIRouter:
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/local-tools/render-check")
    async def check(conv_id: str, body: CheckBody, request: Request):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        item = hub.tools.sessions.get(conv_id)
        limit = hub.tools.limits.render_checks
        try:
            authorize(item, principal.name, [*body.media, *([body.reference] if body.reference else [])])
            validate(body)
            images = await asyncio.to_thread(load, store, body.media)
            ref = body.reference
            reference = (await asyncio.to_thread(load, store, [ref]))[0][1] if ref else None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

        def allowed():
            live = hub.tools.sessions.get(conv_id) is item and item.status == "active" and item.checker
            return None if live else "render checks were switched off during the call"

        def spend():
            if item.checks >= limit:
                return False
            item.checks += 1
            return True

        result = await render_check.check(
            images, body.questions, compare=body.compare, reference=reference, evidence=body.evidence,
            decisions=decisions, spend=spend, allowed=allowed)
        await hub.tools.note(item, "render_check", summary(result, body))
        return {**result, "budget": {"used": item.checks, "max": limit}}

    return router
