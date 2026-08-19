"""Harness hook payloads: a named contract, not a bag of .get()s.

Grok POSTs snake_case `stop`; Claude POSTs PascalCase `Stop`. Folding those
onto one key lives here, inside the model, so an unseen dialect is a 422
rather than a dropped receipt. Known non-boundary events (Notification,
SubagentStop) still parse — they just do not begin or end a turn.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

# Folded names. Dialects are accepted at the field, then reduced to these.
TURN_BOUNDARIES: dict[str, Literal["began", "ended"]] = {
    "userpromptsubmit": "began",
    "stop": "ended",
    "stopfailure": "ended",
    "stopcancelled": "ended",
}

KNOWN_EVENTS = frozenset({
    *TURN_BOUNDARIES,
    "notification",
    "subagentstop",
})

TurnBoundary = Literal["began", "ended"]


def fold_hook_event(name: str) -> str:
    """Claude `Stop` and Grok `stop` / `stop_cancelled` become one key."""
    return name.replace("_", "").lower()


class HookPayload(BaseModel):
    """One harness POST. Extra vendor fields are kept off the contract."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    event: str = Field(validation_alias=AliasChoices("hookEventName", "hook_event_name"))
    message: str | None = None
    title: str | None = None

    @field_validator("event", mode="before")
    @classmethod
    def _fold_known_event(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "hook payload needs hookEventName (or hook_event_name)"
            )
        folded = fold_hook_event(value)
        if folded not in KNOWN_EVENTS:
            known = ", ".join(sorted(KNOWN_EVENTS))
            raise ValueError(
                f"unrecognized hook event {value!r}; known names fold to: {known}"
            )
        return folded

    def turn_boundary(self) -> TurnBoundary | None:
        return TURN_BOUNDARIES.get(self.event)


def hook_validation_detail(exc: ValidationError) -> str:
    """The first human-readable error, without Pydantic's 'Value error, ' prefix."""
    for error in exc.errors():
        message = str(error.get("msg") or "")
        if message.startswith("Value error, "):
            return message.removeprefix("Value error, ")
        if message:
            return message
    return "invalid hook payload"


def parse_hook_payload(body: object) -> HookPayload:
    """Raise ValidationError with a message handle_hook can put on a 422."""
    return HookPayload.model_validate(body)
