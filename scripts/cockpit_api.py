"""The cockpit's authenticated HTTP client, split from `cockpit.py` for its line cap."""

from __future__ import annotations

import os
from http.client import HTTPResponse
from typing import Protocol
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from pydantic import TypeAdapter

from partyline.contracts import (
    ConversationResponse,
    RestartPlanMode,
    RestartPlanRequest,
    RestartPlanResponse,
)


class ResponseOpener(Protocol):
    def __call__(self, request: Request) -> HTTPResponse: ...


def resolve_line(
    conversations: list[ConversationResponse], selector: str
) -> ConversationResponse:
    """Resolve an exact id or unique case-insensitive name without guessing."""
    if found := next((line for line in conversations if line.id == selector), None):
        return found
    matches = [line for line in conversations if line.name.casefold() == selector.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(f"line name {selector!r} is ambiguous; use its id")
    raise ValueError(f"no live line matches {selector!r}")


def _authorized(request: Request) -> Request:
    """Attach the PARTYLINE_TOKEN credential every attached process holds
    (a human shell exports theirs). A missing credential is refused here,
    before the network — a guessed or absent identity must fail loudly."""
    token = os.environ.get("PARTYLINE_TOKEN")
    if not token:
        raise SystemExit(
            "PARTYLINE_TOKEN is not set; export your partyline credential "
            "before calling the cockpit API")
    request.add_header("Authorization", f"Bearer {token}")
    return request


def schedule_restart_plan(
    selector: str,
    debrief: str,
    base_url: str,
    open_url: ResponseOpener = urlopen,
    *,
    mode: RestartPlanMode = "automatic",
) -> RestartPlanResponse:
    """Persist a same-line plan in the running cockpit, without restarting it."""
    conversations_request = _authorized(Request(urljoin(base_url, "/api/conversations")))
    with open_url(conversations_request) as response:
        conversations = TypeAdapter(list[ConversationResponse]).validate_json(response.read())
    conversation = resolve_line(conversations, selector)
    body = RestartPlanRequest(
        conversation_id=conversation.id,
        debrief=debrief,
        mode=mode,
    )
    request = _authorized(Request(
        urljoin(base_url, "/api/restart-plan"),
        data=body.model_dump_json().encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    ))
    with open_url(request) as response:
        return RestartPlanResponse.model_validate_json(response.read())
