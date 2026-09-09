"""The cockpit's authenticated HTTP client, split from `cockpit.py` for its line cap."""

from __future__ import annotations

import json
import os
from http.client import HTTPResponse
from typing import Protocol
from itertools import takewhile
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from pydantic import TypeAdapter

from scripts.cockpit_venv import fetch_version
from partyline.contracts import (
    ConversationResponse,
    RestartPlanMode,
    RestartPlanRequest,
    RestartPlanResponse,
    RestartPlanScope,
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


# The release that taught the server `scope="all"` and made every candidate
# name its own line. An older server ignores the unknown field and silently
# returns a line-scoped plan, which the orphan refusal would then reject with
# no way forward — so the refusal happens here, with the way forward in it.
FLEET_PLAN_MIN_VERSION = (0, 63, 0)


def _version_tuple(text: str) -> tuple[int, ...]:
    """Compare release numbers without pulling in a version library."""
    parts: list[int] = []
    for piece in str(text).split("."):
        digits = "".join(takewhile(str.isdigit, piece))
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def refuse_unsupported_fleet_plan(base_url: str, get_version=fetch_version) -> None:
    """Refuse `--all` against a server that cannot honour it.

    This is the one restart that cannot be planned fleet-wide, because the
    running server predates the feature being deployed. `docs/dogfooding.md`
    records the bootstrap: plan the cockpit line, close the other lines'
    processes deliberately, arm, then reattach them.
    """
    try:
        live = str((get_version(base_url) or {}).get("version", ""))
    except Exception as exc:
        raise ValueError(
            f"could not read the live version to check --all support: {exc}"
        ) from exc
    if _version_tuple(live) < FLEET_PLAN_MIN_VERSION:
        wanted = ".".join(str(part) for part in FLEET_PLAN_MIN_VERSION)
        raise ValueError(
            f"the running server is {live or 'an unreadable version'} and ignores --all; "
            f"fleet planning needs {wanted}. For this one bootstrap restart, plan the "
            "cockpit line alone, close every other line's processes deliberately, arm, "
            "and reattach them afterwards — see docs/dogfooding.md"
        )


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
    scope: RestartPlanScope = "line",
) -> RestartPlanResponse:
    """Persist a plan in the running cockpit, without restarting it.

    The selector always names the line that *owns* the plan — where a manual
    offer appears and where a failure is reported. ``scope="all"`` widens which
    processes it recovers, never which line owns it."""
    conversations_request = _authorized(Request(urljoin(base_url, "/api/conversations")))
    with open_url(conversations_request) as response:
        conversations = TypeAdapter(list[ConversationResponse]).validate_json(response.read())
    conversation = resolve_line(conversations, selector)
    if scope == "all":
        # Asked through the injected opener, so a test never dials a network
        # and a caller never has to remember a second injection point.
        def version(url: str) -> dict:
            with open_url(_authorized(Request(urljoin(url, "/api/version")))) as response:
                return json.loads(response.read())

        refuse_unsupported_fleet_plan(base_url, version)
    body = RestartPlanRequest(
        conversation_id=conversation.id,
        debrief=debrief,
        mode=mode,
        scope=scope,
    )
    request = _authorized(Request(
        urljoin(base_url, "/api/restart-plan"),
        data=body.model_dump_json().encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    ))
    with open_url(request) as response:
        return RestartPlanResponse.model_validate_json(response.read())
