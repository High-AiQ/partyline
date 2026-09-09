"""What an adapter's harness can tell us about itself.

Kept apart from `reattach.py`, which owns resume and was at its size limit:
these answer a different question — not "can this be brought back" but "does
this CLI report its own turn boundaries" — and the presence path needs the
second without dragging in the first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .adapters import ADAPTER_METADATA, ADAPTERS


def adapter_completion(kind: str) -> str:
    """Whether this adapter's harness reports its own turn boundaries.

    ``receipt`` when the manifest declares it, ``none`` otherwise. ``none``
    means the server never clears the badge on its own, so an adapter that
    has not proved it has a receipt is treated as though it has none — the
    failure mode of guessing is a badge that lies, which is the whole reason
    `presence.py` was rewritten.
    """
    metadata = ADAPTER_METADATA.get(kind) or {}
    capabilities = metadata.get("capabilities") or {}
    turn_end = capabilities.get("turn_end") if isinstance(capabilities, dict) else None
    return "receipt" if turn_end == "receipt" else "none"


def claims_transcript(att: dict) -> bool:
    """Whether this attachment's harness owns a structured transcript that it
    must claim before anything typed at it counts as delivered.

    Transcript adapters prove identity by content — claude's claim token, the
    antigravity conversation read-back — so a paste into one is only a probe
    until the claim shows up in the transcript. A bare process owns no
    session to claim and keeps the paste-and-credit contract it always had.
    """
    capabilities = (att.get("adapter_metadata") or {}).get("capabilities") or {}
    return bool(capabilities.get("transcript"))


def transcript_claimed(adapter) -> bool:
    """Whether the adapter has opened the transcript it claimed."""
    return getattr(adapter, "_ready_result", None) is True


@dataclass(frozen=True)
class ImmediateMentions:
    """Whether a mention reaches this adapter's *running* turn, and why.

    Two separate questions, deliberately not collapsed into one boolean.
    ``supported`` is a claim the adapter package makes about its harness.
    ``effective`` is whether it holds for this host right now, which for some
    harnesses depends on the user's own CLI configuration. Advertising the
    first as though it were the second is how a room ends up believing a
    message arrived promptly when it is still sitting behind a turn boundary.
    """

    supported: bool
    effective: bool
    detail: str


def adapter_supports_immediate_mentions(kind: str) -> bool:
    """Whether this adapter claims it can deliver into an active turn.

    False for every adapter that does not say otherwise. Writing bytes at a
    terminal is not delivery: most harnesses read the composer only at a turn
    boundary, so silence in a manifest means the safe answer, not the
    convenient one.
    """
    metadata = ADAPTER_METADATA.get(kind) or {}
    capabilities = metadata.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        return False
    return capabilities.get("immediate_mentions") is True


def immediate_mentions(kind: str, env: Mapping[str, str] | None = None) -> ImmediateMentions:
    """Resolve the capability against this host.

    An adapter whose harness needs no host prerequisite is effective as soon
    as it claims support. One that does — Grok needs `follow_up_behavior =
    "steer"` — publishes a ``immediate_mentions_preflight`` on its class and
    is only effective when that preflight passes.
    """
    if not adapter_supports_immediate_mentions(kind):
        return ImmediateMentions(False, False, f"{kind} does not support immediate mentions")
    preflight = getattr(ADAPTERS.get(kind), "immediate_mentions_preflight", None)
    if preflight is None:
        return ImmediateMentions(True, True, f"{kind} delivers into the active turn")
    effective, detail = preflight(env)
    return ImmediateMentions(True, bool(effective), detail)
