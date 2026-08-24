"""What an adapter's harness can tell us about itself.

Kept apart from `reattach.py`, which owns resume and was at its size limit:
these answer a different question — not "can this be brought back" but "does
this CLI report its own turn boundaries" — and the presence path needs the
second without dragging in the first.
"""

from __future__ import annotations

from .adapters import ADAPTER_METADATA


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
