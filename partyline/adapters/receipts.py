"""Turn-boundary receipts an adapter posts to its own hook URL.

Receipts enter presence through the same token-authorized door the claude and
grok harnesses use (see `hook_routes.py`): the attachment's ``hook_url``
carries its per-activation capability token, so an adapter-observed boundary
is owner-checked exactly like a harness hook. Adapters that can *see* their
harness's turn boundaries in a transcript they already tail — opencode's
session store, codex's rollout — report them through here rather than growing
a parallel channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

# The event names the hook contract already folds: a pasted digest begins a
# turn, and any completed non-tool-calls assistant message ends one.
BEGAN = "UserPromptSubmit"
ENDED = "Stop"


def _post(url: str, event: str) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps({"hookEventName": event}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5):
        pass


async def receipt(att: dict, event: str) -> None:
    """Fire-and-forget a turn boundary; never raise into a tail loop.

    A lost receipt degrades to the pre-receipt behavior — a badge that stays
    lit until the process exits — so failures are never retried: the tail
    cannot know whether a retry would land after a newer turn has already
    opened, and presence treats a stale ending as a lie. But a systematically
    dead receipt path must stay diagnosable: loud in the log, invisible to
    the delivery.
    """
    url = att.get("hook_url")
    if not url:
        return
    try:
        await asyncio.to_thread(_post, url, event)
    except Exception:
        logger.exception("turn receipt %r for @%s never arrived", event, att.get("name"))
