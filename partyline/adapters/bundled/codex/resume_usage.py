"""Model usage for a resumed Codex process, whose speech is relayed from thread history.

The thread-history store holds no token counts, but the resumed turns are still written to a
rollout under the same private home. This reads that rollout for usage only: it never claims
it, narrows the watch, marks readiness or posts, so the thread-history relay is unchanged.
"""

import asyncio
import contextlib
import glob
import json
import logging
import os

from partyline.adapters.bundled.codex.thread_history import tail_thread_history

logger = logging.getLogger(__name__)


def _matches(path: str, session: str) -> bool | None:
    """Whether this rollout is, or was forked from, the resumed session; None while unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            payload = json.loads(fh.readline()).get("payload") or {}
    except (OSError, ValueError, AttributeError):
        return None  # a fork is created before its first line lands: look again on the next wake
    if "subagent" in json.dumps(payload.get("source") or {}):
        return False
    return session in (payload.get("forked_from_id"), payload.get("session_id"), payload.get("id"))


def _rollouts(home: str) -> list[str]:
    return sorted(glob.glob(os.path.join(home, "sessions", "**", "rollout-*.jsonl"), recursive=True))


def _read_from(path: str, offset: int) -> bytes:
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            return fh.read()
    except OSError:
        return b""


class _Source:
    """One rollout followed from its start, with its own parser so forks never share state."""

    def __init__(self, path: str, parser):
        self.path, self.parser, self.offset, self.pending = path, parser, 0, b""

    async def drain(self, adapter) -> bool:
        chunk = await asyncio.to_thread(_read_from, self.path, self.offset)
        self.offset += len(chunk)
        *lines, self.pending = (self.pending + chunk).split(b"\n")
        for line in lines:
            with contextlib.suppress(ValueError):
                await adapter.note_turn_usage(json.loads(line), self.parser)
        return bool(chunk)


async def _usage_tail(adapter, home: str, session: str) -> None:
    """Follow every rollout of this session, including a fork created after the first one."""
    sources: dict[str, _Source] = {}
    other: set[str] = set()
    while adapter.alive():
        for path in await asyncio.to_thread(_rollouts, home):
            if path in sources or path in other:
                continue
            match = await asyncio.to_thread(_matches, path, session)
            if match:
                sources[path] = _Source(path, adapter.turn_parser())
            elif match is False:
                other.add(path)
        moved = False
        for source in sources.values():
            moved = await source.drain(adapter) or moved
        if not moved:
            await adapter.wait_for_change()


async def _guarded(adapter, home: str, session: str) -> None:
    try:
        await _usage_tail(adapter, home, session)
    except Exception:  # telemetry must never reach the relay
        logger.debug("resumed codex usage not recorded", exc_info=True)


async def tail_history_with_usage(adapter, home: str, thread_id: str) -> bool:
    """``tail_thread_history``, with this process's rollout read alongside for model usage."""
    task = asyncio.get_running_loop().create_task(_guarded(adapter, home, thread_id))
    try:
        return await tail_thread_history(adapter, home, thread_id)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
